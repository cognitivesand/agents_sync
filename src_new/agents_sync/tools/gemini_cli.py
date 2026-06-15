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

# Gemini CLI's agent front-matter spellings → canonical attributes (S20 increment 2).
# Only ``model`` folds; gemini's ``tools`` stay tool-private (per_tool_extra) until a
# later increment, matching the old codec.
_AGENT_FIELD_MAP = (("model", "model"),)

GEMINI_CLI_TOOL = ToolDefinition(
    name="gemini_cli",
    surface_recipes=(
        DirectorySurfaceRecipe(
            "agent", "gemini_cli_agents_dir", ".md", markdown_surface_format(_AGENT_FIELD_MAP)
        ),
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
