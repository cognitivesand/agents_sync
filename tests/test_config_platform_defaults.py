from __future__ import annotations

from pathlib import Path

from agents_sync.config import default_config_path, default_state_path, platform_defaults


def _portable_path(value: object) -> str:
    return str(value).replace("\\", "/")


def test_linux_defaults_use_home_conventions():
    home = Path("/home/tester")
    defaults = platform_defaults(os_name="posix", env={}, home=home)

    assert defaults["state_path"] == str(home / ".local" / "state" / "agents-sync" / "state.json")
    assert defaults["claude_agents_dir"] == str(home / ".claude" / "agents")
    assert defaults["claude_commands_dir"] == str(home / ".claude" / "commands")
    assert defaults["claude_rules_dir"] == str(home / ".claude")
    assert defaults["claude_mcp_servers_file"] == str(home / ".claude.json")
    assert defaults["codex_agents_dir"] == str(home / ".codex" / "agents")
    assert defaults["codex_prompts_dir"] == str(home / ".codex" / "prompts")
    assert defaults["codex_skills_dir"] == str(home / ".codex" / "skills")
    assert defaults["codex_rules_dir"] == str(home / ".codex")
    assert defaults["codex_config_file"] == str(home / ".codex" / "config.toml")
    assert defaults["cursor_agents_dir"] == str(home / ".cursor" / "agents")
    assert defaults["cursor_commands_dir"] == str(home / ".cursor" / "commands")
    assert defaults["cursor_skills_dir"] == str(home / ".cursor" / "skills")
    assert defaults["cursor_rules_dir"] == str(home / ".cursor" / "rules")
    assert defaults["cursor_mcp_servers_file"] == str(home / ".cursor" / "mcp.json")
    assert defaults["cursor_enabled"] is True
    assert defaults["gemini_cli_settings_file"] == str(
        home / ".gemini" / "settings.json"
    )
    assert defaults["opencode_agents_dir"] == str(home / ".config" / "opencode" / "agents")
    assert defaults["opencode_commands_dir"] == str(home / ".config" / "opencode" / "commands")
    assert defaults["opencode_skills_dir"] == str(home / ".config" / "opencode" / "skills")
    assert defaults["opencode_rules_dir"] == str(home / ".config" / "opencode")
    assert defaults["opencode_config_file"] == str(home / ".config" / "opencode" / "opencode.json")
    assert defaults["copilot_enabled"] is True
    assert defaults["copilot_cli_enabled"] is True
    assert defaults["copilot_vscode_user_profile_enabled"] is True
    assert defaults["copilot_cli_agents_dir"] == str(home / ".copilot" / "agents")
    assert defaults["copilot_cli_skills_dir"] == str(home / ".copilot" / "skills")
    assert defaults["copilot_cli_mcp_config_file"] == str(home / ".copilot" / "mcp-config.json")
    assert defaults["copilot_vscode_user_agents_dir"] is None
    assert defaults["copilot_vscode_user_instructions_dir"] is None
    assert defaults["copilot_vscode_user_prompts_dir"] is None
    assert defaults["copilot_vscode_user_mcp_file"] is None


def test_windows_defaults_prefer_appdata_and_localappdata():
    env = {
        "APPDATA": r"C:\Users\tester\AppData\Roaming",
        "LOCALAPPDATA": r"C:\Users\tester\AppData\Local",
    }
    defaults = platform_defaults(os_name="nt", env=env, home=Path(r"C:\Users\tester"))

    assert (
        _portable_path(defaults["state_path"])
        == "C:/Users/tester/AppData/Local/agents-sync/state/state.json"
    )
    assert _portable_path(
        default_config_path(os_name="nt", env=env, home=Path(r"C:\Users\tester"))
    ) == ("C:/Users/tester/AppData/Roaming/agents-sync/config.toml")
    assert _portable_path(defaults["opencode_agents_dir"]) == (
        "C:/Users/tester/AppData/Roaming/opencode/agents"
    )
    assert _portable_path(defaults["opencode_commands_dir"]) == (
        "C:/Users/tester/AppData/Roaming/opencode/commands"
    )
    assert _portable_path(defaults["opencode_skills_dir"]) == (
        "C:/Users/tester/AppData/Roaming/opencode/skills"
    )
    assert _portable_path(defaults["opencode_rules_dir"]) == (
        "C:/Users/tester/AppData/Roaming/opencode"
    )
    assert _portable_path(defaults["opencode_config_file"]) == (
        "C:/Users/tester/AppData/Roaming/opencode/opencode.json"
    )
    assert _portable_path(defaults["cursor_agents_dir"]) == (
        "C:/Users/tester/.cursor/agents"
    )
    assert _portable_path(defaults["cursor_commands_dir"]) == (
        "C:/Users/tester/.cursor/commands"
    )
    assert _portable_path(defaults["cursor_skills_dir"]) == (
        "C:/Users/tester/.cursor/skills"
    )
    assert _portable_path(defaults["cursor_rules_dir"]) == (
        "C:/Users/tester/.cursor/rules"
    )
    assert _portable_path(defaults["cursor_mcp_servers_file"]) == (
        "C:/Users/tester/.cursor/mcp.json"
    )
    assert _portable_path(defaults["gemini_cli_settings_file"]) == (
        "C:/Users/tester/.gemini/settings.json"
    )


def test_windows_defaults_fallback_to_profile_when_env_missing():
    home = Path(r"C:\Users\tester")

    cfg = default_config_path(os_name="nt", env={}, home=home)
    st = default_state_path(os_name="nt", env={}, home=home)

    assert cfg == home / "AppData" / "Roaming" / "agents-sync" / "config.toml"
    assert st == home / "AppData" / "Local" / "agents-sync" / "state" / "state.json"
