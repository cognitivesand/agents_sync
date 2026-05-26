"""AgenticToolSpec factory for Gemini CLI."""
from __future__ import annotations

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    RulesFileLayout,
)


def build_gemini_cli_spec() -> AgenticToolSpec:
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
        },
        disable_config_key="gemini_cli_enabled",
    )
