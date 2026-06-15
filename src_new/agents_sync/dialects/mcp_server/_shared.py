"""Shared mcp_server dialect vocabulary — field spellings + transport canonicalization (pure).

The constants and the one canonicalization both ``parse`` and ``render`` reference. Kept in
one place so the field-spelling vocabulary has a single home across the package (no I/O, no
import of any dialect — so it forms no cycle).
"""

from __future__ import annotations

from typing import Any

from agents_sync.domain_model.tool_surface import McpSpellingRecipe, SurfaceFormat

_NAME_FIELD = "name"
_TRANSPORT_FIELDS = ("transport", "type", "transportType")
_URL_FIELDS = ("url", "httpUrl", "serverUrl")
# Per-tool wire quirks (opencode's `environment` env, inverted `enabled`, …) are recipe DATA
# (``McpSpellingRecipe``), read per surface — never module constants or tool-name branches.
# The spellings below are the canonical defaults a tool's recipe overrides (S20 increment 3).
_ALWAYS_ALLOW_FIELDS = ("always_allow", "alwaysAllow", "allowedTools")
_AUTH_FIELDS = ("auth", "oauth")
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
    verbatim in per_tool_extra). ``env``/``disabled`` come from the recipe, so a tool's own
    spellings (opencode ``environment``/``enabled``) are owned by the dialect, not leaked."""
    return frozenset(
        (
            _NAME_FIELD,
            "command",
            "args",
            "cwd",
            "timeout",
            "headers",
            spelling.env_field,
            spelling.disabled_field,
            *_ALWAYS_ALLOW_FIELDS,
            *_AUTH_FIELDS,
            *_TRANSPORT_FIELDS,
            *_URL_FIELDS,
        )
    )


def _canonical_transport(value: Any) -> str:
    """Normalise a transport spelling to its canonical form; raise ``ValueError`` if unknown."""
    raw = str(value)
    normalized = _TRANSPORT_ALIASES.get(raw.casefold(), raw)
    if normalized not in _CANONICAL_TRANSPORTS:
        raise ValueError(f"unsupported mcp_server transport: {raw!r}")
    return normalized
