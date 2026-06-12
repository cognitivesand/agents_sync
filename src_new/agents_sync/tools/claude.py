"""Claude Code — tool definition (data only)."""

from __future__ import annotations

from agents_sync.tools._shared_formats import markdown_surface_format, mcp_surface_format
from agents_sync.tools.tool_definition import (
    DirectorySurfaceRecipe,
    KeyedMapSurfaceRecipe,
    RulesFileSurfaceRecipe,
    ToolDefinition,
)

CLAUDE_TOOL = ToolDefinition(
    name="claude",
    surface_recipes=(
        DirectorySurfaceRecipe("agent", "claude_agents_dir", ".md", markdown_surface_format()),
        DirectorySurfaceRecipe(
            "slash_command", "claude_commands_dir", ".md", markdown_surface_format()
        ),
        RulesFileSurfaceRecipe(
            "rules", "claude_rules_dir", ("AGENTS.md", "CLAUDE.md"), markdown_surface_format()
        ),
        KeyedMapSurfaceRecipe(
            "mcp_server", "claude_mcp_servers_file", mcp_surface_format(("mcpServers",), "json")
        ),
    ),
)
