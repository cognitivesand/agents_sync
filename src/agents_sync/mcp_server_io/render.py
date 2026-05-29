"""Render canonical ``mcp_server`` documents back to JSON/TOML slots."""
from __future__ import annotations

from typing import Any

from agents_sync.mcp_secret_policy import apply_mcp_secret_policy

from agents_sync.mcp_server_io._helpers import (
    render_env_refs,
    render_field_name,
)
from agents_sync.mcp_server_io._slot_codec import dumps_slot, loads_slot
from agents_sync.mcp_server_io.dialect import (
    DEFAULT_MCP_SERVER_DIALECT,
    McpServerDialect,
)
from agents_sync.mcp_server_io.headers import render_http_headers


def render_mcp_server_json(
    canonical: dict[str, Any],
    prior_text: str | None = None,
    *,
    agentic_tool_name: str,
    dialect: McpServerDialect = DEFAULT_MCP_SERVER_DIALECT,
    slot_format: str = "json",
    secret_policy: str = "secrets_refused",
) -> str:
    """Render one canonical ``mcp_server`` document as a JSON slot."""
    prior_obj = (
        loads_slot(prior_text, slot_format=slot_format)
        if prior_text else {}
    )
    tool_only = canonical.get("per_agentic_tool_only", {}).get(
        agentic_tool_name, {},
    )

    obj: dict[str, Any] = {}
    obj.update(canonical.get("per_agentic_tool_extra", {}).get(agentic_tool_name, {}))

    pair_id = canonical.get("pair_id")
    if pair_id:
        obj[dialect.pair_id_field] = pair_id
    if dialect.render_name_field:
        obj[dialect.name_field] = str(canonical["name"])

    transport = dialect.canonical_transport(canonical.get("transport"))
    transport_field = render_field_name(
        tool_only.get("transport_field"),
        prior_obj,
        dialect.transport_fields,
        dialect.transport_fields[0],
    )
    if dialect.render_transport_field:
        obj[transport_field] = _render_transport_value(transport, tool_only, dialect)

    _render_common_fields(canonical, obj, dialect, tool_only, prior_obj)
    _render_transport_fields(canonical, obj, transport, dialect, tool_only, prior_obj)

    obj = apply_mcp_secret_policy(
        obj,
        policy=secret_policy,
        artifact=str(canonical.get("name", "<unknown>")),
    )
    return dumps_slot(obj, slot_format=slot_format)


def _render_common_fields(
    canonical: dict[str, Any],
    obj: dict[str, Any],
    dialect: McpServerDialect,
    tool_only: dict[str, Any],
    prior_obj: dict[str, Any],
) -> None:
    if "disabled" in canonical:
        field = render_field_name(
            tool_only.get("disabled_field"),
            prior_obj,
            dialect.disabled_fields,
            dialect.disabled_fields[0],
        )
        obj[field] = (
            not bool(canonical["disabled"])
            if field == "enabled"
            else bool(canonical["disabled"])
        )
    if "always_allow" in canonical:
        field = render_field_name(
            tool_only.get("always_allow_field"),
            prior_obj,
            dialect.always_allow_fields,
            dialect.always_allow_fields[0],
        )
        obj[field] = canonical["always_allow"]


def _render_transport_fields(
    canonical: dict[str, Any],
    obj: dict[str, Any],
    transport: str,
    dialect: McpServerDialect,
    tool_only: dict[str, Any],
    prior_obj: dict[str, Any],
) -> None:
    if transport == "stdio":
        _render_stdio_fields(canonical, obj, dialect, tool_only, prior_obj)
        return
    url_field = render_field_name(
        tool_only.get("url_field"),
        prior_obj,
        dialect.url_fields,
        _default_url_field_for_transport(transport, dialect),
    )
    obj[url_field] = canonical["url"]
    render_http_headers(canonical, obj, dialect, tool_only, prior_obj)
    if "auth" in canonical and dialect.auth_render_field is not None:
        auth_field = render_field_name(
            tool_only.get("auth_field"),
            prior_obj,
            dialect.auth_fields,
            dialect.auth_render_field,
        )
        obj[auth_field] = render_env_refs(canonical["auth"], dialect)


def _render_stdio_fields(
    canonical: dict[str, Any],
    obj: dict[str, Any],
    dialect: McpServerDialect,
    tool_only: dict[str, Any],
    prior_obj: dict[str, Any],
) -> None:
    if dialect.command_mode == "array":
        obj["command"] = [
            str(canonical["command"]),
            *[str(arg) for arg in canonical.get("args", [])],
        ]
    else:
        obj["command"] = canonical["command"]
        if "args" in canonical:
            obj["args"] = canonical["args"]
    if "env" in canonical:
        env_field = render_field_name(
            tool_only.get("env_field"),
            prior_obj,
            dialect.env_fields,
            dialect.env_fields[0],
        )
        obj[env_field] = render_env_refs(canonical["env"], dialect)
    for key in ("cwd", "timeout"):
        if key in canonical:
            obj[key] = canonical[key]


def _render_transport_value(
    transport: str,
    tool_only: dict[str, Any],
    dialect: McpServerDialect,
) -> str:
    raw = tool_only.get("transport_value")
    if isinstance(raw, str):
        try:
            if dialect.canonical_transport(raw) == transport:
                return raw
        except ValueError:
            pass
    render_values = dict(dialect.transport_render_values)
    if transport in render_values:
        return render_values[transport]
    return transport


def _default_url_field_for_transport(
    transport: str,
    dialect: McpServerDialect,
) -> str:
    render_fields = dict(dialect.url_render_fields)
    return render_fields.get(transport, dialect.url_fields[0])
