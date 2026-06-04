"""US-04 — identity persists across rename.

AC-1: a pure filesystem `mv` updates the stored path with no rewrite.
AC-2/AC-3: a `name`-field change renames the file/folder to the new slug on every
tool (archiving the old name first), regardless of which tool originated it.
AC-5: a rename that would collide with another managed slug is rejected with no
destructive operation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agents_sync.state import load_state
from agents_sync.sync import Syncer

from ._helpers import make_syncer, skill_md


def _two_tool_syncer(tmp_path: Path) -> Syncer:
    return make_syncer(
        tmp_path,
        cursor_enabled=False,
        antigravity_enabled=False,
        opencode_enabled=False,
    )


def test_filesystem_mv_updates_state_path_without_rewrite(tmp_path: Path) -> None:
    syncer = _two_tool_syncer(tmp_path)
    agent = syncer.tool_root("claude", "agent") / "writer.md"
    agent.write_text(skill_md("writer", description="clean"))
    syncer.sync_once()

    state = load_state(syncer.state_dir)
    pair_id = next(iter(state))
    codex_path = state[pair_id].agentic_tools["codex"].path
    codex_before = codex_path.read_text()

    # Pure mv on the claude side: the embedded pair_id travels with the bytes.
    moved = syncer.tool_root("claude", "agent") / "scribe.md"
    agent.rename(moved)

    syncer.sync_once()

    state2 = load_state(syncer.state_dir)
    assert state2[pair_id].agentic_tools["claude"].path.name == "scribe.md"
    # AC-1: no rewrite on any other tool.
    assert codex_path.exists()
    assert codex_path.read_text() == codex_before
