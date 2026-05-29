"""AgenticToolSpec factory for Claude Code."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    DirectorySkillLayout,
)
from agents_sync.tool_specs._mcp_server_factory import build_mcp_server_io
from agents_sync.tool_specs._rules_factory import build_global_rules_io


def build_claude_spec(config: Mapping[str, Any] | None = None) -> AgenticToolSpec:
    from agents_sync.mcp_server_io import McpServerDialect
    from agents_sync.claude_io import (
        extract_pair_id_from_md,
        parse_claude_md,
        render_claude_md,
    )
    from agents_sync.slash_command_io import (
        parse_slash_command_markdown,
        render_slash_command_markdown,
        slash_command_slug,
    )

    def parse_agent(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_claude_md(text, prior_canonical=prior_canonical, kind="agent")

    def parse_skill(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_claude_md(text, prior_canonical=prior_canonical, kind="skill")

    def render(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_claude_md(canonical, prior_text=prior_text)

    def parse_slash_command(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_slash_command_markdown(
            text,
            prior_canonical,
            agentic_tool_name="claude",
            artifact_path=artifact_path,
            artifact_root=artifact_root,
        )

    def render_slash_command(
        canonical: dict[str, Any],
        prior_text: str | None,
    ) -> str:
        return render_slash_command_markdown(
            canonical,
            prior_text,
            agentic_tool_name="claude",
        )

    return AgenticToolSpec(
        name="claude",
        config_dir_keys={
            "agent": "claude_agents_dir",
            "skill": "claude_skills_dir",
            "slash_command": "claude_commands_dir",
            "rules": "claude_rules_dir",
            "mcp_server": "claude_mcp_servers_file",
        },
        io={
            "agent": CustomizationTypeIO(
                parse=parse_agent,
                render=render,
                extract_pair_id=extract_pair_id_from_md,
                storage="single_file",
                file_suffix=".md",
            ),
            "skill": CustomizationTypeIO(
                parse=parse_skill,
                render=render,
                extract_pair_id=extract_pair_id_from_md,
                file_layout=DirectorySkillLayout(),
            ),
            "slash_command": CustomizationTypeIO(
                parse=parse_slash_command,
                render=render_slash_command,
                extract_pair_id=extract_pair_id_from_md,
                storage="single_file",
                file_suffix=".md",
                slugify_name=slash_command_slug,
                recursive=True,
            ),
            "rules": build_global_rules_io("claude", ("AGENTS.md", "CLAUDE.md")),
            "mcp_server": build_mcp_server_io(
                "claude",
                "claude_mcp_servers_file",
                ("mcpServers",),
                file_format="json",
                config=config,
                dialect=McpServerDialect(
                    render_name_field=False,
                    transport_fields=("type", "transport", "transportType"),
                    auth_fields=("oauth", "auth"),
                    auth_render_field="oauth",
                    env_reference_style="claude",
                ),
            ),
        },
    )
