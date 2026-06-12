"""Tool definitions — the recipe types tools-as-data instantiate (pure data, §13).

A ``ToolDefinition`` is one tool's complete integration: a tuple of per-kind
surface recipes, each pairing a config key (resolved to a real path by the
runtime config, S21) with the layout and ``SurfaceFormat`` the read phase and
translation need. Adding a tool is one data module plus a registry entry; no
sync-mechanism change (NFR-11). Recipes carry no callables — behaviour lives in
the dialects, selected by the format's ``dialect`` field.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents_sync.domain_model.tool_surface import SurfaceFormat


@dataclass(frozen=True)
class DirectorySurfaceRecipe:
    """Per-file artifacts in a configured directory (agents, commands, rule files)."""

    kind: str
    config_key: str
    filename_suffix: str
    surface_format: SurfaceFormat


@dataclass(frozen=True)
class KeyedMapSurfaceRecipe:
    """Artifacts as slots of one configured shared keyed-map file (mcp servers)."""

    kind: str
    config_key: str
    surface_format: SurfaceFormat


@dataclass(frozen=True)
class RulesFileSurfaceRecipe:
    """The whole-file global-rules family: an ordered filename precedence (FR-10)."""

    kind: str
    config_key: str
    candidate_filenames: tuple[str, ...]
    surface_format: SurfaceFormat


type SurfaceRecipe = DirectorySurfaceRecipe | KeyedMapSurfaceRecipe | RulesFileSurfaceRecipe


@dataclass(frozen=True)
class ToolDefinition:
    """One tool's integration, as data: its name and its per-kind surface recipes.

    Kinds a tool supports but the rebuild's dialects do not yet (directory-tree
    skills) are absent from ``surface_recipes`` until their dialect lands."""

    name: str
    surface_recipes: tuple[SurfaceRecipe, ...] = ()
