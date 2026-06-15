"""Centralized translation — the single seam between tool bytes and the canonical (§10).

The seam's pure functions convert between a tool's on-disk text and the canonical
document, dispatching on the surface's dialect:

- ``file_to_canonical`` — the one full-parse path; raises ``MalformedSurfaceError`` on
  malformed content (the read phase catches it into a ``ParseFailure``); never mints.
- ``canonical_to_file`` — the one render path; preserves the user's prior formatting.
- ``extract_artifact_id`` — the id in isolation; never raises on malformed text.
- ``remove_surface_content`` / ``surface_fragment_text`` — the executor's removal and
  archive-fragment views of a surface (S19), so it never touches a dialect directly.

Each takes the whole ``ToolSurface`` (not just its ``SurfaceFormat``) because the seam
keys the canonical's per-tool bags by ``tool`` and stamps ``kind`` — neither derivable
from a format shared across tools (the pure core, by contrast, never names a tool,
NFR-11). A dialect mechanism (:mod:`agents_sync.dialects`) is the only place a wire
format is understood; adding one is one registry entry. An unregistered dialect is a
configuration error, so dispatch fails loud — even for ``extract_artifact_id``, whose
"never raises" contract covers malformed *text*, not an unknown dialect.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from agents_sync.dialects import (
    MalformedSurfaceError,
    keyed_map_slot,
    markdown_frontmatter,
    mcp_server,
    structured_text,
)
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import KeyedMapSlot, ToolSurface


@dataclass(frozen=True)
class _Dialect:
    """One wire format's three translation callables."""

    parse: Callable[[str, ToolSurface, CanonicalDocument | None], CanonicalDocument]
    render: Callable[[CanonicalDocument, ToolSurface, str | None], str]
    extract_id: Callable[[str, ToolSurface], str | None]


_DIALECTS: dict[str, _Dialect] = {
    "markdown_frontmatter": _Dialect(
        parse=markdown_frontmatter.parse,
        render=markdown_frontmatter.render,
        extract_id=markdown_frontmatter.extract_id,
    ),
    "keyed_map_slot": _Dialect(
        parse=keyed_map_slot.parse,
        render=keyed_map_slot.render,
        extract_id=keyed_map_slot.extract_id,
    ),
    "structured_text": _Dialect(
        parse=structured_text.parse,
        render=structured_text.render,
        extract_id=structured_text.extract_id,
    ),
    "mcp_server": _Dialect(
        parse=mcp_server.parse,
        render=mcp_server.render,
        extract_id=mcp_server.extract_id,
    ),
}


KNOWN_DIALECTS: frozenset[str] = frozenset(_DIALECTS)
"""The registered dialect names — runtime_config validates every recipe against
this set so a tool naming an unimplemented dialect fails closed at startup."""


def _dialect_for(tool_surface: ToolSurface) -> _Dialect:
    name = tool_surface.surface_format.dialect
    try:
        return _DIALECTS[name]
    except KeyError:
        raise ValueError(f"unknown surface dialect: {name!r}") from None


def file_to_canonical(
    text: str,
    tool_surface: ToolSurface,
    prior_canonical: CanonicalDocument | None,
) -> CanonicalDocument:
    """Parse a tool's text into the canonical document; raise on malformed content."""
    return _dialect_for(tool_surface).parse(text, tool_surface, prior_canonical)


def canonical_to_file(
    canonical: CanonicalDocument,
    tool_surface: ToolSurface,
    prior_text: str | None,
) -> str:
    """Render the canonical onto a tool's text, preserving prior formatting if given."""
    return _dialect_for(tool_surface).render(canonical, tool_surface, prior_text)


def extract_artifact_id(text: str, tool_surface: ToolSurface) -> str | None:
    """Return the embedded id, recovered in isolation; never raises on malformed text."""
    return _dialect_for(tool_surface).extract_id(text, tool_surface)


def remove_surface_content(text: str, tool_surface: ToolSurface) -> str | None:
    """The shared file's text with this surface's slot removed — or ``None`` when the
    surface owns its whole file (the caller deletes the file instead)."""
    if isinstance(tool_surface.location, KeyedMapSlot):
        return keyed_map_slot.remove_slot(text, tool_surface)
    return None


def surface_fragment_text(text: str, tool_surface: ToolSurface) -> str:
    """The bytes this surface owns within ``text`` — the slot's serialization for a
    keyed-map surface (stable JSON, faithful enough for archive recovery), the whole
    text otherwise. What archive-before-write preserves for one surface."""
    if isinstance(tool_surface.location, KeyedMapSlot):
        slot_value = keyed_map_slot.read_slot(text, tool_surface)
        return json.dumps(slot_value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    return text


__all__ = [
    "MalformedSurfaceError",
    "canonical_to_file",
    "extract_artifact_id",
    "file_to_canonical",
    "remove_surface_content",
    "surface_fragment_text",
]
