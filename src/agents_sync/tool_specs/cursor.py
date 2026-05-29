"""AgenticToolSpec factory for Cursor."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    DirectorySkillLayout,
    RulesFileLayout,
    SharedKeyedMapLayout,
    SingleFileLayout,
)


def build_cursor_spec(config: Mapping[str, Any] | None = None) -> AgenticToolSpec:
    from agents_sync.cursor_io import (
        extract_pair_id_from_cursor_agent_md,
        extract_pair_id_from_cursor_command_md,
        extract_pair_id_from_cursor_mcp_server_json,
        extract_pair_id_from_cursor_rule_mdc,
        extract_pair_id_from_cursor_skill_md,
        parse_cursor_agent_md,
        parse_cursor_command_md,
        parse_cursor_mcp_server_json,
        parse_cursor_rule_mdc,
        parse_cursor_skill_md,
        render_cursor_agent_md,
        render_cursor_command_md,
        render_cursor_mcp_server_json,
        render_cursor_rule_mdc,
        render_cursor_skill_md,
    )
    from agents_sync.slash_command_io import slash_command_slug

    def secret_policy() -> str:
        if config is None:
            return "secrets_refused"
        return str(
            config.get("secret_policy")
            or config.get("mcp_server_secret_policy")
            or "secrets_refused"
        )

    def parse_mcp_server(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_cursor_mcp_server_json(
            text,
            prior_canonical,
            artifact_path=artifact_path,
            artifact_root=artifact_root,
            secret_policy=secret_policy(),
        )

    def render_mcp_server(
        canonical: dict[str, Any],
        prior_text: str | None,
    ) -> str:
        return render_cursor_mcp_server_json(
            canonical,
            prior_text,
            secret_policy=secret_policy(),
        )

    return AgenticToolSpec(
        name="cursor",
        config_dir_keys={
            "agent": "cursor_agents_dir",
            "skill": "cursor_skills_dir",
            "rules": "cursor_rules_dir",
            "slash_command": "cursor_commands_dir",
            "mcp_server": "cursor_mcp_servers_file",
        },
        io={
            "agent": CustomizationTypeIO(
                parse=parse_cursor_agent_md,
                render=render_cursor_agent_md,
                extract_pair_id=extract_pair_id_from_cursor_agent_md,
                file_layout=SingleFileLayout(extension=".md"),
            ),
            "skill": CustomizationTypeIO(
                parse=parse_cursor_skill_md,
                render=render_cursor_skill_md,
                extract_pair_id=extract_pair_id_from_cursor_skill_md,
                file_layout=DirectorySkillLayout(),
            ),
            "rules": CustomizationTypeIO(
                parse=parse_cursor_rule_mdc,
                render=render_cursor_rule_mdc,
                extract_pair_id=extract_pair_id_from_cursor_rule_mdc,
                file_layout=RulesFileLayout(extension=".mdc"),
                recursive=True,
            ),
            "slash_command": CustomizationTypeIO(
                parse=parse_cursor_command_md,
                render=render_cursor_command_md,
                extract_pair_id=extract_pair_id_from_cursor_command_md,
                file_layout=SingleFileLayout(extension=".md"),
                slugify_name=slash_command_slug,
                recursive=True,
            ),
            "mcp_server": CustomizationTypeIO(
                parse=parse_mcp_server,
                render=render_mcp_server,
                extract_pair_id=extract_pair_id_from_cursor_mcp_server_json,
                file_layout=SharedKeyedMapLayout(
                    shared_path_config_key="cursor_mcp_servers_file",
                    map_key_path=("mcpServers",),
                    file_format="json",
                ),
            ),
        },
        disable_config_key="cursor_enabled",
    )
