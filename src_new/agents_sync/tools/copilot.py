"""GitHub Copilot — tool definition (data only). Dotted markdown suffixes."""

from __future__ import annotations

from agents_sync.tools._shared_formats import markdown_surface_format, mcp_surface_format
from agents_sync.tools.tool_definition import (
    DirectorySurfaceRecipe,
    KeyedMapSurfaceRecipe,
    ToolDefinition,
)

COPILOT_TOOL = ToolDefinition(
    name="copilot",
    surface_recipes=(
        DirectorySurfaceRecipe(
            "agent", "copilot_cli_agents_dir", ".agent.md", markdown_surface_format()
        ),
        DirectorySurfaceRecipe(
            "slash_command",
            "copilot_vscode_user_prompts_dir",
            ".prompt.md",
            markdown_surface_format(),
        ),
        DirectorySurfaceRecipe(
            "rules",
            "copilot_vscode_user_instructions_dir",
            ".instructions.md",
            markdown_surface_format(),
        ),
        KeyedMapSurfaceRecipe(
            "mcp_server", "copilot_cli_mcp_config_file", mcp_surface_format(("servers",), "json")
        ),
    ),
)
