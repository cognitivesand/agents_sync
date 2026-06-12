"""The tool registry — every supported tool's definition, and the spec builder.

``surface_specs_for`` turns one definition plus the runtime-resolved paths into
the read phase's ``SurfaceSpec``s. A recipe whose config key has no resolved
path contributes nothing — the tool or kind is absent on this machine, and an
absent tool blocks nothing (US-11). An unknown tool name is a configuration
bug and fails loud.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agents_sync.read_tool_surfaces import (
    DirectorySurfaceSpec,
    KeyedMapSurfaceSpec,
    RulesFileSurfaceSpec,
    SurfaceSpec,
)
from agents_sync.tools.antigravity import ANTIGRAVITY_TOOL
from agents_sync.tools.claude import CLAUDE_TOOL
from agents_sync.tools.codex import CODEX_TOOL
from agents_sync.tools.copilot import COPILOT_TOOL
from agents_sync.tools.cursor import CURSOR_TOOL
from agents_sync.tools.gemini_cli import GEMINI_CLI_TOOL
from agents_sync.tools.opencode import OPENCODE_TOOL
from agents_sync.tools.tool_definition import (
    DirectorySurfaceRecipe,
    RulesFileSurfaceRecipe,
    ToolDefinition,
)

ALL_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    CLAUDE_TOOL,
    CODEX_TOOL,
    CURSOR_TOOL,
    COPILOT_TOOL,
    GEMINI_CLI_TOOL,
    OPENCODE_TOOL,
    ANTIGRAVITY_TOOL,
)

_DEFINITIONS_BY_NAME = {definition.name: definition for definition in ALL_TOOL_DEFINITIONS}


def tool_definition(tool_name: str) -> ToolDefinition:
    """The named tool's definition; an unknown name is a configuration bug."""
    try:
        return _DEFINITIONS_BY_NAME[tool_name]
    except KeyError:
        raise ValueError(
            f"unknown tool: {tool_name!r} (supported: {sorted(_DEFINITIONS_BY_NAME)})"
        ) from None


def surface_specs_for(
    definition: ToolDefinition, resolved_paths: Mapping[str, Path]
) -> tuple[SurfaceSpec, ...]:
    """The read-phase specs for one tool, given its runtime-resolved paths.

    A recipe whose config key is unresolved is skipped — that tool/kind is
    absent on this machine and contributes no surfaces (US-11)."""
    specs: list[SurfaceSpec] = []
    for recipe in definition.surface_recipes:
        resolved_path = resolved_paths.get(recipe.config_key)
        if resolved_path is None:
            continue
        if isinstance(recipe, DirectorySurfaceRecipe):
            specs.append(
                DirectorySurfaceSpec(
                    definition.name,
                    recipe.kind,
                    resolved_path,
                    recipe.filename_suffix,
                    recipe.surface_format,
                )
            )
        elif isinstance(recipe, RulesFileSurfaceRecipe):
            specs.append(
                RulesFileSurfaceSpec(
                    definition.name,
                    recipe.kind,
                    resolved_path,
                    recipe.candidate_filenames,
                    recipe.surface_format,
                )
            )
        else:
            specs.append(
                KeyedMapSurfaceSpec(
                    definition.name, recipe.kind, resolved_path, recipe.surface_format
                )
            )
    return tuple(specs)
