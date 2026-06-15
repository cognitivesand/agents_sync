"""mcp_server parse — fold one keyed-map slot into the canonical document (pure).

Reuses ``keyed_map_slot.read_slot`` for the navigate, then adds the wire interpretation:
transport canonicalization + inference, the stdio fields (command/args with array-form split,
env, cwd), the http/sse fields (url with alias detection, verbatim headers/auth maps), the
transport-independent fields (timeout, disabled, always_allow), per-tool field-spelling
preservation, and the no-foreign-leak of unknown keys. The mcp fields are *reset* on each
parse (a slot is the whole server definition, so an omitted field clears, never carries a
stale prior). A slot mixing the two transport shapes fails loud as malformed content.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from agents_sync.dialects import MalformedSurfaceError, keyed_map_slot
from agents_sync.dialects.mcp_server._shared import (
    _ALWAYS_ALLOW_FIELDS,
    _AUTH_FIELDS,
    _NAME_FIELD,
    _TRANSPORT_FIELDS,
    _URL_FIELDS,
    _canonical_transport,
    _known_slot_fields,
    _spelling,
)
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import McpSpellingRecipe, ToolSurface

# The fields owned by exactly one transport shape: a slot declaring fields from the OTHER
# shape describes two conflicting servers at once — malformed content, never silently halved.
# The env spelling is per-tool (recipe data), so it is added to the stdio-only set per parse.
_STDIO_ONLY_FIELDS = ("command", "args", "cwd")
_HTTP_ONLY_FIELDS = (*_URL_FIELDS, "headers", *_AUTH_FIELDS)
# The alias families where one field accepts several spellings: a slot using two spellings
# of one family declares the field twice — the same conflict, the same fail-loud answer.
_ALIAS_FAMILIES = (_TRANSPORT_FIELDS, _URL_FIELDS, _AUTH_FIELDS, _ALWAYS_ALLOW_FIELDS)


def parse(
    text: str,
    tool_surface: ToolSurface,
    prior_canonical: CanonicalDocument | None,
) -> CanonicalDocument:
    """Fold one mcp_server slot into the canonical document (raises if malformed)."""
    slot = keyed_map_slot.read_slot(text, tool_surface)
    spelling = _spelling(tool_surface.surface_format)
    _reject_duplicate_aliases(slot)
    transport, transport_field = _detect_transport(slot)
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
        "url": None,
        "headers": {},
        "auth": {},
    }
    name = slot.get(_NAME_FIELD)
    if isinstance(name, str):
        changes["name"] = name
    if transport == "stdio":
        _fold_stdio(slot, changes, spelling)
    else:
        _fold_http(slot, changes, transport, spelling)
    _fold_common(slot, changes, spelling)
    tool = tool_surface.tool
    changes["per_tool_only"] = _with_tool_slot(
        base.per_tool_only, tool, _spellings(slot, transport_field)
    )
    changes["per_tool_extra"] = _with_tool_slot(
        base.per_tool_extra, tool, _foreign_keys(slot, id_field, spelling)
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


def _fold_stdio(slot: dict[str, Any], changes: dict[str, Any], spelling: McpSpellingRecipe) -> None:
    """Fold the stdio fields (command/args/env/cwd) onto ``changes``."""
    _reject_foreign_shape(slot, _HTTP_ONLY_FIELDS, "stdio")
    command = slot.get("command")
    if command is None:
        raise MalformedSurfaceError("stdio mcp_server requires a command")
    if isinstance(command, list):
        if "args" in slot:
            # the invocation declared twice in conflicting shapes — folding one and silently
            # dropping the other would mangle the user's file on round-trip.
            raise MalformedSurfaceError("mcp_server command array and args must not coexist")
        parts = [_as_string(part, "command array item") for part in command]
        if not parts:
            raise MalformedSurfaceError("stdio mcp_server command array must not be empty")
        changes["command"] = parts[0]
        changes["args"] = tuple(parts[1:])
    else:
        changes["command"] = _as_string(command, "command")
        if "args" in slot:
            changes["args"] = tuple(_as_string(arg, "args item") for arg in _as_list(slot["args"]))
    if spelling.env_field in slot:
        changes["env"] = _as_string_map(slot[spelling.env_field], "env")
    if "cwd" in slot:
        changes["cwd"] = _as_string(slot["cwd"], "cwd")


def _fold_http(
    slot: dict[str, Any], changes: dict[str, Any], transport: str, spelling: McpSpellingRecipe
) -> None:
    """Fold the http/sse fields (url, headers, auth — verbatim maps) onto ``changes``."""
    _reject_foreign_shape(slot, (*_STDIO_ONLY_FIELDS, spelling.env_field), transport)
    url_field = _first_present(slot, _URL_FIELDS)
    if url_field is None:
        raise MalformedSurfaceError(f"{transport} mcp_server requires a url")
    changes["url"] = _as_string(slot[url_field], "url")
    if "headers" in slot:
        changes["headers"] = _as_string_map(slot["headers"], "headers")
    auth_field = _first_present(slot, _AUTH_FIELDS)
    if auth_field is not None:
        changes["auth"] = _as_string_map(slot[auth_field], auth_field)


def _reject_duplicate_aliases(slot: dict[str, Any]) -> None:
    """Two spellings of one alias family declare the field twice — conflicting content:
    folding the first and silently dropping the second would mangle the user's file."""
    for family_fields in _ALIAS_FAMILIES:
        present = [field for field in family_fields if field in slot]
        if len(present) > 1:
            raise MalformedSurfaceError(
                f"mcp_server must not declare both {present[0]!r} and {present[1]!r}"
            )


def _reject_foreign_shape(
    slot: dict[str, Any], foreign_fields: tuple[str, ...], transport: str
) -> None:
    """A slot declaring fields of the other transport shape is conflicting content: folding
    one shape and silently dropping the other would mangle the user's file on round-trip."""
    foreign_field = _first_present(slot, foreign_fields)
    if foreign_field is not None:
        raise MalformedSurfaceError(f"{transport} mcp_server must not declare {foreign_field!r}")


def _fold_common(
    slot: dict[str, Any], changes: dict[str, Any], spelling: McpSpellingRecipe
) -> None:
    """Fold the transport-independent fields (timeout, disabled, always_allow).

    ``disabled`` reads the tool's own flag spelling; an inverted flag (opencode's
    ``enabled``) folds to its complement so the canonical always stores ``disabled``."""
    if "timeout" in slot:
        timeout = slot["timeout"]
        # bool is an int subclass; the canonical's ``timeout: int | None`` means a genuine
        # integer, so JSON true/false is malformed, not silently folded to 1/0.
        if not isinstance(timeout, int) or isinstance(timeout, bool):
            raise MalformedSurfaceError("mcp_server timeout must be an integer")
        changes["timeout"] = timeout
    if spelling.disabled_field in slot:
        flag = bool(slot[spelling.disabled_field])
        changes["disabled"] = (not flag) if spelling.disabled_inverted else flag
    always_allow_field = _first_present(slot, _ALWAYS_ALLOW_FIELDS)
    if always_allow_field is not None:
        value = slot[always_allow_field]
        items = value if isinstance(value, list) else [value]
        changes["always_allow"] = tuple(_as_string(item, "always_allow item") for item in items)


def _spellings(slot: dict[str, Any], transport_field: str | None) -> dict[str, Any]:
    """Record this tool's own field spellings (only where they differ from the default)."""
    result: dict[str, Any] = {}
    if transport_field is not None:
        result["transport_field"] = transport_field
        result["transport_value"] = slot.get(transport_field)
    _record_alias(result, "always_allow_field", slot, _ALWAYS_ALLOW_FIELDS)
    _record_alias(result, "url_field", slot, _URL_FIELDS)
    _record_alias(result, "auth_field", slot, _AUTH_FIELDS)
    if isinstance(slot.get("command"), list):
        result["command_array"] = True
    return result


def _record_alias(
    result: dict[str, Any], key: str, slot: dict[str, Any], fields: tuple[str, ...]
) -> None:
    """Record under ``key`` the field spelling used, only when it is a non-default alias."""
    used = _first_present(slot, fields)
    if used is not None and used != fields[0]:
        result[key] = used


def _foreign_keys(
    slot: dict[str, Any], id_field: str, spelling: McpSpellingRecipe
) -> dict[str, Any]:
    """Slot keys the dialect does not own — kept verbatim under per_tool_extra (no-foreign-leak)."""
    known = {id_field, *_known_slot_fields(spelling)}
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


def _as_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise MalformedSurfaceError(f"mcp_server {field_name} must be a string")
    return value


def _as_string_map(value: Any, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise MalformedSurfaceError(f"mcp_server {field_name} must be an object")
    return {str(key): _as_string(item, f"{field_name} value") for key, item in value.items()}


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
