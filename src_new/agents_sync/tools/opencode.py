"""opencode — tool definition (data only).

The per-tool mcp spellings this tool needs (``environment`` for env, the
inverted-polarity ``enabled`` flag, array-form command) are the next S20
increment; until then those keys round-trip verbatim via ``per_tool_extra``.
"""

from __future__ import annotations

from agents_sync.tools._shared_formats import markdown_surface_format, mcp_surface_format
from agents_sync.tools.tool_definition import (
    DirectorySurfaceRecipe,
    KeyedMapSurfaceRecipe,
    RulesFileSurfaceRecipe,
    ToolDefinition,
)

OPENCODE_TOOL = ToolDefinition(
    name="opencode",
    surface_recipes=(
        DirectorySurfaceRecipe("agent", "opencode_agents_dir", ".md", markdown_surface_format()),
        DirectorySurfaceRecipe(
            "slash_command", "opencode_commands_dir", ".md", markdown_surface_format()
        ),
        RulesFileSurfaceRecipe(
            "rules", "opencode_rules_dir", ("AGENTS.md",), markdown_surface_format()
        ),
        KeyedMapSurfaceRecipe(
            "mcp_server", "opencode_config_file", mcp_surface_format(("mcp",), "json")
        ),
    ),
)
