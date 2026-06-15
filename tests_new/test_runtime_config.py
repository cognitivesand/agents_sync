"""S21b — ``runtime_config``: resolve per-OS default paths, load/merge TOML, and
fail closed on configuration defects with a distinct exit code (NFR-10, US-07 AC-7).

Platform-resolution tests inject ``os_name`` / ``env`` / ``home`` and assert on
the pure resolver functions, so they never touch the real filesystem or depend on
the host OS. The ``load_runtime_config`` tests use ``tmp_path`` as the home so the
one I/O step (creating the state directory) stays sandboxed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.domain_model.tool_surface import SurfaceFormat
from agents_sync.runtime_config import (
    EXIT_CONFIG_FAILURE,
    EXIT_OK,
    EXIT_RUNTIME_FAILURE,
    ConfigurationError,
    default_config_path,
    default_state_path,
    load_runtime_config,
    resolve_default_paths,
)
from agents_sync.tools.agentic_tools_registry import ALL_TOOL_DEFINITIONS, tool_definition
from agents_sync.tools.tool_definition import DirectorySurfaceRecipe, ToolDefinition

WINDOWS_ENV = {
    "APPDATA": r"C:\Users\tester\AppData\Roaming",
    "LOCALAPPDATA": r"C:\Users\tester\AppData\Local",
}


# --- pure platform resolution ---------------------------------------------------------

def test_resolve_default_paths_posix_anchors_home_and_config_root() -> None:
    home = Path("/home/tester")
    paths = resolve_default_paths(ALL_TOOL_DEFINITIONS, os_name="posix", env={}, home=home)

    # HOME-anchored tools join directly under the home directory.
    assert paths["claude_agents_dir"] == home / ".claude" / "agents"
    assert paths["claude_rules_dir"] == home / ".claude"
    assert paths["claude_mcp_servers_file"] == home / ".claude.json"
    # opencode is the only CONFIG_ROOT-anchored tool: ~/.config on POSIX.
    assert paths["opencode_agents_dir"] == home / ".config" / "opencode" / "agents"
    assert paths["opencode_config_file"] == home / ".config" / "opencode" / "opencode.json"


def test_resolve_default_paths_omits_surfaces_without_a_default() -> None:
    paths = resolve_default_paths(
        ALL_TOOL_DEFINITIONS, os_name="posix", env={}, home=Path("/home/tester")
    )

    assert "copilot_vscode_user_prompts_dir" not in paths
    assert "copilot_vscode_user_instructions_dir" not in paths


def test_resolve_default_paths_windows_routes_config_root_to_appdata() -> None:
    home = Path(r"C:\Users\tester")
    paths = resolve_default_paths(
        ALL_TOOL_DEFINITIONS, os_name="nt", env=WINDOWS_ENV, home=home
    )

    appdata = Path(WINDOWS_ENV["APPDATA"])
    assert paths["opencode_agents_dir"] == appdata / "opencode" / "agents"
    # HOME-anchored tools still resolve under the user profile on Windows.
    assert paths["claude_agents_dir"] == home / ".claude" / "agents"


def test_default_state_and_config_paths_posix() -> None:
    home = Path("/home/tester")

    assert default_state_path(os_name="posix", env={}, home=home) == (
        home / ".local" / "state" / "agents-sync" / "state.json"
    )
    assert default_config_path(os_name="posix", env={}, home=home) == (
        home / ".config" / "agents-sync" / "config.toml"
    )


def test_default_state_and_config_paths_windows_use_env_roots() -> None:
    home = Path(r"C:\Users\tester")

    assert default_state_path(os_name="nt", env=WINDOWS_ENV, home=home) == (
        Path(WINDOWS_ENV["LOCALAPPDATA"]) / "agents-sync" / "state" / "state.json"
    )
    assert default_config_path(os_name="nt", env=WINDOWS_ENV, home=home) == (
        Path(WINDOWS_ENV["APPDATA"]) / "agents-sync" / "config.toml"
    )


def test_windows_paths_fall_back_to_profile_when_env_missing() -> None:
    home = Path(r"C:\Users\tester")

    assert default_config_path(os_name="nt", env={}, home=home) == (
        home / "AppData" / "Roaming" / "agents-sync" / "config.toml"
    )
    assert default_state_path(os_name="nt", env={}, home=home) == (
        home / "AppData" / "Local" / "agents-sync" / "state" / "state.json"
    )


# --- load / merge ---------------------------------------------------------------------

def test_load_defaults_when_no_config_file_present(tmp_path: Path) -> None:
    cfg = load_runtime_config(config_path=None, os_name="posix", env={}, home=tmp_path)

    assert cfg.poll_interval_seconds == 2.0
    assert cfg.secret_policy == "secrets_refused"
    assert cfg.state_path == tmp_path / ".local" / "state" / "agents-sync" / "state.json"
    assert cfg.resolved_paths["claude_agents_dir"] == tmp_path / ".claude" / "agents"


def test_load_creates_the_state_directory(tmp_path: Path) -> None:
    # The single I/O step: the state directory is created so the daemon can write.
    cfg = load_runtime_config(config_path=None, os_name="posix", env={}, home=tmp_path)

    assert cfg.state_path.parent.is_dir()


def test_toml_overrides_scalars_and_a_surface_path(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[agents-sync]\n"
        "poll_interval_seconds = 5\n"
        'secret_policy = "secrets_accepted"\n'
        'claude_agents_dir = "/custom/agents"\n'
    )

    cfg = load_runtime_config(config_path=config_file, os_name="posix", env={}, home=tmp_path)

    assert cfg.poll_interval_seconds == 5.0
    assert cfg.secret_policy == "secrets_accepted"
    assert cfg.resolved_paths["claude_agents_dir"] == Path("/custom/agents")


def test_toml_can_supply_a_surface_that_has_no_default(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text('[agents-sync]\ncopilot_vscode_user_prompts_dir = "/vs/prompts"\n')

    cfg = load_runtime_config(config_path=config_file, os_name="posix", env={}, home=tmp_path)

    assert cfg.resolved_paths["copilot_vscode_user_prompts_dir"] == Path("/vs/prompts")


# --- fail closed (US-07 AC-7) ---------------------------------------------------------

def test_malformed_toml_fails_closed(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("this is = = not toml")

    with pytest.raises(ConfigurationError, match="(?i)toml"):
        load_runtime_config(config_path=config_file, os_name="posix", env={}, home=tmp_path)


@pytest.mark.parametrize("value", ["0", "-1", '"abc"'])
def test_non_positive_or_non_numeric_poll_interval_fails_closed(
    tmp_path: Path, value: str
) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(f"[agents-sync]\npoll_interval_seconds = {value}\n")

    with pytest.raises(ConfigurationError, match="poll_interval"):
        load_runtime_config(config_path=config_file, os_name="posix", env={}, home=tmp_path)


def test_unknown_secret_policy_fails_closed(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text('[agents-sync]\nsecret_policy = "permissive"\n')

    with pytest.raises(ConfigurationError, match="secret_policy"):
        load_runtime_config(config_path=config_file, os_name="posix", env={}, home=tmp_path)


def test_duplicate_tool_names_fail_closed(tmp_path: Path) -> None:
    duplicated = (tool_definition("claude"), tool_definition("claude"))

    with pytest.raises(ConfigurationError, match="(?i)duplicate"):
        load_runtime_config(
            config_path=None,
            os_name="posix",
            env={},
            home=tmp_path,
            tool_definitions=duplicated,
        )


def test_recipe_naming_an_unregistered_dialect_fails_closed(tmp_path: Path) -> None:
    bad_tool = ToolDefinition(
        "imaginary",
        (
            DirectorySurfaceRecipe(
                "agent",
                "imaginary_agents_dir",
                ".md",
                SurfaceFormat(dialect="no_such_dialect"),
                default_location=None,
            ),
        ),
    )

    with pytest.raises(ConfigurationError, match="(?i)dialect"):
        load_runtime_config(
            config_path=None,
            os_name="posix",
            env={},
            home=tmp_path,
            tool_definitions=(bad_tool,),
        )


def test_uncreatable_state_path_parent_fails_closed(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a directory is needed")
    config_file = tmp_path / "config.toml"
    config_file.write_text(f'[agents-sync]\nstate_path = "{blocker / "sub" / "state.json"}"\n')

    with pytest.raises(ConfigurationError, match="state_path"):
        load_runtime_config(config_path=config_file, os_name="posix", env={}, home=tmp_path)


# --- distinct exit codes (NFR-10) -----------------------------------------------------

def test_exit_codes_are_distinct_and_pinned() -> None:
    assert EXIT_OK == 0
    assert EXIT_RUNTIME_FAILURE == 1
    assert EXIT_CONFIG_FAILURE == 2
    assert len({EXIT_OK, EXIT_RUNTIME_FAILURE, EXIT_CONFIG_FAILURE}) == 3
