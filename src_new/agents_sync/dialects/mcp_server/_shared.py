"""Shared mcp_server dialect vocabulary — field spellings + transport canonicalization (pure).

The constants and the one canonicalization both ``parse`` and ``render`` reference. Kept in
one place so the field-spelling vocabulary has a single home across the package (no I/O, no
import of any dialect — so it forms no cycle).
"""

from __future__ import annotations

from typing import Any

_NAME_FIELD = "name"
_TRANSPORT_FIELDS = ("transport", "type", "transportType")
_URL_FIELDS = ("url", "httpUrl", "serverUrl")
# NOTE for S20 (per-tool spellings are recipe data): opencode spells `env` as `environment`,
# and spells the disabled flag `enabled` with INVERTED polarity (enabled = not disabled) —
# wire semantics, not plain aliases. Until then those keys fall through to per_tool_extra and
# round-trip verbatim; the dialect's defaults are the single spellings `env` / `disabled`.
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
# Every slot key the dialect interprets; anything else is foreign (kept in per_tool_extra).
_FIXED_KNOWN_FIELDS = (
    _NAME_FIELD,
    "command",
    "args",
    "cwd",
    "timeout",
    "env",
    "disabled",
    "headers",
    *_ALWAYS_ALLOW_FIELDS,
    *_AUTH_FIELDS,
    *_TRANSPORT_FIELDS,
    *_URL_FIELDS,
)


def _canonical_transport(value: Any) -> str:
    """Normalise a transport spelling to its canonical form; raise ``ValueError`` if unknown."""
    raw = str(value)
    normalized = _TRANSPORT_ALIASES.get(raw.casefold(), raw)
    if normalized not in _CANONICAL_TRANSPORTS:
        raise ValueError(f"unsupported mcp_server transport: {raw!r}")
    return normalized
