"""US-07 AC-5: with fewer than two available agentic_tools the daemon performs
no destructive operations (no adoption, propagation, or removal) and polls
quietly until at least two become available.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agents_sync.canonical import list_canonical_ids
from agents_sync.sync import Syncer

from ._helpers import make_syncer, skill_md


def _dir_kinds(syncer: Syncer, tool: str) -> list[str]:
    """Kinds of ``tool`` whose root is a directory (not a shared config file)."""
    spec = syncer.agentic_tools[tool]
    return [kind for kind, key in spec.config_dir_keys.items() if "file" not in key]


def _remove_dir_roots(syncer: Syncer, tool: str) -> None:
    for kind in _dir_kinds(syncer, tool):
        root = syncer.tool_root(tool, kind)
        if root.is_dir():
            shutil.rmtree(root)


def _recreate_dir_roots(syncer: Syncer, tool: str) -> None:
    for kind in _dir_kinds(syncer, tool):
        syncer.tool_root(tool, kind).mkdir(parents=True, exist_ok=True)


def _one_available_syncer(tmp_path: Path) -> Syncer:
    """A syncer with exactly one available tool: claude (codex's roots removed,
    every optional tool disabled)."""
    syncer = make_syncer(
        tmp_path,
        cursor_enabled=False,
        antigravity_enabled=False,
        opencode_enabled=False,
    )
    _remove_dir_roots(syncer, "codex")
    return syncer


def test_one_available_tool_adopts_nothing(tmp_path: Path) -> None:
    syncer = _one_available_syncer(tmp_path)
    skill_dir = syncer.tool_root("claude", "skill") / "writer"
    skill_dir.mkdir(parents=True)
    md = skill_dir / "SKILL.md"
    md.write_text(skill_md("writer", description="clean"))

    result = syncer.sync_once()

    snapshot = syncer.tool_status.snapshot()
    available = [t for t, s in snapshot.items() if s == "available"]
    assert available == ["claude"], snapshot
    # No destructive op: nothing adopted, the user's file is not rewritten.
    assert list(list_canonical_ids(syncer.state_dir)) == []
    assert "pair_id" not in md.read_text()
    assert result.changed == 0


def test_adoption_resumes_once_a_second_tool_is_available(tmp_path: Path) -> None:
    syncer = _one_available_syncer(tmp_path)
    skill_dir = syncer.tool_root("claude", "skill") / "writer"
    skill_dir.mkdir(parents=True)
    md = skill_dir / "SKILL.md"
    md.write_text(skill_md("writer", description="clean"))

    syncer.sync_once()
    assert list(list_canonical_ids(syncer.state_dir)) == []  # still one tool

    # A second tool becomes available — adoption now proceeds.
    _recreate_dir_roots(syncer, "codex")
    syncer.sync_once()

    assert len(list(list_canonical_ids(syncer.state_dir))) == 1
    assert "pair_id" in md.read_text()
