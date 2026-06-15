"""mcp_server render — render the canonical onto its keyed-map slot (pure).

Builds the slot from the canonical and the tool's recorded field spellings (stdio and
http/sse shapes), then reuses ``keyed_map_slot.write_slot`` to reassemble the shared file
with siblings preserved.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agents_sync.dialects import keyed_map_slot
from agents_sync.dialects.mcp_server._carriers import split_headers
from agents_sync.dialects.mcp_server._shared import (
    _ALWAYS_ALLOW_FIELDS,
    _AUTH_FIELDS,
    _HEADERS_FIELDS,
    _TRANSPORT_FIELDS,
    _URL_FIELDS,
    _canonical_transport,
    _spelling,
)
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import McpSpellingRecipe, ToolSurface


def render(canonical: CanonicalDocument, tool_surface: ToolSurface, prior_text: str | None) -> str:
    """Render the canonical onto its slot, reassembling the shared file (siblings preserved)."""
    spelling = _spelling(tool_surface.surface_format)
    only = canonical.per_tool_only.get(tool_surface.tool, {})
    # to_dict() deep-thaws the per-tool bag: a foreign nested object is frozen to a
    # mappingproxy that json.dumps cannot serialize (the markdown dialect thaws the same way).
    slot: dict[str, Any] = dict(canonical.to_dict()["per_tool_extra"].get(tool_surface.tool, {}))
    if canonical.artifact_id:
        slot[tool_surface.surface_format.id_field] = canonical.artifact_id
    if canonical.name and spelling.name_render_field is not None:
        slot[spelling.name_render_field] = canonical.name

    transport = _canonical_transport(canonical.transport)
    if spelling.transport_render_field is not None:
        # A transport-field-less tool (gemini/codex) infers the transport from command/url
        # on re-parse, so emitting it would be a spurious field, not a faithful projection.
        field = _spelled_field(
            only, "transport_field", _TRANSPORT_FIELDS, spelling.transport_render_field
        )
        slot[field] = _render_transport_value(transport, only, spelling)
    if transport == "stdio":
        _render_stdio(canonical, slot, only, spelling)
    else:
        _render_http(canonical, slot, only, spelling, transport)
    _render_common(canonical, slot, only, spelling)
    return keyed_map_slot.write_slot(prior_text, tool_surface, slot)


def _spelled_field(
    only: Mapping[str, Any], key: str, allowed: tuple[str, ...], preferred: str = ""
) -> str:
    """The key to emit — this tool's observed spelling if valid, else the recipe's preferred
    spelling if valid (a fresh projection has no observation), else the canonical default."""
    spelled = only.get(key)
    if isinstance(spelled, str) and spelled in allowed:
        return spelled
    return preferred if preferred in allowed else allowed[0]


def _render_transport_value(
    transport: str, only: Mapping[str, Any], spelling: McpSpellingRecipe
) -> str:
    """The value to emit — the tool's observed spelling if it still canonicalizes equal, else
    the recipe's wire value for this transport (opencode: ``stdio``→``local``), else the
    canonical transport itself."""
    raw = only.get("transport_value")
    if isinstance(raw, str):
        try:
            if _canonical_transport(raw) == transport:
                return raw
        except ValueError:
            pass
    return dict(spelling.transport_render_values).get(transport, transport)


def _render_stdio(
    canonical: CanonicalDocument,
    slot: dict[str, Any],
    only: Mapping[str, Any],
    spelling: McpSpellingRecipe,
) -> None:
    """Emit the stdio fields back onto ``slot`` (env under the tool's own spelling)."""
    as_array = only.get("command_array") is True or spelling.command_mode == "array"
    if as_array and canonical.command is not None:
        # the tool spells the invocation as one array: give that shape back, no args key.
        slot["command"] = [canonical.command, *canonical.args]
    else:
        if canonical.command is not None:
            slot["command"] = canonical.command
        if canonical.args:
            slot["args"] = list(canonical.args)
    if canonical.env:
        slot[spelling.env_field] = dict(canonical.env)
    if canonical.cwd is not None:
        slot["cwd"] = canonical.cwd


def _render_http(
    canonical: CanonicalDocument,
    slot: dict[str, Any],
    only: Mapping[str, Any],
    spelling: McpSpellingRecipe,
    transport: str,
) -> None:
    """Emit the http/sse fields (url, headers + carriers, auth) back onto ``slot``.

    The url-field spelling may itself encode the transport (gemini renders ``httpUrl`` for
    http, ``url`` for sse — ``url_field_by_transport``); an observed spelling still wins."""
    if canonical.url is not None:
        preferred = dict(spelling.url_field_by_transport).get(transport, "")
        slot[_spelled_field(only, "url_field", _URL_FIELDS, preferred)] = canonical.url
    _render_headers(canonical, slot, only, spelling)
    if canonical.auth and spelling.auth_render_field is not None:
        field = _spelled_field(only, "auth_field", _AUTH_FIELDS, spelling.auth_render_field)
        slot[field] = dict(canonical.auth)


def _render_headers(
    canonical: CanonicalDocument,
    slot: dict[str, Any],
    only: Mapping[str, Any],
    spelling: McpSpellingRecipe,
) -> None:
    """Emit canonical headers: env-reference headers lift into the recipe's dedicated carriers,
    the literal remainder stays under the (possibly tool-spelled) headers field."""
    if not canonical.headers:
        return
    literal, carriers = split_headers(canonical.headers, spelling)
    slot.update(carriers)
    if literal:
        spelled = _spelled_field(
            only, "headers_field", _HEADERS_FIELDS, spelling.headers_render_field
        )
        slot[spelled] = literal


def _render_common(
    canonical: CanonicalDocument,
    slot: dict[str, Any],
    only: Mapping[str, Any],
    spelling: McpSpellingRecipe,
) -> None:
    """Emit the transport-independent fields (disabled under the tool's own flag spelling)."""
    if canonical.timeout is not None:
        slot["timeout"] = canonical.timeout
    if canonical.disabled is not None:
        flag = (not canonical.disabled) if spelling.disabled_inverted else canonical.disabled
        slot[spelling.disabled_field] = flag
    if canonical.always_allow:
        field = _spelled_field(only, "always_allow_field", _ALWAYS_ALLOW_FIELDS)
        slot[field] = list(canonical.always_allow)
