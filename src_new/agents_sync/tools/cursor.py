"""Cursor — tool definition (data only). Rules are a directory of ``.mdc`` files."""

from __future__ import annotations

from agents_sync.domain_model.tool_surface import McpSpellingRecipe
from agents_sync.tools._shared_formats import markdown_surface_format, mcp_surface_format
from agents_sync.tools.tool_definition import (
    DefaultLocation,
    DirectorySurfaceRecipe,
    KeyedMapSurfaceRecipe,
    PathAnchor,
    ToolDefinition,
)

_HOME = PathAnchor.HOME

# Cursor's agent front-matter spellings → canonical attributes (S20 increment 2).
_AGENT_FIELD_MAP = (
    ("model", "model"),
    ("tools", "tools"),
)

# Cursor's mcp wire spells the transport field `type` (S20 increment 4).
_MCP_SPELLING = McpSpellingRecipe(transport_render_field="type")

CURSOR_TOOL = ToolDefinition(
    name="cursor",
    surface_recipes=(
        DirectorySurfaceRecipe(
            "agent",
            "cursor_agents_dir",
            ".md",
            markdown_surface_format(_AGENT_FIELD_MAP),
            default_location=DefaultLocation(_HOME, (".cursor", "agents")),
        ),
        DirectorySurfaceRecipe(
            "slash_command",
            "cursor_commands_dir",
            ".md",
            markdown_surface_format(),
            default_location=DefaultLocation(_HOME, (".cursor", "commands")),
        ),
        DirectorySurfaceRecipe(
            "rules",
            "cursor_rules_dir",
            ".mdc",
            markdown_surface_format(),
            default_location=DefaultLocation(_HOME, (".cursor", "rules")),
        ),
        KeyedMapSurfaceRecipe(
            "mcp_server",
            "cursor_mcp_servers_file",
            mcp_surface_format(("mcpServers",), "json", _MCP_SPELLING),
            default_location=DefaultLocation(_HOME, (".cursor", "mcp.json")),
        ),
    ),
)
