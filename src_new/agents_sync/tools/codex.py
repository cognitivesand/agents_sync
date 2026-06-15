"""Codex CLI — tool definition (data only). Agents are whole-file TOML."""

from __future__ import annotations

from agents_sync.domain_model.tool_surface import McpSpellingRecipe
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

# Codex's whole-file TOML agent spellings → canonical attributes (S20 increment 2).
_AGENT_FIELD_MAP = (
    ("model", "model"),
    ("model_reasoning_effort", "effort"),
)

# Codex spells HTTP auth across dedicated carriers, not a generic headers/auth block (S20
# increment 5): `http_headers` for literal headers, `env_http_headers` (header→env-name) and
# `bearer_token_env_var` (one env-name → Authorization bearer) for env-reference headers, and
# no generic auth field. The dialect folds all three onto the canonical `headers` map.
_MCP_SPELLING = McpSpellingRecipe(
    headers_render_field="http_headers",
    env_http_headers_field="env_http_headers",
    bearer_token_env_var_field="bearer_token_env_var",
    auth_render_field=None,
)

CODEX_TOOL = ToolDefinition(
    name="codex",
    surface_recipes=(
        DirectorySurfaceRecipe(
            "agent",
            "codex_agents_dir",
            ".toml",
            structured_text_surface_format("toml", _AGENT_FIELD_MAP),
        ),
        DirectorySurfaceRecipe(
            "slash_command", "codex_prompts_dir", ".md", markdown_surface_format()
        ),
        RulesFileSurfaceRecipe(
            "rules", "codex_rules_dir", ("AGENTS.md",), markdown_surface_format()
        ),
        KeyedMapSurfaceRecipe(
            "mcp_server",
            "codex_config_file",
            mcp_surface_format(("mcp_servers",), "toml", _MCP_SPELLING),
        ),
    ),
)
