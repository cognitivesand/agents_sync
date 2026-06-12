"""Codex CLI — tool definition (data only). Agents are whole-file TOML."""

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

CODEX_TOOL = ToolDefinition(
    name="codex",
    surface_recipes=(
        DirectorySurfaceRecipe(
            "agent", "codex_agents_dir", ".toml", structured_text_surface_format("toml")
        ),
        DirectorySurfaceRecipe(
            "slash_command", "codex_prompts_dir", ".md", markdown_surface_format()
        ),
        RulesFileSurfaceRecipe(
            "rules", "codex_rules_dir", ("AGENTS.md",), markdown_surface_format()
        ),
        KeyedMapSurfaceRecipe(
            "mcp_server", "codex_config_file", mcp_surface_format(("mcp_servers",), "toml")
        ),
    ),
)
