"""mcp_server parse — fold one keyed-map slot into the canonical document (stdio core, pure).

Reuses ``keyed_map_slot.read_slot`` for the navigate, then adds the wire interpretation:
transport canonicalization + inference, the stdio fields (command/args with array-form split,
env, cwd, timeout, disabled, always_allow), per-tool field-spelling preservation, and the
no-foreign-leak of unknown keys. The mcp fields are *reset* on each parse (a slot is the whole
server definition, so an omitted field clears, never carries a stale prior). http/sse is S13c.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from agents_sync.dialects import MalformedSurfaceError, keyed_map_slot
from agents_sync.dialects.mcp_server._shared import (
    _ALWAYS_ALLOW_FIELDS,
    _FIXED_KNOWN_FIELDS,
    _NAME_FIELD,
    _TRANSPORT_FIELDS,
    _URL_FIELDS,
    _canonical_transport,
)
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import ToolSurface


def parse(
    text: str,
    tool_surface: ToolSurface,
    prior_canonical: CanonicalDocument | None,
) -> CanonicalDocument:
    """Fold one mcp_server slot into the canonical document (raises if malformed)."""
    slot = keyed_map_slot.read_slot(text, tool_surface)
    transport, transport_field = _detect_transport(slot)
    if transport != "stdio":
        raise ValueError(f"mcp_server {transport} transport is not yet supported (S13c)")

    base = prior_canonical or CanonicalDocument(artifact_id="", kind=tool_surface.kind)
    id_field = tool_surface.surface_format.id_field
    changes: dict[str, Any] = {
        "artifact_id": _recover_id(slot, id_field, base),
        "kind": tool_surface.kind,
        "transport": transport,
        # reset all mcp fields: an omitted slot field clears, never carries a stale prior.
        "command": None,
        "args": (),
        "env": {},
        "cwd": None,
        "timeout": None,
        "disabled": None,
        "always_allow": (),
    }
    name = slot.get(_NAME_FIELD)
    if isinstance(name, str):
        changes["name"] = name
    _fold_stdio(slot, changes)
    _fold_common(slot, changes)
    tool = tool_surface.tool
    changes["per_tool_only"] = _with_tool_slot(
        base.per_tool_only, tool, _spellings(slot, transport_field)
    )
    changes["per_tool_extra"] = _with_tool_slot(
        base.per_tool_extra, tool, _foreign_keys(slot, id_field)
    )
    return replace(base, **changes)


def extract_id(text: str, tool_surface: ToolSurface) -> str | None:
    """Return the slot's embedded id; never raises on malformed text (FR-11).

    The id is the slot's ``id_field`` like any keyed-map slot, so the read delegates."""
    return keyed_map_slot.extract_id(text, tool_surface)


def _detect_transport(slot: dict[str, Any]) -> tuple[str, str | None]:
    """Return ``(canonical_transport, the_field_it_came_from)``; infer from command/url.

    The field is ``None`` when the transport was inferred rather than read from a key."""
    for field in _TRANSPORT_FIELDS:
        if field in slot:
            return _canonical_or_malformed(slot[field]), field
    if "command" in slot:
        return "stdio", None
    if any(field in slot for field in _URL_FIELDS):
        return "http", None
    raise MalformedSurfaceError("mcp_server slot must declare a transport, command, or url")


def _canonical_or_malformed(value: Any) -> str:
    """Canonicalize a wire transport value; a bad value is malformed content, not a recipe error."""
    try:
        return _canonical_transport(value)
    except ValueError as error:
        raise MalformedSurfaceError(str(error)) from error


def _fold_stdio(slot: dict[str, Any], changes: dict[str, Any]) -> None:
    """Fold the stdio fields (command/args/env/cwd/timeout) onto ``changes``."""
    command = slot.get("command")
    if command is None:
        raise MalformedSurfaceError("stdio mcp_server requires a command")
    if isinstance(command, list):
        parts = [str(part) for part in command]
        if not parts:
            raise MalformedSurfaceError("stdio mcp_server command array must not be empty")
        changes["command"] = parts[0]
        changes["args"] = tuple(parts[1:])
    else:
        changes["command"] = str(command)
        if "args" in slot:
            changes["args"] = tuple(str(arg) for arg in _as_list(slot["args"]))
    if "env" in slot:
        env = slot["env"]
        if not isinstance(env, dict):
            raise MalformedSurfaceError("mcp_server env must be an object")
        changes["env"] = {str(key): str(value) for key, value in env.items()}
    if "cwd" in slot:
        changes["cwd"] = str(slot["cwd"])
    if "timeout" in slot:
        changes["timeout"] = slot["timeout"]


def _fold_common(slot: dict[str, Any], changes: dict[str, Any]) -> None:
    """Fold the transport-independent fields (disabled, always_allow) onto ``changes``."""
    if "disabled" in slot:
        changes["disabled"] = bool(slot["disabled"])
    always_allow_field = _first_present(slot, _ALWAYS_ALLOW_FIELDS)
    if always_allow_field is not None:
        value = slot[always_allow_field]
        items = value if isinstance(value, list) else [value]
        changes["always_allow"] = tuple(str(item) for item in items)


def _spellings(slot: dict[str, Any], transport_field: str | None) -> dict[str, Any]:
    """Record this tool's own field spellings (only where they differ from the default)."""
    result: dict[str, Any] = {}
    if transport_field is not None:
        result["transport_field"] = transport_field
        result["transport_value"] = slot.get(transport_field)
    always_allow_field = _first_present(slot, _ALWAYS_ALLOW_FIELDS)
    if always_allow_field is not None and always_allow_field != _ALWAYS_ALLOW_FIELDS[0]:
        result["always_allow_field"] = always_allow_field
    return result


def _foreign_keys(slot: dict[str, Any], id_field: str) -> dict[str, Any]:
    """Slot keys the dialect does not own — kept verbatim under per_tool_extra (no-foreign-leak)."""
    known = {id_field, *_FIXED_KNOWN_FIELDS}
    return {key: value for key, value in slot.items() if key not in known}


def _first_present(slot: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key in slot:
            return key
    return None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    raise MalformedSurfaceError("mcp_server args must be a list or string")


def _recover_id(slot: dict[str, Any], id_field: str, base: CanonicalDocument) -> str:
    embedded = slot.get(id_field)
    return embedded if isinstance(embedded, str) and embedded else base.artifact_id


def _with_tool_slot(
    bags: Mapping[str, Mapping[str, Any]], tool: str, slot: dict[str, Any]
) -> dict[str, Any]:
    # Mirrors field_mapping's per-tool-bag merge (replace this tool's bag, keep the others);
    # inlined per Rule of Three — extract a shared helper if a third dialect needs it.
    merged = dict(bags)
    if slot:
        merged[tool] = dict(slot)
    else:
        merged.pop(tool, None)
    return merged
