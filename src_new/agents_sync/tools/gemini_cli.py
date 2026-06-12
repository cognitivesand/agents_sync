"""Gemini CLI — tool definition (data only). Rules are the fixed ``GEMINI.md``;
slash commands are whole-file TOML."""

from __future__ import annotations

from agents_sync.tools._shared_formats import (
    markdown_surface_format,
    mcp_surface_format,
    structured_text_surface_format,
)
from agents_sync.tools.tool_definition import (
    DirectorySurfaceRecipe,
    KeyedMapSurfaceRecipe,
    RulesFileSurfaceRecipe,
    ToolDefinition,
)

GEMINI_CLI_TOOL = ToolDefinition(
    name="gemini_cli",
    surface_recipes=(
        DirectorySurfaceRecipe("agent", "gemini_cli_agents_dir", ".md", markdown_surface_format()),
        DirectorySurfaceRecipe(
            "slash_command",
            "gemini_cli_commands_dir",
            ".toml",
            structured_text_surface_format("toml"),
        ),
        RulesFileSurfaceRecipe(
            "rules", "gemini_cli_rules_dir", ("GEMINI.md",), markdown_surface_format()
        ),
        KeyedMapSurfaceRecipe(
            "mcp_server",
            "gemini_cli_settings_file",
            mcp_surface_format(("mcpServers",), "json"),
        ),
    ),
)
