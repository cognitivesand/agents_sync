from __future__ import annotations

from pathlib import Path

from agents_sync.config import default_config_path, default_state_path, platform_defaults


def test_linux_defaults_use_home_conventions():
    home = Path("/home/tester")
    defaults = platform_defaults(os_name="posix", env={}, home=home)

    assert defaults["state_path"] == str(home / ".local" / "state" / "agents-sync" / "state.json")
    assert defaults["claude_agents_dir"] == str(home / ".claude" / "agents")
    assert defaults["codex_skills_dir"] == str(home / ".agents" / "skills")


def test_windows_defaults_prefer_appdata_and_localappdata():
    env = {
        "APPDATA": r"C:\Users\tester\AppData\Roaming",
        "LOCALAPPDATA": r"C:\Users\tester\AppData\Local",
    }
    defaults = platform_defaults(os_name="nt", env=env, home=Path(r"C:\Users\tester"))

    assert Path(defaults["state_path"]) == Path(r"C:\Users\tester\AppData\Local\agents-sync\state\state.json")
    assert default_config_path(os_name="nt", env=env, home=Path(r"C:\Users\tester")) == Path(
        r"C:\Users\tester\AppData\Roaming\agents-sync\config.toml"
    )


def test_windows_defaults_fallback_to_profile_when_env_missing():
    home = Path(r"C:\Users\tester")

    cfg = default_config_path(os_name="nt", env={}, home=home)
    st = default_state_path(os_name="nt", env={}, home=home)

    assert cfg == home / "AppData" / "Roaming" / "agents-sync" / "config.toml"
    assert st == home / "AppData" / "Local" / "agents-sync" / "state" / "state.json"
