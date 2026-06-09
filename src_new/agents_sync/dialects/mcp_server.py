"""The mcp_server dialect — stdio core (pure, no I/O).

An mcp_server artifact is one slot in a shared keyed-map file, so this dialect reuses
``keyed_map_slot``'s ``read_slot`` / ``write_slot`` for the navigate-and-reassemble
(sibling preservation) and adds the wire interpretation a flat field map cannot express:
transport canonicalization + an alias map (``local``→``stdio``), transport inference
(``command``→stdio), the stdio fields (``command``/``args`` with array-form split, ``env``,
``cwd``, ``timeout``, ``disabled``, ``always_allow``), and preservation of each tool's own
field spelling under ``per_tool_only`` (unknown keys under ``per_tool_extra``).

The mcp fields are *reset* on each parse (a slot is the whole server definition, so an
omitted field clears rather than carrying a stale prior value). http/sse transport and the
url/headers/auth fields are S13b; the mcp secret policy runs in the read phase (S18). The
default field-spelling lists are module constants here — per-tool overrides become recipe
data when tools become data (S20).

Size note (§3 derogation): ~330 lines, modestly over the 300 guideline — one cohesive
dialect, every function under 40 lines. It splits into a package (parse / render, as the
reference does) at S13b, when http + headers/auth are added and the single module would
genuinely exceed the limit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from agents_sync.dialects import MalformedSurfaceError, keyed_map_slot
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import ToolSurface

_NAME_FIELD = "name"
_TRANSPORT_FIELDS = ("transport", "type", "transportType")
_URL_FIELDS = ("url", "httpUrl", "serverUrl")
_ENV_FIELDS = ("env",)
# NOTE for S20 (per-tool spellings): opencode (a stdio tool) spells this `enabled`, whose
# polarity is INVERTED (enabled = not disabled) — model it as wire semantics, not a plain
# alias. Until then an `enabled` key falls through to per_tool_extra and round-trips verbatim.
_DISABLED_FIELDS = ("disabled",)
_ALWAYS_ALLOW_FIELDS = ("always_allow", "alwaysAllow", "allowedTools")
_CANONICAL_TRANSPORTS = frozenset({"stdio", "http", "sse", "streamable-http"})
# alias (casefolded) → canonical transport; an alias not here passes through to be
# validated against _CANONICAL_TRANSPORTS, so an unknown value is rejected.
_TRANSPORT_ALIASES = {
    "stdio": "stdio",
    "local": "stdio",
    "http": "http",
    "remote": "http",
    "sse": "sse",
    "streamable-http": "streamable-http",
    "streamable_http": "streamable-http",
    "streamablehttp": "streamable-http",
}
# Every slot key the dialect interprets; anything else is foreign (kept in per_tool_extra).
_FIXED_KNOWN_FIELDS = (
    _NAME_FIELD,
    "command",
    "args",
    "cwd",
    "timeout",
    *_ENV_FIELDS,
    *_DISABLED_FIELDS,
    *_ALWAYS_ALLOW_FIELDS,
    *_TRANSPORT_FIELDS,
    *_URL_FIELDS,
)


def parse(
    text: str,
    tool_surface: ToolSurface,
    prior_canonical: CanonicalDocument | None,
) -> CanonicalDocument:
    """Fold one mcp_server slot into the canonical document (raises if malformed)."""
    slot = keyed_map_slot.read_slot(text, tool_surface)
    transport, transport_field = _detect_transport(slot)
    if transport != "stdio":
        raise ValueError(f"mcp_server {transport} transport is not yet supported (S13b)")

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
        raise ValueError(f"mcp_server {transport} transport is not yet supported (S13b)")
    slot[_render_transport_field(only)] = _render_transport_value(transport, only)
    _render_stdio(canonical, slot, only)
    _render_common(canonical, slot, only)
    return keyed_map_slot.write_slot(prior_text, tool_surface, slot)


def extract_id(text: str, tool_surface: ToolSurface) -> str | None:
    """Return the slot's embedded id; never raises on malformed text (FR-11).

    The id is the slot's ``id_field`` like any keyed-map slot, so the read delegates."""
    return keyed_map_slot.extract_id(text, tool_surface)


# --- parse helpers -------------------------------------------------------------


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


def _canonical_transport(value: Any) -> str:
    """Normalise a transport spelling to its canonical form; raise ``ValueError`` if unknown."""
    raw = str(value)
    normalized = _TRANSPORT_ALIASES.get(raw.casefold(), raw)
    if normalized not in _CANONICAL_TRANSPORTS:
        raise ValueError(f"unsupported mcp_server transport: {raw!r}")
    return normalized


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
    env_field = _first_present(slot, _ENV_FIELDS)
    if env_field is not None:
        env = _as_mapping(slot[env_field], env_field)
        changes["env"] = {str(key): str(value) for key, value in env.items()}
    if "cwd" in slot:
        changes["cwd"] = str(slot["cwd"])
    if "timeout" in slot:
        changes["timeout"] = slot["timeout"]


def _fold_common(slot: dict[str, Any], changes: dict[str, Any]) -> None:
    """Fold the transport-independent fields (disabled, always_allow) onto ``changes``."""
    disabled_field = _first_present(slot, _DISABLED_FIELDS)
    if disabled_field is not None:
        changes["disabled"] = bool(slot[disabled_field])
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
    _record_alias(result, "env_field", _first_present(slot, _ENV_FIELDS), _ENV_FIELDS[0])
    _record_alias(
        result, "disabled_field", _first_present(slot, _DISABLED_FIELDS), _DISABLED_FIELDS[0]
    )
    _record_alias(
        result,
        "always_allow_field",
        _first_present(slot, _ALWAYS_ALLOW_FIELDS),
        _ALWAYS_ALLOW_FIELDS[0],
    )
    return result


def _record_alias(result: dict[str, Any], key: str, used: str | None, default: str) -> None:
    """Record a field spelling under ``key`` only when a non-default alias was used."""
    if used is not None and used != default:
        result[key] = used


def _foreign_keys(slot: dict[str, Any], id_field: str) -> dict[str, Any]:
    """Slot keys the dialect does not own — kept verbatim under per_tool_extra (no-foreign-leak)."""
    known = {id_field, *_FIXED_KNOWN_FIELDS}
    return {key: value for key, value in slot.items() if key not in known}


# --- render helpers ------------------------------------------------------------


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


def _render_stdio(
    canonical: CanonicalDocument, slot: dict[str, Any], only: Mapping[str, Any]
) -> None:
    """Emit the stdio fields back onto ``slot``."""
    if canonical.command is not None:
        slot["command"] = canonical.command
    if canonical.args:
        slot["args"] = list(canonical.args)
    if canonical.env:
        slot[_spelled_or_default(only, "env_field", _ENV_FIELDS[0])] = dict(canonical.env)
    if canonical.cwd is not None:
        slot["cwd"] = canonical.cwd
    if canonical.timeout is not None:
        slot["timeout"] = canonical.timeout


def _render_common(
    canonical: CanonicalDocument, slot: dict[str, Any], only: Mapping[str, Any]
) -> None:
    """Emit the transport-independent fields back onto ``slot``."""
    if canonical.disabled is not None:
        slot[_spelled_or_default(only, "disabled_field", _DISABLED_FIELDS[0])] = canonical.disabled
    if canonical.always_allow:
        field = _spelled_or_default(only, "always_allow_field", _ALWAYS_ALLOW_FIELDS[0])
        slot[field] = list(canonical.always_allow)


# --- small shared utilities ----------------------------------------------------


def _spelled_or_default(only: Mapping[str, Any], key: str, default: str) -> str:
    spelled = only.get(key)
    return spelled if isinstance(spelled, str) else default


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


def _as_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MalformedSurfaceError(f"mcp_server {field_name} must be an object")
    return value


def _recover_id(slot: dict[str, Any], id_field: str, base: CanonicalDocument) -> str:
    embedded = slot.get(id_field)
    return embedded if isinstance(embedded, str) and embedded else base.artifact_id


def _with_tool_slot(bags: Any, tool: str, slot: dict[str, Any]) -> dict[str, Any]:
    # Mirrors field_mapping's per-tool-bag merge (replace this tool's bag, keep the others);
    # inlined per Rule of Three — extract a shared helper if a third dialect needs it.
    merged = dict(bags)
    if slot:
        merged[tool] = dict(slot)
    else:
        merged.pop(tool, None)
    return merged
