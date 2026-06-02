"""NFR-17 regression: the daemon adapts to all user actions without any CLI call.

Six scenarios, each ending with a convergence assertion (second sync_once
returns changed == 0). No call to the agents-sync CLI in any test — all
operations are performed directly on the filesystem and driven by sync_once.

  - add:           new artifact appears in a tool directory
  - edit:          existing artifact body edited in place
  - single-remove: one artifact deliberately deleted from one tool
  - bulk-remove:   ≥2 artifacts vanish from one tool in one poll (glitch)
  - rename:        artifact directory renamed on one tool (filesystem mv, AC-1)
  - tool-uninstall: tool root directory removed mid-session
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agents_sync.canonical import load_canonical
from agents_sync.state import load_state

from ._helpers import make_syncer, skill_md

# ──────────────────────────── helpers ────────────────────────────


def _plant(syncer, tool: str, name: str, body: str = "v1") -> Path:
    """Write a SKILL.md into a tool root and return the skill directory."""
    d = syncer.tool_root(tool, "skill") / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(skill_md(name, body=body))
    return d


def _skill_file(syncer, tool: str, name: str) -> Path:
    return syncer.tool_root(tool, "skill") / name / "SKILL.md"


def _adopt_and_sync(syncer, tool: str, *names: str) -> None:
    """Plant skills on *tool*, run sync_once to adopt + project everywhere."""
    for name in names:
        _plant(syncer, tool, name)
    syncer.sync_once()


# ──────────────────────────── add ────────────────────────────────


def test_nfr17_add_artifact_converges_without_cli(tmp_path: Path) -> None:
    """A new artifact created in a tool directory is adopted and projected to
    all tools by one sync_once, with no further change on the second poll."""
    syncer = make_syncer(tmp_path)

    _plant(syncer, "claude", "new-skill")
    first = syncer.sync_once()

    assert first.changed >= 1
    assert _skill_file(syncer, "claude", "new-skill").exists()
    assert _skill_file(syncer, "codex", "new-skill").exists()
    assert load_state(syncer.state_dir)

    assert syncer.sync_once().changed == 0


# ──────────────────────────── edit ───────────────────────────────


def test_nfr17_edit_artifact_converges_without_cli(tmp_path: Path) -> None:
    """An in-place edit on one tool propagates to all others in one sync_once
    and the second poll is a no-op."""
    syncer = make_syncer(tmp_path)
    _adopt_and_sync(syncer, "claude", "my-skill")

    # User edits the body on the claude copy.
    f = _skill_file(syncer, "claude", "my-skill")
    f.write_text(skill_md("my-skill", body="v2"))

    first = syncer.sync_once()
    assert first.changed >= 1
    assert "v2" in _skill_file(syncer, "codex", "my-skill").read_text()

    assert syncer.sync_once().changed == 0


# ──────────────────────── single-remove ──────────────────────────


def test_nfr17_single_remove_propagates_without_cli(tmp_path: Path) -> None:
    """Deleting one artifact from one tool propagates the removal to all
    other tools in one sync_once; the pair is fully dropped from state."""
    syncer = make_syncer(tmp_path)
    _adopt_and_sync(syncer, "claude", "to-delete")

    assert _skill_file(syncer, "codex", "to-delete").exists()

    shutil.rmtree(syncer.tool_root("claude", "skill") / "to-delete")
    syncer.sync_once()

    assert not _skill_file(syncer, "codex", "to-delete").exists()
    assert not load_state(syncer.state_dir)

    assert syncer.sync_once().changed == 0


# ──────────────────────── bulk-remove ────────────────────────────


def test_nfr17_bulk_remove_is_healed_without_cli(tmp_path: Path) -> None:
    """When ≥2 artifacts vanish from one tool in the same poll (glitch:
    uninstall / unmount), the daemon re-heals from the canonical instead of
    propagating the deletion; library is intact after one sync_once."""
    syncer = make_syncer(tmp_path)
    _adopt_and_sync(syncer, "claude", "alpha", "beta")

    assert _skill_file(syncer, "claude", "alpha").exists()
    assert _skill_file(syncer, "claude", "beta").exists()

    # Simulate glitch: both vanish from claude in one poll.
    shutil.rmtree(syncer.tool_root("claude", "skill") / "alpha")
    shutil.rmtree(syncer.tool_root("claude", "skill") / "beta")

    syncer.sync_once()

    # Both re-healed from canonical on the emptied tool.
    assert _skill_file(syncer, "claude", "alpha").exists()
    assert _skill_file(syncer, "claude", "beta").exists()
    # Other tools unaffected.
    assert _skill_file(syncer, "codex", "alpha").exists()
    assert _skill_file(syncer, "codex", "beta").exists()
    # State preserved.
    assert len(load_state(syncer.state_dir)) == 2

    assert syncer.sync_once().changed == 0


# ──────────────────────────── rename ─────────────────────────────


def test_nfr17_rename_directory_converges_without_cli(tmp_path: Path) -> None:
    """US-04 AC-1: a filesystem rename of a skill directory (no metadata
    field change) is recognised via the stable pair_id. The sync engine
    updates the stored path on that tool and converges without re-projecting
    content to other tools (content unchanged)."""
    syncer = make_syncer(tmp_path)
    _adopt_and_sync(syncer, "claude", "demo")

    state_before = load_state(syncer.state_dir)
    pair_id = next(iter(state_before))
    codex_content_before = _skill_file(syncer, "codex", "demo").read_text()

    # Filesystem rename on claude: demo/ → demo-renamed/
    old_dir = syncer.tool_root("claude", "skill") / "demo"
    new_dir = syncer.tool_root("claude", "skill") / "demo-renamed"
    old_dir.rename(new_dir)

    syncer.sync_once()

    # Pair still managed under the same id.
    state_after = load_state(syncer.state_dir)
    assert pair_id in state_after

    # Content on codex unchanged (no field changed, no rewrite needed).
    assert _skill_file(syncer, "codex", "demo").read_text() == codex_content_before

    assert syncer.sync_once().changed == 0


# ─────────────────────── tool-uninstall ──────────────────────────


def test_nfr17_tool_uninstall_preserves_canonical_without_cli(tmp_path: Path) -> None:
    """When a tool's skill root directory is removed mid-session (uninstall),
    the daemon treats it as unavailable and does not propagate its artifact
    absences as deliberate deletions. The canonical and remaining tool files
    are preserved; state is intact; second poll is a no-op."""
    syncer = make_syncer(tmp_path)
    _adopt_and_sync(syncer, "claude", "shared-skill")

    assert _skill_file(syncer, "codex", "shared-skill").exists()
    pair_id = next(iter(load_state(syncer.state_dir)))
    assert load_canonical(syncer.state_dir, pair_id) is not None

    # Simulate tool uninstall: delete the codex skill root entirely.
    codex_root = syncer.tool_root("codex", "skill")
    shutil.rmtree(codex_root)
    assert not codex_root.exists()

    syncer.sync_once()

    # Claude's copy intact.
    assert _skill_file(syncer, "claude", "shared-skill").exists()
    # Canonical preserved (NFR-16).
    assert load_canonical(syncer.state_dir, pair_id) is not None
    # State still holds the pair (not dropped).
    assert pair_id in load_state(syncer.state_dir)

    assert syncer.sync_once().changed == 0
