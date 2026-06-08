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
class SurfaceFormat:
    """How a surface is encoded — the dialect plus the recipe its translation applies.

    ``known_fields`` is an ordered tuple of ``(field_key, canonical_attribute)`` pairs
    (a tuple, not a dict, so the value object stays hashable); ``tool_only_fields`` are
    field keys preserved under ``per_tool_only[tool]``. ``map_key_path`` and
    ``file_format`` are the keyed-map recipe: the nested keys to the slot-map inside the
    shared file (e.g. ``("mcpServers",)``) and the structured-text format that file is in
    (``"json"``). All default empty so a format that needs no recipe is
    ``SurfaceFormat(dialect=...)``.
    """

    dialect: str
    id_field: str = ""
    known_fields: tuple[tuple[str, str], ...] = ()
    tool_only_fields: tuple[str, ...] = ()
    map_key_path: tuple[str, ...] = ()
    file_format: str = ""


@dataclass(frozen=True)
class ToolSurface:
    """Where one agentic tool keeps one artifact, and how to translate it."""

    tool: str
    kind: str
    location: Path | KeyedMapSlot
    surface_format: SurfaceFormat
