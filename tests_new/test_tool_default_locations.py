"""S21a — each surface recipe carries its default filesystem location as data.

These tests pin the per-tool default locations (a ``PathAnchor`` plus the parts
relative to it) that ``runtime_config`` (S21b) resolves into the
``config_key -> Path`` map the read phase consumes. The table below is the
authoritative statement of those defaults, mirroring the documented platform
conventions; a tool that changes a default path must change this table too.
"""

from __future__ import annotations

import dataclasses

import pytest

from agents_sync.tools.agentic_tools_registry import ALL_TOOL_DEFINITIONS, tool_definition
from agents_sync.tools.tool_definition import DefaultLocation, PathAnchor, SurfaceRecipe

HOME = PathAnchor.HOME
CONFIG_ROOT = PathAnchor.CONFIG_ROOT

# config_key -> the default location the tool data must declare. ``None`` means the
# surface has no built-in default: it is absent unless the config file names a path.
EXPECTED_DEFAULT_LOCATIONS: dict[str, DefaultLocation | None] = {
    # claude — everything under ~/.claude
    "claude_agents_dir": DefaultLocation(HOME, (".claude", "agents")),
    "claude_commands_dir": DefaultLocation(HOME, (".claude", "commands")),
    "claude_rules_dir": DefaultLocation(HOME, (".claude",)),
    "claude_mcp_servers_file": DefaultLocation(HOME, (".claude.json",)),
    # codex — under ~/.codex
    "codex_agents_dir": DefaultLocation(HOME, (".codex", "agents")),
    "codex_prompts_dir": DefaultLocation(HOME, (".codex", "prompts")),
    "codex_rules_dir": DefaultLocation(HOME, (".codex",)),
    "codex_config_file": DefaultLocation(HOME, (".codex", "config.toml")),
    # cursor — under ~/.cursor
    "cursor_agents_dir": DefaultLocation(HOME, (".cursor", "agents")),
    "cursor_commands_dir": DefaultLocation(HOME, (".cursor", "commands")),
    "cursor_rules_dir": DefaultLocation(HOME, (".cursor", "rules")),
    "cursor_mcp_servers_file": DefaultLocation(HOME, (".cursor", "mcp.json")),
    # copilot — CLI surfaces under ~/.copilot; the VS Code user surfaces have no
    # built-in default (discovered / configured only).
    "copilot_cli_agents_dir": DefaultLocation(HOME, (".copilot", "agents")),
    "copilot_vscode_user_prompts_dir": None,
    "copilot_vscode_user_instructions_dir": None,
    "copilot_cli_mcp_config_file": DefaultLocation(HOME, (".copilot", "mcp-config.json")),
    # gemini_cli — under ~/.gemini
    "gemini_cli_agents_dir": DefaultLocation(HOME, (".gemini", "agents")),
    "gemini_cli_commands_dir": DefaultLocation(HOME, (".gemini", "commands")),
    "gemini_cli_rules_dir": DefaultLocation(HOME, (".gemini",)),
    "gemini_cli_settings_file": DefaultLocation(HOME, (".gemini", "settings.json")),
    # opencode — under the per-OS config root (CONFIG_ROOT: ~/.config or %APPDATA%),
    # the only tool whose default root diverges by operating system.
    "opencode_agents_dir": DefaultLocation(CONFIG_ROOT, ("opencode", "agents")),
    "opencode_commands_dir": DefaultLocation(CONFIG_ROOT, ("opencode", "commands")),
    "opencode_rules_dir": DefaultLocation(CONFIG_ROOT, ("opencode",)),
    "opencode_config_file": DefaultLocation(CONFIG_ROOT, ("opencode", "opencode.json")),
}


_RECIPES_BY_CONFIG_KEY: dict[str, SurfaceRecipe] = {
    recipe.config_key: recipe
    for definition in ALL_TOOL_DEFINITIONS
    for recipe in definition.surface_recipes
}


def test_expected_table_covers_exactly_the_declared_config_keys() -> None:
    declared = set(_RECIPES_BY_CONFIG_KEY)
    expected = set(EXPECTED_DEFAULT_LOCATIONS)
    assert declared == expected, (
        f"config-key completeness drift: only in recipes={declared - expected}, "
        f"only in expected table={expected - declared}"
    )


@pytest.mark.parametrize("config_key", sorted(EXPECTED_DEFAULT_LOCATIONS))
def test_each_recipe_declares_its_documented_default_location(config_key: str) -> None:
    assert _RECIPES_BY_CONFIG_KEY[config_key].default_location == (
        EXPECTED_DEFAULT_LOCATIONS[config_key]
    )


def test_default_location_is_immutable() -> None:
    location = tool_definition("claude").surface_recipes[0].default_location
    assert location is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        location.relative_parts = ()  # type: ignore[misc]
