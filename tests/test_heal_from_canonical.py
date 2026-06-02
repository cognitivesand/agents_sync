"""US-11 AC-8 / NFR-16 (P2): the daemon projects (heals) a managed pair that exists
in the canonical store + state but is absent from disk — e.g. a freshly imported
stub recorded on zero tools. The canonical is the source of truth.

FROZEN test contract for v0.6 P2 — do not edit without user feedback.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agents_sync.canonical import empty_canonical, save_canonical, set_canonical_metadata
from agents_sync.state import CustomizationArtifactState, load_state, save_state

from ._helpers import make_syncer

PAIR_ID = "1707fa01-7530-4de0-8332-6351815acb8b"


def _write_stub(syncer, pair_id: str = PAIR_ID, kind: str = "skill", name: str = "demo") -> None:
    """A zero-disk import stub: a canonical + a state entry with no tools recorded."""
    canon = empty_canonical(kind, pair_id)
    canon["name"] = name
    canon["description"] = "d"
    canon["body"] = "hello body"
    set_canonical_metadata(canon, last_modified=1.0, generation=1)
    save_canonical(syncer.state_dir, pair_id, canon)
    state = load_state(syncer.state_dir)
    state[pair_id] = CustomizationArtifactState(kind=kind, agentic_tools={})
    save_state(syncer.state_dir, state)


def test_heal_projects_zero_disk_stub_to_all_supporting_tools(tmp_path: Path) -> None:
    syncer = make_syncer(tmp_path)
    _write_stub(syncer)

    syncer.sync_once()

    claude = syncer.tool_root("claude", "skill") / "demo" / "SKILL.md"
    codex = syncer.tool_root("codex", "skill") / "demo" / "SKILL.md"
    assert claude.exists()
    assert codex.exists()
    assert "hello body" in claude.read_text()

    st = load_state(syncer.state_dir)
    assert {"claude", "codex"} <= set(st[PAIR_ID].agentic_tools)


def test_heal_is_idempotent_nfr05(tmp_path: Path) -> None:
    syncer = make_syncer(tmp_path)
    _write_stub(syncer)
    syncer.sync_once()  # heal

    # The post-write on-disk digest is recorded, so steady-state polls do nothing.
    assert syncer.sync_once().changed == 0
    assert syncer.sync_once().changed == 0


def test_heal_only_targets_supporting_tools(tmp_path: Path) -> None:
    # A `rules` artifact heals only onto tools whose rules family supports it,
    # never onto a tool that has no rules root (e.g. antigravity).
    syncer = make_syncer(tmp_path)
    _write_stub(syncer, kind="rules", name="global")

    syncer.sync_once()

    st = load_state(syncer.state_dir)
    projected = set(st[PAIR_ID].agentic_tools)
    assert "claude" in projected  # rules-capable
    assert "antigravity" not in projected  # skills-only, no rules root
