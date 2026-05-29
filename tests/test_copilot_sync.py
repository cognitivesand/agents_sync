from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

from agents_sync.claude_io import extract_pair_id_from_md
from agents_sync.copilot_io import (
    extract_pair_id_from_copilot_agent_md,
    parse_copilot_skill_md,
)
from agents_sync.sync import Syncer


def _config(tmp_path: Path, *, with_vscode: bool = True) -> dict[str, Any]:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "claude-agents"),
        "claude_commands_dir": str(tmp_path / "claude-commands"),
        "claude_skills_dir": str(tmp_path / "claude-skills"),
        "claude_rules_dir": str(tmp_path / "claude-rules"),
        "claude_mcp_servers_file": str(tmp_path / "claude-mcp.json"),
        "codex_agents_dir": str(tmp_path / "codex-agents"),
        "codex_prompts_dir": str(tmp_path / "codex-prompts"),
        "codex_skills_dir": str(tmp_path / "codex-skills"),
        "codex_rules_dir": str(tmp_path / "codex-rules"),
        "codex_config_file": str(tmp_path / "codex-config.toml"),
        "antigravity_skills_dir": str(tmp_path / "antigravity-skills"),
        "antigravity_enabled": True,
        "opencode_agents_dir": str(tmp_path / "opencode-agents"),
        "opencode_commands_dir": str(tmp_path / "opencode-commands"),
        "opencode_skills_dir": str(tmp_path / "opencode-skills"),
        "opencode_rules_dir": str(tmp_path / "opencode-rules"),
        "opencode_config_file": str(tmp_path / "opencode.json"),
        "opencode_enabled": True,
        "copilot_enabled": True,
        "copilot_cli_enabled": True,
        "copilot_vscode_user_profile_enabled": True,
        "copilot_cli_agents_dir": str(tmp_path / "copilot-agents"),
        "copilot_cli_skills_dir": str(tmp_path / "copilot-skills"),
        "copilot_cli_mcp_config_file": str(tmp_path / "copilot-mcp.json"),
        "copilot_vscode_user_agents_dir": None,
        "copilot_vscode_user_instructions_dir": (
            str(tmp_path / "copilot-instructions") if with_vscode else None
        ),
        "copilot_vscode_user_prompts_dir": (
            str(tmp_path / "copilot-prompts") if with_vscode else None
        ),
        "copilot_vscode_user_mcp_file": None,
    }
    return config


def test_copilot_cli_agent_adopts_and_projects_to_other_agent_tools(tmp_path: Path):
    syncer = Syncer(_config(tmp_path))
    source = syncer.tool_root("copilot", "agent") / "reviewer.agent.md"
    source.write_text(
        textwrap.dedent(
            """\
            ---
            name: reviewer
            description: Reviews patches
            ---
            Review the patch.
            """
        ),
        encoding="utf-8",
    )

    assert syncer.sync_once() == 1

    pair_id = extract_pair_id_from_copilot_agent_md(source.read_text(encoding="utf-8"))
    assert pair_id is not None
    claude_target = syncer.tool_root("claude", "agent") / "reviewer.md"
    codex_target = syncer.tool_root("codex", "agent") / "reviewer.toml"
    opencode_target = syncer.tool_root("opencode", "agent") / "reviewer.md"
    assert extract_pair_id_from_md(claude_target.read_text(encoding="utf-8")) == pair_id
    assert codex_target.exists()
    assert opencode_target.exists()


def test_agent_from_other_tool_projects_to_copilot_agent_md(tmp_path: Path):
    syncer = Syncer(_config(tmp_path))
    source = syncer.tool_root("claude", "agent") / "planner.md"
    source.write_text(
        textwrap.dedent(
            """\
            ---
            name: planner
            description: Makes plans
            ---
            Plan the work.
            """
        ),
        encoding="utf-8",
    )

    assert syncer.sync_once() == 1

    pair_id = extract_pair_id_from_md(source.read_text(encoding="utf-8"))
    target = syncer.tool_root("copilot", "agent") / "planner.agent.md"
    assert target.exists()
    assert extract_pair_id_from_copilot_agent_md(target.read_text(encoding="utf-8")) == pair_id


def test_skill_from_other_tool_keeps_canonical_name_on_copilot_slug_path(tmp_path: Path):
    syncer = Syncer(_config(tmp_path, with_vscode=False))
    source = syncer.tool_root("claude", "skill") / "source-skill"
    source.mkdir()
    (source / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: Release Checklist!
            description: Prepare releases
            ---
            Check every release gate.
            """
        ),
        encoding="utf-8",
    )

    assert syncer.sync_once() == 1

    target = syncer.tool_root("copilot", "skill") / "release-checklist"
    target_text = (target / "SKILL.md").read_text(encoding="utf-8")
    parsed = parse_copilot_skill_md(target_text, None, artifact_path=target)

    assert target.exists()
    assert not (syncer.tool_root("copilot", "skill") / "Release Checklist!").exists()
    assert "name: release-checklist" in target_text
    assert parsed["name"] == "Release Checklist!"


def test_copilot_prompt_syncs_as_slash_command_with_namespace(tmp_path: Path):
    syncer = Syncer(_config(tmp_path))
    source = syncer.tool_root("copilot", "slash_command") / "git" / "commit.prompt.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """\
            ---
            description: Draft commit message
            tools:
              - terminal
            ---
            Summarize the staged diff.
            """
        ),
        encoding="utf-8",
    )

    assert syncer.sync_once() == 1

    target = syncer.tool_root("claude", "slash_command") / "git" / "commit.md"
    assert target.exists()
    target_text = target.read_text(encoding="utf-8")
    assert "Summarize the staged diff." in target_text
    assert "allowed-tools:" in target_text
    assert "terminal" in target_text


def test_copilot_cli_mcp_servers_project_to_other_mcp_adapters(tmp_path: Path):
    config = _config(tmp_path)
    source = Path(config["copilot_cli_mcp_config_file"])
    source.write_text(
        json.dumps(
            {
                "servers": {
                    "docs": {
                        "type": "http",
                        "url": "https://developers.openai.com/mcp",
                    },
                    "everything": {
                        "type": "stdio",
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-everything"],
                    },
                },
                "inputs": [{"id": "token"}],
            }
        ),
        encoding="utf-8",
    )

    assert Syncer(config).sync_once().changed == 2

    copilot = json.loads(source.read_text(encoding="utf-8"))
    claude = json.loads((tmp_path / "claude-mcp.json").read_text(encoding="utf-8"))
    assert copilot["inputs"] == [{"id": "token"}]
    assert claude["mcpServers"]["docs"]["url"] == "https://developers.openai.com/mcp"
    assert claude["mcpServers"]["everything"]["command"] == "npx"
    assert claude["mcpServers"]["everything"]["args"] == [
        "-y",
        "@modelcontextprotocol/server-everything",
    ]


def test_unset_vscode_profile_paths_do_not_disable_copilot_cli_half(tmp_path: Path):
    syncer = Syncer(_config(tmp_path, with_vscode=False))
    source = syncer.tool_root("copilot", "agent") / "reviewer.agent.md"
    source.write_text("---\nname: reviewer\n---\nReview.\n", encoding="utf-8")

    syncer.sync_once()

    assert syncer.tool_status.snapshot()["copilot"] == "available"
    assert syncer.tool_status.is_kind_available("copilot", "agent") is True
    assert syncer.tool_status.is_kind_available("copilot", "skill") is True
    assert syncer.tool_status.is_kind_available("copilot", "slash_command") is False
    assert syncer.tool_status.is_kind_available("copilot", "rules") is False


def test_disabling_both_copilot_halves_marks_tool_disabled(tmp_path: Path):
    config = _config(tmp_path)
    config["copilot_cli_enabled"] = False
    config["copilot_vscode_user_profile_enabled"] = False
    syncer = Syncer(config)

    syncer.sync_once()

    assert syncer.tool_status.snapshot()["copilot"] == "disabled"
    assert syncer.tool_status.is_kind_available("copilot", "agent") is False
