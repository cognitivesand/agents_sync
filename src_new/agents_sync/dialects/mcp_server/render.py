"""mcp_server render — render the canonical onto its keyed-map slot (stdio core, pure).

Builds the slot from the canonical and the tool's recorded field spellings, then reuses
``keyed_map_slot.write_slot`` to reassemble the shared file with siblings preserved. http/sse
is S13c.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agents_sync.dialects import keyed_map_slot
from agents_sync.dialects.mcp_server._shared import (
    _ALWAYS_ALLOW_FIELDS,
    _NAME_FIELD,
    _TRANSPORT_FIELDS,
    _canonical_transport,
)
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import ToolSurface


def render(canonical: CanonicalDocument, tool_surface: ToolSurface, prior_text: str | None) -> str:
    """Render the canonical onto its slot, reassembling the shared file (siblings preserved)."""
    only = canonical.per_tool_only.get(tool_surface.tool, {})
    slot: dict[str, Any] = dict(canonical.per_tool_extra.get(tool_surface.tool, {}))
    if canonical.artifact_id:
        slot[tool_surface.surface_format.id_field] = canonical.artifact_id
    if canonical.name:
        slot[_NAME_FIELD] = canonical.name

    transport = _canonical_transport(canonical.transport)
    if transport != "stdio":
        raise ValueError(f"mcp_server {transport} transport is not yet supported (S13c)")
    slot[_render_transport_field(only)] = _render_transport_value(transport, only)
    _render_stdio(canonical, slot)
    _render_common(canonical, slot, only)
    return keyed_map_slot.write_slot(prior_text, tool_surface, slot)


def _render_transport_field(only: Mapping[str, Any]) -> str:
    """The transport key to emit — this tool's recorded spelling, else the canonical default."""
    spelled = only.get("transport_field")
    return (
        spelled
        if isinstance(spelled, str) and spelled in _TRANSPORT_FIELDS
        else _TRANSPORT_FIELDS[0]
    )


def _render_transport_value(transport: str, only: Mapping[str, Any]) -> str:
    """The value to emit — the tool's original spelling if it still canonicalizes equal."""
    raw = only.get("transport_value")
    if isinstance(raw, str):
        try:
            if _canonical_transport(raw) == transport:
                return raw
        except ValueError:
            pass
    return transport


def _render_stdio(canonical: CanonicalDocument, slot: dict[str, Any]) -> None:
    """Emit the stdio fields back onto ``slot``."""
    if canonical.command is not None:
        slot["command"] = canonical.command
    if canonical.args:
        slot["args"] = list(canonical.args)
    if canonical.env:
        slot["env"] = dict(canonical.env)
    if canonical.cwd is not None:
        slot["cwd"] = canonical.cwd
    if canonical.timeout is not None:
        slot["timeout"] = canonical.timeout


def _render_common(
    canonical: CanonicalDocument, slot: dict[str, Any], only: Mapping[str, Any]
) -> None:
    """Emit the transport-independent fields back onto ``slot``."""
    if canonical.disabled is not None:
        slot["disabled"] = canonical.disabled
    if canonical.always_allow:
        spelled = only.get("always_allow_field")
        field = spelled if isinstance(spelled, str) else _ALWAYS_ALLOW_FIELDS[0]
        slot[field] = list(canonical.always_allow)
