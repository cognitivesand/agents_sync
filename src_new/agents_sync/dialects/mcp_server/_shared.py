"""Shared mcp_server dialect vocabulary — field spellings, canonicalization, value coercion (pure).

The constants, the transport canonicalization, the env-reference helpers, and the value-shape
coercion that ``parse``, ``render``, and ``_carriers`` all reference. Kept in one place so the
shared vocabulary has a single home across the package (no I/O, no import of a dialect
*submodule* — only the package's shared ``MalformedSurfaceError`` — so it forms no cycle).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from agents_sync.dialects import MalformedSurfaceError
from agents_sync.domain_model.tool_surface import McpSpellingRecipe, SurfaceFormat

_NAME_FIELD = "name"
_TRANSPORT_FIELDS = ("transport", "type", "transportType")
_URL_FIELDS = ("url", "httpUrl", "serverUrl")
# Per-tool wire quirks (opencode's `environment` env, inverted `enabled`, …) are recipe DATA
# (``McpSpellingRecipe``), read per surface — never module constants or tool-name branches.
# The spellings below are the canonical defaults a tool's recipe overrides (S20 increment 3).
_ALWAYS_ALLOW_FIELDS = ("always_allow", "alwaysAllow", "allowedTools")
_AUTH_FIELDS = ("auth", "oauth")
_HEADERS_FIELDS = ("headers", "http_headers")

# Env-reference vocabulary (S20 increments 5, 7). The canonical stores an env-reference in one
# FIXED style, ``${env:NAME}``; each tool's wire uses its own inline ``env_reference_style``
# (claude/gemini ``${NAME}``, opencode ``{env:NAME}``). The dialect canonicalizes any recognized
# form on parse and restyles on render. codex's carriers map a bare env var NAME to/from the
# canonical form. ``_ENV_REFERENCE_TOKEN_PATTERN`` finds an env-ref token (any form) inside a
# larger string (e.g. ``Bearer ${env:TOK}``); the per-form matchers below anchor a whole value.
_ENV_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_ENV_NAME_PATTERN = re.compile(rf"^{_ENV_NAME}$")
_ENV_REFERENCE_PATTERN = re.compile(rf"^\$\{{env:({_ENV_NAME})\}}$")
_BEARER_REFERENCE_PATTERN = re.compile(rf"^Bearer \$\{{env:({_ENV_NAME})\}}$")
_ENV_REFERENCE_TOKEN_PATTERN = re.compile(
    rf"\$\{{env:({_ENV_NAME})\}}|\$\{{({_ENV_NAME})\}}|\{{env:({_ENV_NAME})\}}"
)
_CANONICAL_ENV_STYLE = ("${env:", "}")
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
_DEFAULT_MCP_SPELLING = McpSpellingRecipe()


def _spelling(surface_format: SurfaceFormat) -> McpSpellingRecipe:
    """This surface's mcp spelling recipe, or the canonical defaults when it carries none."""
    return surface_format.mcp_spelling or _DEFAULT_MCP_SPELLING


def _known_slot_fields(spelling: McpSpellingRecipe) -> frozenset[str]:
    """Every slot key the dialect interprets for ``spelling``; anything else is foreign (kept
    verbatim in per_tool_extra). ``env``/``disabled`` and the http carriers come from the
    recipe, so a tool's own spellings (opencode ``environment``/``enabled``, codex
    ``env_http_headers``/``bearer_token_env_var``) are owned by the dialect, not leaked."""
    return frozenset(
        (
            _NAME_FIELD,
            "command",
            "args",
            "cwd",
            "timeout",
            spelling.env_field,
            spelling.disabled_field,
            *_ALWAYS_ALLOW_FIELDS,
            *_AUTH_FIELDS,
            *_TRANSPORT_FIELDS,
            *_URL_FIELDS,
            *_HEADERS_FIELDS,
            *_carrier_fields(spelling),
        )
    )


def _carrier_fields(spelling: McpSpellingRecipe) -> tuple[str, ...]:
    """The recipe's dedicated http auth carrier fields that are set (codex's, or none)."""
    return tuple(
        field
        for field in (spelling.env_http_headers_field, spelling.bearer_token_env_var_field)
        if field is not None
    )


def _http_only_fields(spelling: McpSpellingRecipe) -> tuple[str, ...]:
    """The fields owned by the http shape alone — a stdio slot declaring one is malformed."""
    return (*_URL_FIELDS, *_HEADERS_FIELDS, *_AUTH_FIELDS, *_carrier_fields(spelling))


def _is_env_var_name(name: str) -> bool:
    """Whether ``name`` is a valid environment-variable name (so it can carry an env ref)."""
    return _ENV_NAME_PATTERN.match(name) is not None


def _env_reference(name: str) -> str:
    """The canonical env-reference form (``${env:NAME}``) for a bare env var name."""
    return f"${{env:{name}}}"


def _env_reference_name(value: Any) -> str | None:
    """The env var name if ``value`` is exactly a canonical ``${env:NAME}`` reference, else None."""
    match = _ENV_REFERENCE_PATTERN.match(value) if isinstance(value, str) else None
    return match.group(1) if match is not None else None


def _bearer_reference_name(value: Any) -> str | None:
    """The env var name if ``value`` is exactly ``Bearer ${env:NAME}``, else None."""
    match = _BEARER_REFERENCE_PATTERN.match(value) if isinstance(value, str) else None
    return match.group(1) if match is not None else None


def _restyle_env_references(value: str, style: tuple[str, str]) -> str:
    """Rewrite every env-reference token in ``value`` to ``(prefix, suffix)`` around its name.

    Recognizes any supported inline form, so it both canonicalizes (style = the canonical
    ``("${env:", "}")``) and renders a tool's native style. Non-reference text is untouched."""
    prefix, suffix = style

    def rewrite(match: re.Match[str]) -> str:
        name = next(group for group in match.groups() if group is not None)
        return f"{prefix}{name}{suffix}"

    return _ENV_REFERENCE_TOKEN_PATTERN.sub(rewrite, value)


def _restyle_env_map(mapping: Mapping[str, str], style: tuple[str, str]) -> dict[str, str]:
    """Apply :func:`_restyle_env_references` to every value of a string→string map."""
    return {key: _restyle_env_references(value, style) for key, value in mapping.items()}


def _first_present(slot: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """The first of ``keys`` present in ``slot`` — the observed spelling of an alias family."""
    for key in keys:
        if key in slot:
            return key
    return None


def _as_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise MalformedSurfaceError(f"mcp_server {field_name} must be a string")
    return value


def _as_string_map(value: Any, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise MalformedSurfaceError(f"mcp_server {field_name} must be an object")
    return {str(key): _as_string(item, f"{field_name} value") for key, item in value.items()}


def _canonical_transport(value: Any) -> str:
    """Normalise a transport spelling to its canonical form; raise ``ValueError`` if unknown."""
    raw = str(value)
    normalized = _TRANSPORT_ALIASES.get(raw.casefold(), raw)
    if normalized not in _CANONICAL_TRANSPORTS:
        raise ValueError(f"unsupported mcp_server transport: {raw!r}")
    return normalized
