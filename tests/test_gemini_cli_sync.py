"""Integration coverage for the Gemini CLI adapter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents_sync.gemini_cli_io import (
    extract_pair_id_from_gemini_agent_md,
    extract_pair_id_from_gemini_command_toml,
)
from agents_sync.slash_command_io import parse_slash_command_markdown
from agents_sync.sync import Syncer


def _config(tmp_path: Path, *, antigravity_enabled: bool = False) -> dict[str, Any]:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for sub in (
        "claude-agents",
        "claude-commands",
        "claude-skills",
        "claude-root",
        "codex-agents",
        "codex-prompts",
        "codex-skills",
        "codex-root",
        "antigravity-skills",
        "gemini-agents",
        "gemini-commands",
        "gemini-skills",
        "gemini-root",
        "opencode-agents",
        "opencode-commands",
        "opencode-skills",
        "opencode-root",
    ):
        (tmp_path / sub).mkdir()
    return {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "claude-agents"),
        "claude_commands_dir": str(tmp_path / "claude-commands"),
        "claude_skills_dir": str(tmp_path / "claude-skills"),
        "claude_rules_dir": str(tmp_path / "claude-root"),
        "codex_agents_dir": str(tmp_path / "codex-agents"),
        "codex_prompts_dir": str(tmp_path / "codex-prompts"),
        "codex_skills_dir": str(tmp_path / "codex-skills"),
        "codex_rules_dir": str(tmp_path / "codex-root"),
        "antigravity_skills_dir": str(tmp_path / "antigravity-skills"),
        "antigravity_enabled": antigravity_enabled,
        "gemini_cli_agents_dir": str(tmp_path / "gemini-agents"),
        "gemini_cli_commands_dir": str(tmp_path / "gemini-commands"),
        "gemini_cli_skills_dir": str(tmp_path / "gemini-skills"),
        "gemini_cli_rules_dir": str(tmp_path / "gemini-root"),
        "gemini_cli_enabled": True,
        "opencode_agents_dir": str(tmp_path / "opencode-agents"),
        "opencode_commands_dir": str(tmp_path / "opencode-commands"),
        "opencode_skills_dir": str(tmp_path / "opencode-skills"),
        "opencode_rules_dir": str(tmp_path / "opencode-root"),
        "opencode_enabled": False,
    }


def _syncer(tmp_path: Path, *, antigravity_enabled: bool = False) -> Syncer:
    return Syncer(_config(tmp_path, antigravity_enabled=antigravity_enabled))


def test_gemini_agent_adopts_and_projects_to_agent_capable_tools(tmp_path: Path):
    syncer = _syncer(tmp_path)
    source = syncer.tool_root("gemini_cli", "agent") / "reviewer.md"
    source.write_text(
        "---\n"
        "name: reviewer\n"
        "description: Reviews code\n"
        "kind: local\n"
        "tools:\n"
        "  - read_file\n"
        "---\n"
        "Review carefully.\n",
        encoding="utf-8",
    )

    assert syncer.sync_once() == 1

    pair_id = extract_pair_id_from_gemini_agent_md(source.read_text(encoding="utf-8"))
    assert pair_id is not None
    assert (syncer.tool_root("claude", "agent") / "reviewer.md").is_file()
    assert (syncer.tool_root("codex", "agent") / "reviewer.toml").is_file()
    state = json.loads((syncer.state_dir / "state.json").read_text())
    assert set(state["customization_artifacts"][pair_id]["agentic_tools"]) == {
        "claude",
        "codex",
        "gemini_cli",
    }
    assert list(syncer.tool_root("antigravity", "skill").iterdir()) == []


def test_agent_from_another_tool_projects_to_gemini_subagent(tmp_path: Path):
    syncer = _syncer(tmp_path)
    source = syncer.tool_root("claude", "agent") / "debugger.md"
    source.write_text(
        "---\n"
        "name: debugger\n"
        "description: Debugs failures\n"
        "tools: Read, Grep\n"
        "---\n"
        "Inspect the failing path.\n",
        encoding="utf-8",
    )

    assert syncer.sync_once() == 1

    gemini_agent = syncer.tool_root("gemini_cli", "agent") / "debugger.md"
    text = gemini_agent.read_text(encoding="utf-8")
    assert "kind: local" in text
    assert "tools:" not in text
    assert "Read" not in text
    assert "Grep" not in text
    assert "Inspect the failing path." in text


def test_gemini_skill_syncs_auxiliary_files_without_sharing_antigravity_root(
    tmp_path: Path,
):
    syncer = _syncer(tmp_path, antigravity_enabled=True)
    source_dir = syncer.tool_root("gemini_cli", "skill") / "release-checklist"
    source_dir.mkdir()
    (source_dir / "SKILL.md").write_text(
        "---\n"
        "name: release-checklist\n"
        "description: Prepare release notes\n"
        "license: MIT\n"
        "---\n"
        "Check versions.\n",
        encoding="utf-8",
    )
    (source_dir / "notes.md").write_text("extra context\n", encoding="utf-8")

    assert syncer.sync_once() == 1

    claude_dir = syncer.tool_root("claude", "skill") / "release-checklist"
    antigravity_dir = (
        syncer.tool_root("antigravity", "skill") / "release-checklist"
    )
    assert (claude_dir / "SKILL.md").is_file()
    assert (claude_dir / "notes.md").read_text(encoding="utf-8") == "extra context\n"
    assert (antigravity_dir / "SKILL.md").is_file()
    assert syncer.tool_root("gemini_cli", "skill") != syncer.tool_root(
        "antigravity",
        "skill",
    )


def test_gemini_rules_file_projects_to_global_rules_files(tmp_path: Path):
    syncer = _syncer(tmp_path)
    source = syncer.tool_root("gemini_cli", "rules") / "GEMINI.md"
    source.write_text(
        "---\n"
        "description: Gemini context\n"
        "---\n"
        "Prefer small functions.\n",
        encoding="utf-8",
    )

    assert syncer.sync_once() == 1

    claude_rules = syncer.tool_root("claude", "rules") / "CLAUDE.md"
    codex_rules = syncer.tool_root("codex", "rules") / "AGENTS.md"
    assert "Prefer small functions." in claude_rules.read_text(encoding="utf-8")
    assert "Prefer small functions." in codex_rules.read_text(encoding="utf-8")
    assert "name: global" in source.read_text(encoding="utf-8")


def test_gemini_command_toml_syncs_to_markdown_slash_commands(tmp_path: Path):
    syncer = _syncer(tmp_path)
    body = "Commit {{args}}.\n!{git status}\n"
    source = syncer.tool_root("gemini_cli", "slash_command") / "git" / "commit.toml"
    source.parent.mkdir()
    source.write_text(
        "\n".join([
            'description = "Commit helper"',
            '"argument-hint" = "[message]"',
            f"prompt = {json.dumps(body)}",
            "",
        ]),
        encoding="utf-8",
    )

    assert syncer.sync_once() == 1

    pair_id = extract_pair_id_from_gemini_command_toml(
        source.read_text(encoding="utf-8")
    )
    assert pair_id is not None
    claude_command = syncer.tool_root("claude", "slash_command") / "git" / "commit.md"
    assert claude_command.is_file()

    canonical = parse_slash_command_markdown(
        claude_command.read_text(encoding="utf-8"),
        None,
        agentic_tool_name="claude",
        artifact_path=claude_command,
        artifact_root=syncer.tool_root("claude", "slash_command"),
    )
    assert canonical["name"] == "git:commit"
    assert canonical["description"] == "Commit helper"
    assert canonical["argument_hint"] == "[message]"
    assert canonical["body"] == body
