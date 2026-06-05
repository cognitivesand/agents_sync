"""Tool-surface vocabulary — immutable value objects (pure, no I/O).

A ``ToolSurface`` describes where one agentic tool keeps one artifact: its
``tool`` name, ``kind`` (customization_type), ``location`` (a file path, or a slot
inside a shared keyed-map file), and the ``surface_format`` recipe used to
translate it.

These are declarative value objects with no behaviour yet. ``SurfaceFormat``
carries only its ``dialect`` for now; the translation recipe (known/tool-only
fields, reserved names, rules-filename precedence) grows with its consumers in the
translation (S9) and read-phase (S17) steps, per YAGNI. Every field is hashable,
so a ``ToolSurface`` can be grouped in sets by the planner.
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
    """How a surface is encoded — the dialect that selects its translation."""

    dialect: str


@dataclass(frozen=True)
class ToolSurface:
    """Where one agentic tool keeps one artifact, and how to translate it."""

    tool: str
    kind: str
    location: Path | KeyedMapSlot
    surface_format: SurfaceFormat
