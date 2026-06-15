"""GitHub Copilot — tool definition (data only). Dotted markdown suffixes."""

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

# Copilot's agent front-matter spellings → canonical attributes (S20 increment 2).
_AGENT_FIELD_MAP = (
    ("model", "model"),
    ("tools", "tools"),
)

# Copilot's mcp wire: transport under `type`, auth under `oauth` (S20 increment 4).
_MCP_SPELLING = McpSpellingRecipe(transport_render_field="type", auth_render_field="oauth")

COPILOT_TOOL = ToolDefinition(
    name="copilot",
    surface_recipes=(
        DirectorySurfaceRecipe(
            "agent",
            "copilot_cli_agents_dir",
            ".agent.md",
            markdown_surface_format(_AGENT_FIELD_MAP),
            default_location=DefaultLocation(_HOME, (".copilot", "agents")),
        ),
        DirectorySurfaceRecipe(
            "slash_command",
            "copilot_vscode_user_prompts_dir",
            ".prompt.md",
            markdown_surface_format(),
            default_location=None,
        ),
        DirectorySurfaceRecipe(
            "rules",
            "copilot_vscode_user_instructions_dir",
            ".instructions.md",
            markdown_surface_format(),
            default_location=None,
        ),
        KeyedMapSurfaceRecipe(
            "mcp_server",
            "copilot_cli_mcp_config_file",
            mcp_surface_format(("servers",), "json", _MCP_SPELLING),
            default_location=DefaultLocation(_HOME, (".copilot", "mcp-config.json")),
        ),
    ),
)
