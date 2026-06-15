"""Tool-surface vocabulary — immutable value objects (pure, no I/O).

A ``ToolSurface`` describes where one agentic tool keeps one artifact: its
``tool`` name, ``kind`` (customization_type), ``location`` (a file path, or a slot
inside a shared keyed-map file), and the ``surface_format`` recipe used to
translate it.

These are declarative value objects with no behaviour. ``SurfaceFormat`` carries the
translation recipe the markdown dialect consumes (S9): the ``dialect`` discriminator,
the ``id_field`` (the front-matter key the embedded id lives under), the
``known_fields`` map (front-matter key → canonical attribute, so a tool's native
spelling folds onto the canonical name), and ``tool_only_fields`` (front-matter keys
kept verbatim under ``per_tool_only[tool]``). The remaining recipe fields (reserved
names, rules-filename precedence) grow with the read phase (S17), per YAGNI. Every
field is hashable, so a ``ToolSurface`` can be grouped in sets by the planner.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KeyedMapSlot:
    """A location inside a shared keyed-map file (e.g. one mcp_server entry)."""

    file: Path
    slot: str


@dataclass(frozen=True)
class McpSpellingRecipe:
    """One tool's mcp wire spellings/semantics — declarative data the mcp_server dialect
    reads (proposal §10). The defaults reproduce the canonical wire, so a tool overrides
    only what differs; the dialect never branches on the tool name (the quirks are data).

    ``env_field`` / ``disabled_field`` are this tool's spellings for env and the disabled
    flag; ``disabled_inverted`` marks an inverted flag (opencode's ``enabled`` = not
    disabled). ``command_mode`` ``"array"`` spells the stdio invocation as one
    ``[command, *args]`` list. ``transport_render_field`` / ``auth_render_field`` /
    ``headers_render_field`` are the keys a *fresh* projection emits (an observed spelling
    still wins on round-trip); ``auth_render_field`` is ``None`` for a tool with no generic
    auth block (codex). ``transport_render_values`` maps a canonical transport to this tool's
    wire value (opencode: ``stdio``→``local``).

    ``env_http_headers_field`` / ``bearer_token_env_var_field`` are codex's dedicated HTTP
    auth carriers: when set, an env-reference header (``${env:NAME}``) round-trips through the
    named field (a header→env-name map, and a single bearer env-name) instead of an inline
    header value; ``None`` (the default) leaves env-reference headers inline."""

    env_field: str = "env"
    disabled_field: str = "disabled"
    disabled_inverted: bool = False
    command_mode: str = "split"
    transport_render_field: str = "transport"
    transport_render_values: tuple[tuple[str, str], ...] = ()
    auth_render_field: str | None = "auth"
    headers_render_field: str = "headers"
    env_http_headers_field: str | None = None
    bearer_token_env_var_field: str | None = None


@dataclass(frozen=True)
class SurfaceFormat:
    """How a surface is encoded — the dialect plus the recipe its translation applies.

    ``known_fields`` is an ordered tuple of ``(field_key, canonical_attribute)`` pairs
    (a tuple, not a dict, so the value object stays hashable); ``tool_only_fields`` are
    field keys preserved under ``per_tool_only[tool]``. ``map_key_path`` and
    ``file_format`` are the keyed-map recipe: the nested keys to the slot-map inside the
    shared file (e.g. ``("mcpServers",)``) and the structured-text format that file is in
    (``"json"``). ``mcp_spelling`` carries the per-tool mcp wire recipe (the mcp_server
    dialect substitutes the canonical defaults when it is ``None``). All default empty so a
    format that needs no recipe is ``SurfaceFormat(dialect=...)``.
    """

    dialect: str
    id_field: str = ""
    known_fields: tuple[tuple[str, str], ...] = ()
    tool_only_fields: tuple[str, ...] = ()
    map_key_path: tuple[str, ...] = ()
    file_format: str = ""
    mcp_spelling: McpSpellingRecipe | None = None


@dataclass(frozen=True)
class ToolSurface:
    """Where one agentic tool keeps one artifact, and how to translate it."""

    tool: str
    kind: str
    location: Path | KeyedMapSlot
    surface_format: SurfaceFormat
