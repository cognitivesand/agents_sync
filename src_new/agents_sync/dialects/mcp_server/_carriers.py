"""Codex's mcp http auth carriers — the one place the carrier transform lives (pure, no I/O).

Codex spells HTTP authentication across dedicated carrier fields rather than a generic
``headers``/``auth`` block: ``http_headers`` (literal values), ``env_http_headers``
(header→env-name), and ``bearer_token_env_var`` (one env-name → an ``Authorization: Bearer``
header). :func:`fold_headers` collapses all three onto one canonical ``headers`` map (the parse
half); :func:`split_headers` lifts the env-reference entries back out (the render half). Both
sides use the FIXED canonical ``${env:NAME}`` representation — the per-tool inline *style* is
S20 increment 7. A tool whose recipe declares no carrier leaves env-reference headers inline.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agents_sync.dialects import MalformedSurfaceError
from agents_sync.dialects.mcp_server._shared import (
    _HEADERS_FIELDS,
    _as_string,
    _as_string_map,
    _bearer_reference_name,
    _env_reference,
    _env_reference_name,
    _first_present,
    _is_env_var_name,
)
from agents_sync.domain_model.tool_surface import McpSpellingRecipe


def fold_headers(slot: dict[str, Any], spelling: McpSpellingRecipe) -> dict[str, str]:
    """One canonical headers map from a plain headers field plus codex's dedicated carriers.

    ``http_headers`` literals stay verbatim; an ``env_http_headers`` entry (header→env-name)
    and a ``bearer_token_env_var`` (one env-name) are wrapped into canonical ``${env:NAME}``
    references — a value that is not a valid env var name is malformed content (§8)."""
    headers: dict[str, str] = {}
    headers_field = _first_present(slot, _HEADERS_FIELDS)
    if headers_field is not None:
        headers.update(_as_string_map(slot[headers_field], headers_field))
    env_field = spelling.env_http_headers_field
    if env_field is not None and env_field in slot:
        for header, name in _as_string_map(slot[env_field], env_field).items():
            headers[header] = _carrier_reference(name, env_field)
    bearer_field = spelling.bearer_token_env_var_field
    if bearer_field is not None and bearer_field in slot:
        name = _as_string(slot[bearer_field], bearer_field)
        headers["Authorization"] = f"Bearer {_carrier_reference(name, bearer_field)}"
    return headers


def split_headers(
    headers: Mapping[str, str], spelling: McpSpellingRecipe
) -> tuple[dict[str, str], dict[str, Any]]:
    """Split canonical headers into ``(literal remainder, carrier fields to emit)``.

    A ``Bearer ${env:NAME}`` Authorization and every whole-value ``${env:NAME}`` header lift
    into the recipe's dedicated carriers (when declared); literal headers stay in the
    remainder. No carrier declared → the remainder is the headers unchanged."""
    literal = dict(headers)
    carriers: dict[str, Any] = {}
    bearer_field = spelling.bearer_token_env_var_field
    if bearer_field is not None:
        name = _bearer_reference_name(literal.get("Authorization"))
        if name is not None:
            carriers[bearer_field] = name
            literal.pop("Authorization")
    env_field = spelling.env_http_headers_field
    if env_field is not None:
        env_headers: dict[str, str] = {}
        for header, value in list(literal.items()):
            name = _env_reference_name(value)
            if name is not None:
                env_headers[header] = name
                literal.pop(header)
        if env_headers:
            carriers[env_field] = env_headers
    return literal, carriers


def _carrier_reference(name: str, field: str) -> str:
    """Wrap a carrier's bare env var name as a canonical env reference (raises if malformed)."""
    if not _is_env_var_name(name):
        raise MalformedSurfaceError(f"mcp_server {field} is not a valid env var name: {name!r}")
    return _env_reference(name)
