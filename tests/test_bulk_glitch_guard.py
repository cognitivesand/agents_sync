"""US-11 AC-8/AC-9 (P3): heal-vs-delete by count.

- Exactly ONE recorded artifact vanishing from a tool in a poll = a deliberate
  deletion -> propagated to the other tools.
- TWO OR MORE vanishing from one tool in a single poll = a glitch (uninstall /
  unmount / mid-write) -> not propagated; re-projected from the canonical.
- A glitch on one tool must not suppress a genuine single deletion on another.

FROZEN test contract for v0.6 P3 — do not edit without user feedback.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agents_sync.state import load_state

from ._helpers import make_syncer, skill_md


def _adopt_skill(syncer, name: str) -> Path:
    d = syncer.tool_root("claude", "skill") / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(skill_md(name))
    return d


def _claude_skill(syncer, name: str) -> Path:
    return syncer.tool_root("claude", "skill") / name / "SKILL.md"


def _codex_skill(syncer, name: str) -> Path:
    return syncer.tool_root("codex", "skill") / name / "SKILL.md"


def test_single_deletion_propagates(tmp_path: Path) -> None:
    syncer = make_syncer(tmp_path)
    _adopt_skill(syncer, "solo")
    syncer.sync_once()  # adopt + project everywhere
    assert _codex_skill(syncer, "solo").exists()

    # Delete the only artifact from one tool — a deliberate single deletion.
    shutil.rmtree(syncer.tool_root("claude", "skill") / "solo")
    syncer.sync_once()

    assert not _codex_skill(syncer, "solo").exists()  # removed everywhere
    assert not load_state(syncer.state_dir)  # pair fully dropped


def test_bulk_deletion_is_glitch_and_restored(tmp_path: Path) -> None:
    syncer = make_syncer(tmp_path)
    _adopt_skill(syncer, "alpha")
    _adopt_skill(syncer, "beta")
    syncer.sync_once()  # both adopted + projected everywhere
    assert _codex_skill(syncer, "alpha").exists()
    assert _codex_skill(syncer, "beta").exists()

    # Delete BOTH from one tool in a single poll — a glitch, not a deletion.
    shutil.rmtree(syncer.tool_root("claude", "skill") / "alpha")
    shutil.rmtree(syncer.tool_root("claude", "skill") / "beta")
    syncer.sync_once()

    # Not propagated; re-projected onto the emptied tool from the canonical.
    assert _claude_skill(syncer, "alpha").exists()
    assert _claude_skill(syncer, "beta").exists()
    assert _codex_skill(syncer, "alpha").exists()
    assert _codex_skill(syncer, "beta").exists()
    # And it converges (NFR-05).
    assert syncer.sync_once().changed == 0


def test_glitch_on_one_tool_does_not_suppress_single_on_another(tmp_path: Path) -> None:
    syncer = make_syncer(tmp_path)
    for name in ("alpha", "beta", "gamma"):
        _adopt_skill(syncer, name)
    syncer.sync_once()

    # claude loses two (glitch); codex loses one (deliberate) — same poll.
    shutil.rmtree(syncer.tool_root("claude", "skill") / "alpha")
    shutil.rmtree(syncer.tool_root("claude", "skill") / "beta")
    shutil.rmtree(syncer.tool_root("codex", "skill") / "gamma")
    syncer.sync_once()

    # alpha/beta restored (glitch on claude); gamma deleted everywhere.
    assert _claude_skill(syncer, "alpha").exists()
    assert _claude_skill(syncer, "beta").exists()
    assert not _claude_skill(syncer, "gamma").exists()
    assert not _codex_skill(syncer, "gamma").exists()
