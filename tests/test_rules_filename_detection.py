"""US-14 / FR-10: standard global-rules filename detection.

A "claudelike" tool detects (AGENTS.md, CLAUDE.md) and creates CLAUDE.md;
a "codexlike" tool detects/creates AGENTS.md.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

import json
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import AgenticToolSpec, RulesFileLayout
from agents_sync.sync import Syncer
from agents_sync.tool_specs._rules_factory import build_global_rules_io

from ._helpers import make_syncer

# ---------- unit: detection_file_names precedence ----------


def test_rules_layout_detection_prefers_candidates_over_create_name():
    layout = RulesFileLayout(
        extension=".md",
        fixed_file_name="CLAUDE.md",
        candidate_file_names=("AGENTS.md", "CLAUDE.md"),
    )
    assert layout.detection_file_names == ("AGENTS.md", "CLAUDE.md")
    assert layout.fixed_file_name == "CLAUDE.md"  # create-name


def test_rules_layout_detection_defaults_to_fixed_name():
    layout = RulesFileLayout(extension=".md", fixed_file_name="AGENTS.md")
    assert layout.detection_file_names == ("AGENTS.md",)


def test_rules_layout_candidate_must_match_extension():
    with pytest.raises(ValueError):
        RulesFileLayout(extension=".md", candidate_file_names=("AGENTS.toml",))


# ---------- integration harness ----------


def _global_rules_spec(name: str, candidates: tuple[str, ...]) -> AgenticToolSpec:
    return AgenticToolSpec(
        name=name,
        config_dir_keys={"rules": f"{name}_rules_dir"},
        io={"rules": build_global_rules_io(name, candidates)},
    )


def _syncer(tmp_path: Path) -> Syncer:
    config: dict[str, Any] = {
        "poll_interval_seconds": 1.0,
        "state_path": str(tmp_path / "state" / "state.json"),
        "claudelike_rules_dir": str(tmp_path / "claudelike"),
        "codexlike_rules_dir": str(tmp_path / "codexlike"),
    }
    # Syncer.validate requires the default-tool dir keys even when only custom
    # agentic_tools are registered; point them at unused tmp subdirs.
    for key in (
        "claude_agents_dir",
        "claude_commands_dir",
        "claude_skills_dir",
        "claude_rules_dir",
        "codex_agents_dir",
        "codex_prompts_dir",
        "codex_skills_dir",
        "codex_rules_dir",
        "antigravity_skills_dir",
        "opencode_agents_dir",
        "opencode_commands_dir",
        "opencode_skills_dir",
        "opencode_rules_dir",
    ):
        config[key] = str(tmp_path / f"unused-{key}")
    return Syncer(
        config,
        agentic_tools={
            "claudelike": _global_rules_spec("claudelike", ("AGENTS.md", "CLAUDE.md")),
            "codexlike": _global_rules_spec("codexlike", ("AGENTS.md",)),
        },
    )


def _state(syncer: Syncer) -> dict[str, Any]:
    return json.loads((syncer.state_dir / "state.json").read_text())


_POINTER = "---\nname: global\n---\n@AGENTS.md\n"
_CONTENT = "---\ndescription: Shared rules\n---\nUse small functions.\n"


# ---------- AC-2: prefer AGENTS.md when both present; leave CLAUDE.md alone ----------


def test_agents_md_wins_over_claude_md_and_pointer_untouched(tmp_path: Path):
    syncer = _syncer(tmp_path)
    claude_root = syncer.tool_root("claudelike", "rules")
    (claude_root / "AGENTS.md").write_text(_CONTENT)
    (claude_root / "CLAUDE.md").write_text(_POINTER)

    result = syncer.sync_once()

    assert result.changed == 1
    # CLAUDE.md pointer is never read or written.
    assert (claude_root / "CLAUDE.md").read_text() == _POINTER
    # The detected source is AGENTS.md.
    pair_id, entry = next(iter(_state(syncer)["customization_artifacts"].items()))
    assert Path(entry["agentic_tools"]["claudelike"]["path"]).name == "AGENTS.md"
    # Content (not the pointer) propagated to codexlike's AGENTS.md.
    target = syncer.tool_root("codexlike", "rules") / "AGENTS.md"
    assert "Use small functions." in target.read_text()
    assert f"pair_id: {pair_id}" in target.read_text()


# ---------- AC-4: re-render writes back to the detected name; idempotent ----------


def test_detected_name_round_trips_no_pointer_write(tmp_path: Path):
    syncer = _syncer(tmp_path)
    claude_root = syncer.tool_root("claudelike", "rules")
    (claude_root / "AGENTS.md").write_text(_CONTENT)
    (claude_root / "CLAUDE.md").write_text(_POINTER)

    syncer.sync_once()
    second = syncer.sync_once()

    assert second.changed == 0  # NFR-05: no churn
    assert (claude_root / "CLAUDE.md").read_text() == _POINTER
    assert (claude_root / "AGENTS.md").is_file()


# ---------- AC-3: fall back to CLAUDE.md when AGENTS.md absent ----------


def test_falls_back_to_claude_md_when_no_agents_md(tmp_path: Path):
    syncer = _syncer(tmp_path)
    claude_root = syncer.tool_root("claudelike", "rules")
    (claude_root / "CLAUDE.md").write_text(_CONTENT)

    result = syncer.sync_once()

    assert result.changed == 1
    entry = next(iter(_state(syncer)["customization_artifacts"].values()))
    assert Path(entry["agentic_tools"]["claudelike"]["path"]).name == "CLAUDE.md"
    assert (
        "Use small functions." in (syncer.tool_root("codexlike", "rules") / "AGENTS.md").read_text()
    )


# ---------- AC-5: fresh-create uses the create-name (legacy/lowest precedence) ----------


def test_fresh_claudelike_created_under_create_name(tmp_path: Path):
    syncer = _syncer(tmp_path)
    # Only codexlike has content; claudelike has no rules file at all.
    (syncer.tool_root("codexlike", "rules") / "AGENTS.md").write_text(_CONTENT)

    result = syncer.sync_once()

    assert result.changed == 1
    claude_root = syncer.tool_root("claudelike", "rules")
    assert (claude_root / "CLAUDE.md").is_file()  # create-name
    assert not (claude_root / "AGENTS.md").exists()


# ---------- AC-6: non-standard filename is ignored ----------


def test_non_standard_filename_is_ignored(tmp_path: Path):
    syncer = _syncer(tmp_path)
    claude_root = syncer.tool_root("claudelike", "rules")
    (claude_root / "INSTRUCTIONS.md").write_text(_CONTENT)

    result = syncer.sync_once()

    assert result.changed == 0
    assert (claude_root / "INSTRUCTIONS.md").read_text() == _CONTENT
    assert _state(syncer)["customization_artifacts"] == {}


# ---------- adoption planner: skip a target whose root is unconfigured ----------


def test_adoption_skips_tool_with_unconfigured_target_root(tmp_path: Path):
    """A rules artifact must not crash adoption planning when a participating
    tool's target root for that kind resolves to None. Regression: Copilot's
    VS Code instructions dir defaults to None, which previously hit
    expand_path(None) -> TypeError in adoption_planner.
    """
    # Enable Copilot's VS Code rules surface but leave its instructions dir
    # unconfigured (None) — the exact production config that crashed.
    syncer = make_syncer(
        tmp_path,
        copilot_enabled=True,
        copilot_vscode_user_profile_enabled=True,
    )
    rules_root = syncer.tool_root("claude", "rules")
    (rules_root / "AGENTS.md").write_text("---\ndescription: Shared\n---\nbody\n")

    result = syncer.sync_once()  # must not raise

    # Rules adopted and propagated to the file-based global-rules tools; Copilot
    # (no configured rules root) is silently skipped, not crashed.
    assert result.changed >= 1
    assert (syncer.tool_root("codex", "rules") / "AGENTS.md").is_file()
