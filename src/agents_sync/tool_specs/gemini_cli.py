"""AgenticToolSpec factory for Gemini CLI."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    RulesFileLayout,
)
from agents_sync.tool_specs._mcp_server_factory import build_mcp_server_io


def build_gemini_cli_spec(config: Mapping[str, Any] | None = None) -> AgenticToolSpec:
    from agents_sync.mcp_server_io import McpServerDialect
    from agents_sync.gemini_cli_io import (
        extract_pair_id_from_gemini_agent_md,
        extract_pair_id_from_gemini_command_toml,
        extract_pair_id_from_gemini_rules_md,
        extract_pair_id_from_gemini_skill_md,
        parse_gemini_agent_md,
        parse_gemini_command_toml,
        parse_gemini_rules_md,
        parse_gemini_skill_md,
        render_gemini_agent_md,
        render_gemini_command_toml,
        render_gemini_rules_md,
        render_gemini_skill_md,
    )
    from agents_sync.slash_command_io import slash_command_slug

    return AgenticToolSpec(
        name="gemini_cli",
        config_dir_keys={
            "agent": "gemini_cli_agents_dir",
            "skill": "gemini_cli_skills_dir",
            "rules": "gemini_cli_rules_dir",
            "slash_command": "gemini_cli_commands_dir",
            "mcp_server": "gemini_cli_settings_file",
        },
        io={
            "agent": CustomizationTypeIO(
                parse=parse_gemini_agent_md,
                render=render_gemini_agent_md,
                extract_pair_id=extract_pair_id_from_gemini_agent_md,
                storage="single_file",
                file_suffix=".md",
            ),
            "skill": CustomizationTypeIO(
                parse=parse_gemini_skill_md,
                render=render_gemini_skill_md,
                extract_pair_id=extract_pair_id_from_gemini_skill_md,
                storage="directory_skill",
                file_suffix="",
            ),
            "rules": CustomizationTypeIO(
                parse=parse_gemini_rules_md,
                render=render_gemini_rules_md,
                extract_pair_id=extract_pair_id_from_gemini_rules_md,
                file_layout=RulesFileLayout(
                    extension=".md",
                    fixed_file_name="GEMINI.md",
                ),
            ),
            "slash_command": CustomizationTypeIO(
                parse=parse_gemini_command_toml,
                render=render_gemini_command_toml,
                extract_pair_id=extract_pair_id_from_gemini_command_toml,
                storage="single_file",
                file_suffix=".toml",
                slugify_name=slash_command_slug,
                recursive=True,
            ),
            "mcp_server": build_mcp_server_io(
                "gemini_cli",
                "gemini_cli_settings_file",
                ("mcpServers",),
                file_format="json",
                config=config,
                dialect=McpServerDialect(
                    render_name_field=False,
                    render_transport_field=False,
                    url_fields=("httpUrl", "url", "serverUrl"),
                    transport_from_fields=(
                        ("httpUrl", "http"),
                        ("url", "sse"),
                        ("command", "stdio"),
                    ),
                    url_render_fields=(
                        ("http", "httpUrl"),
                        ("streamable-http", "httpUrl"),
                        ("sse", "url"),
                    ),
                    auth_fields=("oauth", "auth"),
                    auth_render_field="oauth",
                    env_reference_style="gemini",
                ),
            ),
        },
        disable_config_key="gemini_cli_enabled",
    )
