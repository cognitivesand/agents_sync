"""Cursor — tool definition (data only). Rules are a directory of ``.mdc`` files."""

from __future__ import annotations

from agents_sync.tools._shared_formats import markdown_surface_format, mcp_surface_format
from agents_sync.tools.tool_definition import (
    DirectorySurfaceRecipe,
    KeyedMapSurfaceRecipe,
    ToolDefinition,
)

CURSOR_TOOL = ToolDefinition(
    name="cursor",
    surface_recipes=(
        DirectorySurfaceRecipe("agent", "cursor_agents_dir", ".md", markdown_surface_format()),
        DirectorySurfaceRecipe(
            "slash_command", "cursor_commands_dir", ".md", markdown_surface_format()
        ),
        DirectorySurfaceRecipe("rules", "cursor_rules_dir", ".mdc", markdown_surface_format()),
        KeyedMapSurfaceRecipe(
            "mcp_server", "cursor_mcp_servers_file", mcp_surface_format(("mcpServers",), "json")
        ),
    ),
)
