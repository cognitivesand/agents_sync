"""Integration coverage for the real Cursor adapter."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

from agents_sync.cursor_io import (
    extract_pair_id_from_cursor_agent_md,
    extract_pair_id_from_cursor_command_md,
    extract_pair_id_from_cursor_rule_mdc,
    extract_pair_id_from_cursor_skill_md,
)
from agents_sync.sync import Syncer


def test_cursor_agent_adopts_to_other_agent_tools(syncer: Syncer):
    source = syncer.tool_root("cursor", "agent") / "reviewer.md"
    source.write_text(
        "---\n"
        "description: Reviews diffs\n"
        "model: claude-4-sonnet\n"
        "---\n"
        "Review the current diff.\n",
        encoding="utf-8",
    )

    syncer.sync_once()

    injected = source.read_text(encoding="utf-8")
    assert extract_pair_id_from_cursor_agent_md(injected) is not None
    assert "tools: []" not in injected
    assert (syncer.tool_root("claude", "agent") / "reviewer.md").exists()
    assert (syncer.tool_root("codex", "agent") / "reviewer.toml").exists()
    assert (syncer.tool_root("opencode", "agent") / "reviewer.md").exists()


def test_cursor_skill_adopts_with_auxiliary_files(syncer: Syncer):
    source = syncer.tool_root("cursor", "skill") / "release-checklist"
    (source / "scripts").mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\n"
        "name: release-checklist\n"
        "description: Release helper\n"
        "---\n"
        "Run the release checklist.\n",
        encoding="utf-8",
    )
    (source / "scripts" / "check.md").write_text("auxiliary notes\n", encoding="utf-8")

    syncer.sync_once()

    assert extract_pair_id_from_cursor_skill_md(
        (source / "SKILL.md").read_text(encoding="utf-8")
    )
    for tool in ("claude", "codex", "antigravity", "opencode"):
        target = syncer.tool_root(tool, "skill") / "release-checklist"
        assert (target / "SKILL.md").exists()
        assert (target / "scripts" / "check.md").read_text(encoding="utf-8") == (
            "auxiliary notes\n"
        )


def test_cursor_rule_adopts_to_global_rules_tools(syncer: Syncer):
    source = syncer.tool_root("cursor", "rules") / "typescript.mdc"
    source.write_text(
        "---\n"
        "description: TypeScript conventions\n"
        "globs:\n"
        '  - "**/*.ts"\n'
        "alwaysApply: true\n"
        "---\n"
        "Prefer strict types.\n",
        encoding="utf-8",
    )

    syncer.sync_once()

    assert extract_pair_id_from_cursor_rule_mdc(source.read_text(encoding="utf-8"))
    for tool, filename in (
        ("claude", "CLAUDE.md"),
        ("codex", "AGENTS.md"),
        ("opencode", "AGENTS.md"),
    ):
        target = syncer.tool_root(tool, "rules") / filename
        assert "Prefer strict types." in target.read_text(encoding="utf-8")


def test_cursor_command_adopts_without_markdown_yaml_metadata_block_on_cursor(syncer: Syncer):
    source = syncer.tool_root("cursor", "slash_command") / "git" / "commit.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "Write a commit message for $ARGUMENTS.\n",
        encoding="utf-8",
    )

    syncer.sync_once()

    cursor_text = source.read_text(encoding="utf-8")
    assert cursor_text.startswith("<!-- agents_sync:pair_id=")
    assert not cursor_text.startswith("---")
    assert extract_pair_id_from_cursor_command_md(cursor_text) is not None
    assert (syncer.tool_root("codex", "slash_command") / "git" / "commit.md").exists()
    assert (
        syncer.tool_root("opencode", "slash_command") / "git" / "commit.md"
    ).exists()


def test_cursor_mcp_server_adopts_to_other_mcp_tools(syncer: Syncer):
    cursor_file = syncer.tool_root("cursor", "mcp_server")
    cursor_file.write_text(
        json.dumps({
            "mcpServers": {
                "docs": {
                    "url": "https://docs.example.com/mcp",
                },
            },
        }),
        encoding="utf-8",
    )

    syncer.sync_once()

    cursor_config = json.loads(cursor_file.read_text(encoding="utf-8"))
    assert cursor_config["mcpServers"]["docs"]["pair_id"]
    assert cursor_config["mcpServers"]["docs"]["type"] == "streamable-http"

    claude = json.loads(
        syncer.tool_root("claude", "mcp_server").read_text(encoding="utf-8")
    )
    codex = tomllib.loads(
        syncer.tool_root("codex", "mcp_server").read_text(encoding="utf-8")
    )
    opencode = json.loads(
        syncer.tool_root("opencode", "mcp_server").read_text(encoding="utf-8")
    )
    assert claude["mcpServers"]["docs"]["url"] == "https://docs.example.com/mcp"
    assert codex["mcp_servers"]["docs"]["url"] == "https://docs.example.com/mcp"
    assert opencode["mcp"]["docs"]["url"] == "https://docs.example.com/mcp"


def test_projection_into_cursor_preserves_existing_mcp_siblings(syncer: Syncer):
    cursor_file = syncer.tool_root("cursor", "mcp_server")
    cursor_file.write_text(
        json.dumps({
            "version": 1,
            "mcpServers": {
                "local-only": {
                    "pair_id": "22222222-3333-4444-8555-666666666666",
                    "type": "stdio",
                    "command": "local-server",
                },
            },
        }),
        encoding="utf-8",
    )
    claude_file = syncer.tool_root("claude", "mcp_server")
    claude_file.write_text(
        json.dumps({
            "mcpServers": {
                "docs": {
                    "type": "http",
                    "url": "https://docs.example.com/mcp",
                },
            },
        }),
        encoding="utf-8",
    )

    syncer.sync_once()

    cursor_config = json.loads(cursor_file.read_text(encoding="utf-8"))
    assert cursor_config["version"] == 1
    assert set(cursor_config["mcpServers"]) == {"local-only", "docs"}
    assert cursor_config["mcpServers"]["local-only"]["command"] == "local-server"
    assert cursor_config["mcpServers"]["docs"]["url"] == "https://docs.example.com/mcp"
