"""AgenticToolSpec factory for GitHub Copilot."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    RulesFileLayout,
)
from agents_sync.tool_specs._mcp_server_factory import build_mcp_server_io


def build_copilot_spec(config: Mapping[str, Any] | None = None) -> AgenticToolSpec:
    from agents_sync.copilot_io import (
        copilot_skill_slug,
        extract_pair_id_from_copilot_agent_md,
        extract_pair_id_from_copilot_instruction_md,
        extract_pair_id_from_copilot_prompt_md,
        extract_pair_id_from_copilot_skill_md,
        parse_copilot_agent_md,
        parse_copilot_instruction_md,
        parse_copilot_prompt_md,
        parse_copilot_skill_md,
        render_copilot_agent_md,
        render_copilot_instruction_md,
        render_copilot_prompt_md,
        render_copilot_skill_md,
    )
    from agents_sync.mcp_server_io import McpServerDialect
    from agents_sync.slash_command_io import slash_command_slug

    return AgenticToolSpec(
        name="copilot",
        config_dir_keys={
            "agent": "copilot_cli_agents_dir",
            "skill": "copilot_cli_skills_dir",
            "rules": "copilot_vscode_user_instructions_dir",
            "slash_command": "copilot_vscode_user_prompts_dir",
            "mcp_server": "copilot_cli_mcp_config_file",
        },
        io={
            "agent": CustomizationTypeIO(
                parse=parse_copilot_agent_md,
                render=render_copilot_agent_md,
                extract_pair_id=extract_pair_id_from_copilot_agent_md,
                storage="single_file",
                file_suffix=".agent.md",
                accepted_file_suffixes=(".agent.md", ".chatmode.md", ".md"),
            ),
            "skill": CustomizationTypeIO(
                parse=parse_copilot_skill_md,
                render=render_copilot_skill_md,
                extract_pair_id=extract_pair_id_from_copilot_skill_md,
                storage="directory_skill",
                file_suffix="",
                slugify_name=copilot_skill_slug,
            ),
            "rules": CustomizationTypeIO(
                parse=parse_copilot_instruction_md,
                render=render_copilot_instruction_md,
                extract_pair_id=extract_pair_id_from_copilot_instruction_md,
                file_layout=RulesFileLayout(extension=".instructions.md"),
            ),
            "slash_command": CustomizationTypeIO(
                parse=parse_copilot_prompt_md,
                render=render_copilot_prompt_md,
                extract_pair_id=extract_pair_id_from_copilot_prompt_md,
                storage="single_file",
                file_suffix=".prompt.md",
                slugify_name=slash_command_slug,
                recursive=True,
            ),
            "mcp_server": build_mcp_server_io(
                "copilot",
                "copilot_cli_mcp_config_file",
                ("servers",),
                file_format="json",
                config=config,
                dialect=McpServerDialect(
                    render_name_field=False,
                    transport_fields=("type", "transport", "transportType"),
                    auth_fields=("oauth", "auth"),
                    auth_render_field="oauth",
                ),
            ),
        },
        disable_config_key="copilot_enabled",
        partial_availability=True,
        kind_disable_config_keys={
            "agent": "copilot_cli_enabled",
            "skill": "copilot_cli_enabled",
            "mcp_server": "copilot_cli_enabled",
            "rules": "copilot_vscode_user_profile_enabled",
            "slash_command": "copilot_vscode_user_profile_enabled",
        },
    )
