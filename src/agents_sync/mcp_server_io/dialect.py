"""Per-adapter dialect for JSON MCP server slots.

Tool-specific PRs can pass a dialect that recognizes aliases such as
``type`` / ``transportType`` or ``httpUrl`` without changing the sync core.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PAIR_ID_FIELD = "pair_id"
CANONICAL_TRANSPORTS = frozenset({"stdio", "http", "sse", "streamable-http"})


@dataclass(frozen=True)
class McpServerDialect:
    """Per-adapter spellings for JSON MCP server slots.

    The type-level PR ships the canonical JSON dialect. Tool-specific PRs can
    pass a dialect that recognizes aliases such as ``type``/``transportType``
    or ``httpUrl`` without changing the sync core.
    """

    pair_id_field: str = PAIR_ID_FIELD
    name_field: str = "name"
    render_name_field: bool = True
    transport_fields: tuple[str, ...] = ("transport", "type", "transportType")
    url_fields: tuple[str, ...] = ("url", "httpUrl", "serverUrl")
    headers_fields: tuple[str, ...] = ("headers",)
    headers_render_field: str = "headers"
    env_http_headers_field: str | None = None
    bearer_token_env_var_field: str | None = None
    auth_fields: tuple[str, ...] = ("auth", "oauth")
    auth_render_field: str | None = "auth"
    always_allow_fields: tuple[str, ...] = (
        "always_allow",
        "alwaysAllow",
        "allowedTools",
    )
    command_mode: str = "split"
    env_fields: tuple[str, ...] = ("env",)
    disabled_fields: tuple[str, ...] = ("disabled",)
    render_transport_field: bool = True
    env_reference_style: str = "canonical"
    transport_aliases: tuple[tuple[str, str], ...] = (
        ("stdio", "stdio"),
        ("local", "stdio"),
        ("http", "http"),
        ("remote", "http"),
        ("sse", "sse"),
        ("streamable-http", "streamable-http"),
        ("streamable_http", "streamable-http"),
        ("streamableHttp", "streamable-http"),
    )
    transport_render_values: tuple[tuple[str, str], ...] = ()

    def canonical_transport(self, value: Any) -> str:
        raw = str(value)
        aliases = {alias.casefold(): canonical for alias, canonical in self.transport_aliases}
        normalized = aliases.get(raw.casefold(), raw)
        if normalized not in CANONICAL_TRANSPORTS:
            raise ValueError(f"unsupported mcp_server transport: {raw!r}")
        return normalized


DEFAULT_MCP_SERVER_DIALECT = McpServerDialect()
