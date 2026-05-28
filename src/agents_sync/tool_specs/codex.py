"""AgenticToolSpec factory for Codex."""
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


def build_codex_spec(config: Mapping[str, Any] | None = None) -> AgenticToolSpec:
    from agents_sync.mcp_server_io import McpServerDialect
    from agents_sync.codex_io import (
        extract_pair_id,
        parse_codex_agent_toml,
        parse_codex_skill_md,
        render_codex_agent_toml,
        render_codex_skill_md,
    )
    from agents_sync.markdown_yaml_metadata_block import extract_pair_id_from_md
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
        return parse_codex_agent_toml(text, prior_canonical=prior_canonical)

    def render_agent(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_codex_agent_toml(canonical, prior_text=prior_text)

    def parse_skill(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_codex_skill_md(text, prior_canonical=prior_canonical)

    def render_skill(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_codex_skill_md(canonical)

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
            agentic_tool_name="codex",
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
            agentic_tool_name="codex",
        )

    return AgenticToolSpec(
        name="codex",
        config_dir_keys={
            "agent": "codex_agents_dir",
            "skill": "codex_skills_dir",
            "slash_command": "codex_prompts_dir",
            "rules": "codex_rules_dir",
            "mcp_server": "codex_config_file",
        },
        io={
            "agent": CustomizationTypeIO(
                parse=parse_agent,
                render=render_agent,
                extract_pair_id=extract_pair_id,
                storage="single_file",
                file_suffix=".toml",
            ),
            "skill": CustomizationTypeIO(
                parse=parse_skill,
                render=render_skill,
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
            "rules": build_global_rules_io("codex", "AGENTS.md"),
            "mcp_server": build_mcp_server_io(
                "codex",
                "codex_config_file",
                ("mcp_servers",),
                file_format="toml",
                config=config,
                dialect=McpServerDialect(
                    render_name_field=False,
                    render_transport_field=False,
                    headers_fields=("http_headers", "headers"),
                    headers_render_field="http_headers",
                    env_http_headers_field="env_http_headers",
                    bearer_token_env_var_field="bearer_token_env_var",
                    auth_render_field=None,
                ),
            ),
        },
    )
