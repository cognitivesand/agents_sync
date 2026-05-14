"""Tests for v0.4 plan §5.5: first-boot reconciliation of multi-tool
new customization artifacts (same kind, same slug, no pair_id on any tool).

Verified at N=2 (claude + codex). The same algorithm will exercise N=3 once
Antigravity is wired into the registry in v0.4 Phase 4.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from agents_sync.sync import Syncer


def _claude_md(name: str, description: str = "x", body: str = "body") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}\n"


def _codex_toml(name: str, description: str = "x", body: str = "body") -> str:
    return (
        f'name = "{name}"\n'
        f'description = "{description}"\n'
        f'developer_instructions = "{body}"\n'
    )


def _set_mtime(path: Path, value: float) -> None:
    os.utime(path, (value, value))


def _archive_files_for(syncer: Syncer, pair_id: str, tool_name: str) -> list[Path]:
    """List archive files for one (pair_id, tool) pair, if the dir exists."""
    archive_dir = syncer.state_dir / "archive" / pair_id / tool_name
    if not archive_dir.exists():
        return []
    return list(archive_dir.iterdir())


def _list_state(syncer: Syncer) -> dict:
    import json

    state_file = syncer.state_dir / "state.json"
    if not state_file.exists():
        return {}
    return json.loads(state_file.read_text())


def test_two_tool_duplicate_with_drifted_content_merges_to_one(syncer: Syncer):
    """Same slug, both tools, drifted content, codex newer ⇒ codex wins.

    End state: one managed customization_artifact, both tools converge to codex
    content, claude bytes archived. State has one pair_id with both tools.
    """
    claude_md = Path(syncer.claude_agents_dir) / "formatter.md"
    claude_md.write_text(_claude_md("formatter", description="claude version"))
    codex_toml = Path(syncer.codex_agents_dir) / "formatter.toml"
    codex_toml.write_text(_codex_toml("formatter", description="codex version"))

    _set_mtime(claude_md, 1000.0)
    _set_mtime(codex_toml, 2000.0)  # codex wins on mtime

    changed = syncer.sync_once()
    assert changed == 1

    # Exactly one customization_artifact in state, both tools populated.
    state = _list_state(syncer)
    assert state["schema_version"] == 2
    customization_artifacts = state["customization_artifacts"]
    assert len(customization_artifacts) == 1
    entry = next(iter(customization_artifacts.values()))
    assert entry["customization_type"] == "agent"
    assert set(entry["agentic_tools"].keys()) == {"claude", "codex"}

    # Both tools now reflect codex's content.
    pair_id = next(iter(customization_artifacts.keys()))
    final_claude_path = Path(entry["agentic_tools"]["claude"]["path"])
    final_codex_path = Path(entry["agentic_tools"]["codex"]["path"])
    assert "codex version" in final_claude_path.read_text()
    assert "codex version" in final_codex_path.read_text()

    # Claude's pre-merge bytes archived under the merged pair_id.
    claude_archive = _archive_files_for(syncer, pair_id, "claude")
    assert claude_archive, "claude bytes should be archived"
    assert any("claude version" in f.read_text() for f in claude_archive)


def test_mtime_tie_uses_alphabetical_tool_tiebreaker(syncer: Syncer):
    """Equal mtime ⇒ alphabetical first (claude < codex), so claude wins."""
    claude_md = Path(syncer.claude_agents_dir) / "tied.md"
    claude_md.write_text(_claude_md("tied", description="claude content"))
    codex_toml = Path(syncer.codex_agents_dir) / "tied.toml"
    codex_toml.write_text(_codex_toml("tied", description="codex content"))

    _set_mtime(claude_md, 5000.0)
    _set_mtime(codex_toml, 5000.0)

    syncer.sync_once()

    state = _list_state(syncer)
    assert len(state["customization_artifacts"]) == 1
    entry = next(iter(state["customization_artifacts"].values()))
    final_codex_path = Path(entry["agentic_tools"]["codex"]["path"])
    # codex was overwritten by claude (the alphabetical winner on tie).
    assert "claude content" in final_codex_path.read_text()


def test_identical_content_across_tools_merges_cleanly(syncer: Syncer):
    """Same name, same content on both tools: one merged artifact, archives recorded."""
    claude_md = Path(syncer.claude_agents_dir) / "twin.md"
    claude_md.write_text(_claude_md("twin", description="same"))
    codex_toml = Path(syncer.codex_agents_dir) / "twin.toml"
    codex_toml.write_text(_codex_toml("twin", description="same"))

    syncer.sync_once()

    state = _list_state(syncer)
    assert len(state["customization_artifacts"]) == 1


def test_singleton_new_artifact_is_unaffected_by_reconcile(syncer: Syncer):
    """An artifact present on only one tool still adopts normally."""
    claude_md = Path(syncer.claude_agents_dir) / "solo.md"
    claude_md.write_text(_claude_md("solo"))

    changed = syncer.sync_once()
    assert changed == 1

    state = _list_state(syncer)
    assert len(state["customization_artifacts"]) == 1
    entry = next(iter(state["customization_artifacts"].values()))
    # Adoption rendered the codex counterpart.
    assert set(entry["agentic_tools"].keys()) == {"claude", "codex"}


def test_intra_tool_slug_collision_still_blocks(syncer: Syncer):
    """Two distinct claude files that slugify to the same target are NOT merged.

    Reconcile only collapses entries that live on different tools; same-tool
    slug collisions remain the job of _block_target_collisions.
    """
    first = Path(syncer.claude_agents_dir) / "first.md"
    second = Path(syncer.claude_agents_dir) / "second.md"
    first.write_text(_claude_md("same"))
    second.write_text(_claude_md("same"))

    changed = syncer.sync_once()
    assert changed == 0  # collision-blocked, nothing adopted

    state = _list_state(syncer)
    assert state == {} or state.get("customization_artifacts", {}) == {}


def test_reconcile_skipped_when_one_side_already_has_pair_id(syncer: Syncer):
    """If one tool's artifact carries a pair_id (e.g. partial v0.3 state), the
    entries are not in the all-new group and reconcile leaves them alone.

    The pair_id-bearing entry adopts under that id; the other side adopts as
    a separate artifact and falls through to collision blocking.
    """
    claude_md = Path(syncer.claude_agents_dir) / "managed.md"
    claude_md.write_text(
        "---\n"
        "pair_id: 00000000-0000-4000-8000-000000000000\n"
        "name: managed\n"
        "description: from-claude\n"
        "---\n"
        "body\n"
    )
    codex_toml = Path(syncer.codex_agents_dir) / "managed.toml"
    codex_toml.write_text(_codex_toml("managed", description="from-codex"))

    syncer.sync_once()

    state = _list_state(syncer)
    # The claude-managed pair adopts; the codex-only "new" pair collides on
    # the codex side at the same slug and is collision-blocked.
    pair_ids = list(state.get("customization_artifacts", {}).keys())
    assert "00000000-0000-4000-8000-000000000000" in pair_ids
