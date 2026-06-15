"""opencode — tool definition (data only).

opencode's mcp wire spellings live in ``_MCP_SPELLING`` below and are consumed generically
by the mcp_server dialect (S20 increment 3): ``environment`` for env, the inverted-polarity
``enabled`` flag, the array-form command, ``type`` transport with ``local``/``remote``
values, ``oauth`` auth, and the ``{env:NAME}`` env-reference inline style (S20 increment 7).
The agent ``model`` provider-split and ``tools``→``permission`` transforms remain deferred
(they round-trip verbatim via ``per_tool_extra`` until then).
"""

from __future__ import annotations

from agents_sync.domain_model.tool_surface import McpSpellingRecipe
from agents_sync.tools._shared_formats import markdown_surface_format, mcp_surface_format
from agents_sync.tools.tool_definition import (
    DirectorySurfaceRecipe,
    KeyedMapSurfaceRecipe,
    RulesFileSurfaceRecipe,
    ToolDefinition,
)

_MCP_SPELLING = McpSpellingRecipe(
    env_field="environment",
    disabled_field="enabled",
    disabled_inverted=True,
    command_mode="array",
    transport_render_field="type",
    transport_render_values=(
        ("stdio", "local"),
        ("http", "remote"),
        ("sse", "remote"),
        ("streamable-http", "remote"),
    ),
    auth_render_field="oauth",
    env_reference_style=("{env:", "}"),  # opencode writes env refs as {env:NAME} (S20 increment 7)
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
            "mcp_server",
            "opencode_config_file",
            mcp_surface_format(("mcp",), "json", _MCP_SPELLING),
        ),
    ),
)
