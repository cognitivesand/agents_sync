"""AgenticToolSpec factory for opencode."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
)
from agents_sync.tool_specs._mcp_server_factory import build_mcp_server_io
from agents_sync.tool_specs._rules_factory import build_global_rules_io


def build_opencode_spec(config: Mapping[str, Any] | None = None) -> AgenticToolSpec:
    from agents_sync.mcp_server_io import McpServerDialect
    from agents_sync.opencode_io import (
        extract_pair_id_from_md,
        opencode_skill_slug,
        parse_opencode_agent_md,
        parse_opencode_skill_md,
        render_opencode_agent_md,
        render_opencode_skill_md,
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
        return parse_opencode_agent_md(
            text,
            prior_canonical=prior_canonical,
            artifact_path=artifact_path,
        )

    def render_agent(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_opencode_agent_md(canonical, prior_text=prior_text)

    def parse_skill(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_opencode_skill_md(text, prior_canonical=prior_canonical)

    def render_skill(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_opencode_skill_md(canonical, prior_text=prior_text)

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
            agentic_tool_name="opencode",
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
            agentic_tool_name="opencode",
        )

    return AgenticToolSpec(
        name="opencode",
        config_dir_keys={
            "agent": "opencode_agents_dir",
            "skill": "opencode_skills_dir",
            "slash_command": "opencode_commands_dir",
            "rules": "opencode_rules_dir",
            "mcp_server": "opencode_config_file",
        },
        io={
            "agent": CustomizationTypeIO(
                parse=parse_agent,
                render=render_agent,
                extract_pair_id=extract_pair_id_from_md,
                storage="single_file",
                file_suffix=".md",
            ),
            "skill": CustomizationTypeIO(
                parse=parse_skill,
                render=render_skill,
                extract_pair_id=extract_pair_id_from_md,
                storage="directory_skill",
                file_suffix="",
                slugify_name=opencode_skill_slug,
            ),
            "slash_command": CustomizationTypeIO(
                parse=parse_slash_command,
                render=render_slash_command,
                extract_pair_id=extract_pair_id_from_md,
                storage="single_file",
                file_suffix=".md",
                slugify_name=slash_command_slug,
                recursive=True,
                reserved_names=frozenset({
                    "build",
                    "plan",
                    "general",
                    "explore",
                    "scout",
                }),
            ),
            "rules": build_global_rules_io("opencode", "AGENTS.md"),
            "mcp_server": build_mcp_server_io(
                "opencode",
                "opencode_config_file",
                ("mcp",),
                file_format="json",
                config=config,
                dialect=McpServerDialect(
                    render_name_field=False,
                    transport_fields=("type", "transport", "transportType"),
                    auth_fields=("oauth", "auth"),
                    auth_render_field="oauth",
                    command_mode="array",
                    env_fields=("environment", "env"),
                    disabled_fields=("enabled", "disabled"),
                    env_reference_style="opencode",
                    transport_render_values=(
                        ("stdio", "local"),
                        ("http", "remote"),
                        ("sse", "remote"),
                        ("streamable-http", "remote"),
                    ),
                ),
            ),
        },
        disable_config_key="opencode_enabled",
    )
