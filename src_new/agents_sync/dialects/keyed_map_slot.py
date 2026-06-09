"""The keyed-map-slot dialect — one slot inside a shared structured-text file (pure).

An MCP-server artifact is not its own file: many artifacts share one file, each owning
one entry in a keyed map nested at the recipe's ``map_key_path`` (e.g. ``mcpServers``).
This dialect translates the one slot named by ``location.slot``:

- ``parse`` — navigate the shared-file ``text`` to the slot, then apply the shared
  recipe-application (``field_mapping``) exactly as the markdown dialect does (a slot
  has no body, so the fold leaves the canonical's body untouched).
- ``render`` — reassemble the whole shared file from ``prior_text`` with only this one
  slot replaced; sibling slots and out-of-map keys are preserved verbatim.
- ``extract_id`` — read the slot's id field in isolation; never raises (FR-11).

Pure: operates on the shared file's ``text: str`` and does no I/O — the read, the
cross-process lock, and the atomic write are the executor's job (S19). S10 supports the
``json`` file format; TOML/JSONC arrive with the structured-text codec at S11, so an
unimplemented format fails loud (a recipe error, distinct from malformed content).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agents_sync.dialects import MalformedSurfaceError, structured_text
from agents_sync.dialects.field_mapping import (
    fold_fields_into_canonical,
    project_canonical_to_fields,
)
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import KeyedMapSlot, ToolSurface


def parse(
    text: str,
    tool_surface: ToolSurface,
    prior_canonical: CanonicalDocument | None,
) -> CanonicalDocument:
    """Fold this surface's slot into the canonical document (raises if the file is malformed)."""
    slot = read_slot(text, tool_surface)
    return fold_fields_into_canonical(slot, tool_surface, prior_canonical, body=None)


def render(
    canonical: CanonicalDocument,
    tool_surface: ToolSurface,
    prior_text: str | None,
) -> str:
    """Reassemble the shared file from ``prior_text`` with only this slot replaced."""
    slot = project_canonical_to_fields(canonical, tool_surface)
    return write_slot(prior_text, tool_surface, slot)


def extract_id(text: str, tool_surface: ToolSurface) -> str | None:
    """Return the slot's embedded id; never raises on malformed text (FR-11).

    Malformed shared-file content yields ``None``; an unsupported ``file_format`` is a
    recipe error, not malformed content, so it still fails loud (as everywhere else).
    """
    try:
        slot = read_slot(text, tool_surface)
    except MalformedSurfaceError:
        return None
    value = slot.get(tool_surface.surface_format.id_field)
    return value if isinstance(value, str) and value else None


def read_slot(text: str, tool_surface: ToolSurface) -> dict[str, Any]:
    """Navigate the shared file to this surface's slot; ``{}`` if file/path/slot is absent.

    The shared keyed-map-file read, used by this dialect's fold and by the ``mcp_server``
    dialect (which interprets the slot fields itself rather than via the flat recipe)."""
    surface_format = tool_surface.surface_format
    node: Any = structured_text.deserialize(text, surface_format.file_format)
    for key in surface_format.map_key_path:
        if not isinstance(node, dict) or key not in node:
            return {}
        node = node[key]
    if not isinstance(node, dict):
        return {}
    slot = node.get(_slot_key(tool_surface))
    return slot if isinstance(slot, dict) else {}


def write_slot(
    prior_text: str | None, tool_surface: ToolSurface, slot_obj: Mapping[str, Any]
) -> str:
    """Reassemble the shared file from ``prior_text`` with only this surface's slot replaced.

    The shared keyed-map-file write, used by this dialect's render and by the ``mcp_server``
    dialect; sibling slots and out-of-map keys are preserved verbatim."""
    surface_format = tool_surface.surface_format
    root = structured_text.deserialize(prior_text or "", surface_format.file_format)
    slot_map = _navigate_or_create(root, surface_format.map_key_path)
    slot_map[_slot_key(tool_surface)] = dict(slot_obj)
    return structured_text.serialize(root, surface_format.file_format)


def _navigate_or_create(root: dict[str, Any], map_key_path: tuple[str, ...]) -> dict[str, Any]:
    """Walk ``map_key_path``, creating empty objects for missing or non-object segments.

    A non-dict value at a map segment cannot hold sibling slots, so replacing it with an
    empty object loses no artifact data — it self-heals a structurally-broken shared file
    so the managed slot can still be written (the dict case preserves every sibling).
    """
    node = root
    for key in map_key_path:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    return node


def _slot_key(tool_surface: ToolSurface) -> str:
    """The slot key for this surface — the leaf of its keyed-map location (fail-loud)."""
    location = tool_surface.location
    if not isinstance(location, KeyedMapSlot):
        raise ValueError(
            f"keyed_map_slot surface needs a KeyedMapSlot location, got {type(location).__name__}"
        )
    return location.slot
