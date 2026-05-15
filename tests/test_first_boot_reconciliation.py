"""Tests for v0.4 plan §5.5: first-boot reconciliation of multi-tool
new customization artifacts (same kind, same slug, no pair_id on any tool).

Exercised with skills (the customization_type all three tools participate
in). Reconciliation is keyed on (customization_type, target_slug(name)),
so the algorithm itself is tool-agnostic.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from agents_sync.sync import Syncer


def _skill_md(name: str, description: str = "x", body: str = "body") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}\n"


def _write_skill(root: Path, name: str, description: str = "x") -> Path:
    skill_dir = root / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_skill_md(name, description=description))
    return skill_dir


def _set_skill_mtime(skill_dir: Path, value: float) -> None:
    """Set mtime on the SKILL.md (discovery reads st_mtime from the artifact path)."""
    os.utime(skill_dir / "SKILL.md", (value, value))
    os.utime(skill_dir, (value, value))


def _archive_files_for(syncer: Syncer, pair_id: str, tool_name: str) -> list[Path]:
    archive_dir = syncer.state_dir / "archive" / pair_id / tool_name
    if not archive_dir.exists():
        return []
    return list(archive_dir.iterdir())


def _list_state(syncer: Syncer) -> dict:
    state_file = syncer.state_dir / "state.json"
    if not state_file.exists():
        return {}
    return json.loads(state_file.read_text())


def test_two_tool_duplicate_with_drifted_content_merges_to_one(syncer: Syncer):
    """Same slug, both tools, drifted content, codex newer ⇒ codex wins.

    End state: one managed customization_artifact, both tools converge to codex
    content, claude bytes archived. State has one pair_id with both tools
    (plus antigravity from the registry projection).
    """
    claude_dir = _write_skill(syncer.tool_root("claude", "skill"), "formatter", "claude version")
    codex_dir = _write_skill(syncer.tool_root("codex", "skill"), "formatter", "codex version")

    _set_skill_mtime(claude_dir, 1000.0)
    _set_skill_mtime(codex_dir, 2000.0)  # codex wins on mtime

    syncer.sync_once()

    state = _list_state(syncer)
    assert state["schema_version"] == 2
    customization_artifacts = state["customization_artifacts"]
    assert len(customization_artifacts) == 1
    entry = next(iter(customization_artifacts.values()))
    assert entry["customization_type"] == "skill"
    assert "claude" in entry["agentic_tools"]
    assert "codex" in entry["agentic_tools"]

    pair_id = next(iter(customization_artifacts.keys()))
    final_claude_md = Path(entry["agentic_tools"]["claude"]["path"]) / "SKILL.md"
    final_codex_md = Path(entry["agentic_tools"]["codex"]["path"]) / "SKILL.md"
    assert "codex version" in final_claude_md.read_text()
    assert "codex version" in final_codex_md.read_text()

    claude_archive = _archive_files_for(syncer, pair_id, "claude")
    assert claude_archive, "claude bytes should be archived"


def test_mtime_tie_uses_alphabetical_tool_tiebreaker(syncer: Syncer):
    """Equal mtime ⇒ alphabetical first (claude < codex), so claude wins."""
    claude_dir = _write_skill(syncer.tool_root("claude", "skill"), "tied", "claude content")
    codex_dir = _write_skill(syncer.tool_root("codex", "skill"), "tied", "codex content")

    _set_skill_mtime(claude_dir, 5000.0)
    _set_skill_mtime(codex_dir, 5000.0)

    syncer.sync_once()

    state = _list_state(syncer)
    assert len(state["customization_artifacts"]) == 1
    entry = next(iter(state["customization_artifacts"].values()))
    final_codex_md = Path(entry["agentic_tools"]["codex"]["path"]) / "SKILL.md"
    assert "claude content" in final_codex_md.read_text()


def test_identical_content_across_tools_merges_cleanly(syncer: Syncer):
    """Same name, same content on both tools: one merged artifact."""
    _write_skill(syncer.tool_root("claude", "skill"), "twin", "same")
    _write_skill(syncer.tool_root("codex", "skill"), "twin", "same")

    syncer.sync_once()

    state = _list_state(syncer)
    assert len(state["customization_artifacts"]) == 1


def test_singleton_new_artifact_is_unaffected_by_reconcile(syncer: Syncer):
    """An artifact present on only one tool still adopts normally."""
    _write_skill(syncer.tool_root("claude", "skill"), "solo")

    changed = syncer.sync_once()
    assert changed == 1

    state = _list_state(syncer)
    assert len(state["customization_artifacts"]) == 1
    entry = next(iter(state["customization_artifacts"].values()))
    # Adoption projects to every other available tool (codex + antigravity).
    assert "codex" in entry["agentic_tools"]


def test_intra_tool_slug_collision_still_blocks(syncer: Syncer):
    """Two distinct claude skills that slugify to the same target are NOT merged.

    Reconcile only collapses entries that live on different tools; same-tool
    slug collisions remain the job of _block_target_collisions.
    """
    first = syncer.tool_root("claude", "skill") / "first"
    second = syncer.tool_root("claude", "skill") / "second"
    first.mkdir()
    second.mkdir()
    (first / "SKILL.md").write_text(_skill_md("same"))
    (second / "SKILL.md").write_text(_skill_md("same"))

    changed = syncer.sync_once()
    assert changed == 0

    state = _list_state(syncer)
    assert state == {} or state.get("customization_artifacts", {}) == {}


def test_mixed_managed_and_new_at_same_slug_is_blocked(tmp_path: Path):
    """When one side carries a pair_id and the other is a no-id duplicate at
    the same bare slug, both targets collide on the opposite side. Current
    behavior: both pair_ids are blocked and state stays empty.

    The v0.4 plan §5.5 prescribes a "managed wins, new bytes archived" merge
    for this case, but my Phase 1.6 commit deferred that implementation. This
    test documents the present block-and-log behavior so we notice when the
    deferred §5.5 mixed handler lands.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for sub in ("ca", "cs", "xa", "xs", "oa", "os"):
        (tmp_path / sub).mkdir()
    config = {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "ca"),
        "claude_skills_dir": str(tmp_path / "cs"),
        "codex_agents_dir": str(tmp_path / "xa"),
        "codex_skills_dir": str(tmp_path / "xs"),
        "antigravity_skills_dir": str(tmp_path / "as"),
        "antigravity_enabled": False,
        "opencode_agents_dir": str(tmp_path / "oa"),
        "opencode_skills_dir": str(tmp_path / "os"),
        "opencode_enabled": False,
    }
    syncer = Syncer(config)

    claude_dir = syncer.tool_root("claude", "skill") / "managed"
    claude_dir.mkdir()
    (claude_dir / "SKILL.md").write_text(
        "---\n"
        "pair_id: 00000000-0000-4000-8000-000000000000\n"
        "name: managed\n"
        "description: from-claude\n"
        "---\n"
        "body\n"
    )
    _write_skill(syncer.tool_root("codex", "skill"), "managed", "from-codex")

    syncer.sync_once()

    state = _list_state(syncer)
    assert state.get("customization_artifacts", {}) == {}
