"""Config and CLI coverage for the Gemini CLI adapter."""
from __future__ import annotations

from pathlib import Path

from agents_sync.cli import build_parser
from agents_sync.config import merged_config, platform_defaults


def test_platform_defaults_include_gemini_cli_roots():
    home = Path("/home/tester")
    defaults = platform_defaults(os_name="posix", env={}, home=home)

    assert defaults["gemini_cli_agents_dir"] == str(home / ".gemini" / "agents")
    assert defaults["gemini_cli_commands_dir"] == str(home / ".gemini" / "commands")
    assert defaults["gemini_cli_skills_dir"] == str(home / ".gemini" / "skills")
    assert defaults["gemini_cli_rules_dir"] == str(home / ".gemini")
    assert defaults["gemini_cli_settings_file"] == str(
        home / ".gemini" / "settings.json"
    )
    assert defaults["gemini_cli_enabled"] is True
    assert defaults["antigravity_skills_dir"] == str(
        home / ".gemini" / "antigravity" / "skills"
    )


def test_cli_parser_accepts_gemini_cli_flags():
    parser = build_parser()
    args = parser.parse_args([
        "--gemini-cli-agents-dir",
        "/gemini/agents",
        "--gemini-cli-commands-dir",
        "/gemini/commands",
        "--gemini-cli-skills-dir",
        "/gemini/skills",
        "--gemini-cli-rules-dir",
        "/gemini",
        "--gemini-cli-settings-file",
        "/gemini/settings.json",
        "--no-gemini-cli-enabled",
    ])

    assert args.gemini_cli_agents_dir == "/gemini/agents"
    assert args.gemini_cli_commands_dir == "/gemini/commands"
    assert args.gemini_cli_skills_dir == "/gemini/skills"
    assert args.gemini_cli_rules_dir == "/gemini"
    assert args.gemini_cli_settings_file == "/gemini/settings.json"
    assert args.gemini_cli_enabled is False


def test_merged_config_honors_gemini_cli_overrides():
    parser = build_parser()
    args = parser.parse_args([
        "--gemini-cli-agents-dir",
        "/custom/agents",
        "--gemini-cli-settings-file",
        "/custom/settings.json",
        "--no-gemini-cli-enabled",
    ])

    config = merged_config(args)

    assert config["gemini_cli_agents_dir"] == "/custom/agents"
    assert config["gemini_cli_settings_file"] == "/custom/settings.json"
    assert config["gemini_cli_enabled"] is False
