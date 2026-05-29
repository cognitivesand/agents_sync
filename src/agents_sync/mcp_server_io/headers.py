"""HTTP-header extraction for the mcp_server JSON dialect.

Headers live in canonical form as ``{Header-Name: value}``. On parse
this module pulls header values out of dialect-specific carriers
(``env_http_headers``, ``bearer_token_env_var``); on render it does
the inverse, emitting env-only headers under the dialect's dedicated
field rather than inline.
"""
from __future__ import annotations

from typing import Any, cast

from agents_sync.mcp_secret_policy import (
    bearer_env_reference_name,
    env_reference_name,
    format_env_reference,
)
from agents_sync.mcp_server_io._helpers import (
    as_mapping,
    canonicalize_env_refs,
    first_present,
    render_env_refs,
    render_field_name,
)
from agents_sync.mcp_server_io.dialect import McpServerDialect


def headers_from_slot(
    obj: dict[str, Any],
    dialect: McpServerDialect,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    headers_field = first_present(obj, dialect.headers_fields)
    if headers_field is not None:
        headers.update(as_mapping(obj[headers_field], headers_field))
    if dialect.env_http_headers_field and dialect.env_http_headers_field in obj:
        env_headers = as_mapping(
            obj[dialect.env_http_headers_field],
            dialect.env_http_headers_field,
        )
        for header_name, env_name in env_headers.items():
            headers[str(header_name)] = format_env_reference(
                str(env_name), style="canonical"
            )
    if (
        dialect.bearer_token_env_var_field
        and dialect.bearer_token_env_var_field in obj
    ):
        env_name = str(obj[dialect.bearer_token_env_var_field])
        headers["Authorization"] = (
            f"Bearer {format_env_reference(env_name, style='canonical')}"
        )
    return cast("dict[str, Any]", canonicalize_env_refs(headers))


def render_http_headers(
    canonical: dict[str, Any],
    obj: dict[str, Any],
    dialect: McpServerDialect,
    tool_only: dict[str, Any],
    prior_obj: dict[str, Any],
) -> None:
    raw_headers = canonical.get("headers")
    if not isinstance(raw_headers, dict):
        return

    headers = dict(render_env_refs(raw_headers, dialect))
    _extract_bearer_to_env_var(headers, obj, dialect, tool_only)
    _extract_env_headers(headers, obj, dialect, tool_only)
    if headers:
        headers_field = render_field_name(
            tool_only.get("headers_field"),
            prior_obj,
            dialect.headers_fields,
            dialect.headers_render_field,
        )
        obj[headers_field] = headers


def _extract_bearer_to_env_var(
    headers: dict[str, Any],
    obj: dict[str, Any],
    dialect: McpServerDialect,
    tool_only: dict[str, Any],
) -> None:
    """If the dialect supports a dedicated ``bearer_token_env_var`` field and
    the headers carry a ``Bearer ${env:NAME}`` Authorization, lift the env
    var name onto ``obj`` and drop the Authorization header. No-op if either
    side is missing.
    """
    if dialect.bearer_token_env_var_field is None:
        return
    authorization = headers.get("Authorization")
    if not isinstance(authorization, str):
        return
    env_name = bearer_env_reference_name(authorization)
    if env_name is None:
        return
    field = tool_only.get(
        "bearer_token_env_var_field",
        dialect.bearer_token_env_var_field,
    )
    obj[str(field)] = env_name
    headers.pop("Authorization", None)


def _extract_env_headers(
    headers: dict[str, Any],
    obj: dict[str, Any],
    dialect: McpServerDialect,
    tool_only: dict[str, Any],
) -> None:
    """Lift every ``${env:NAME}`` header value into the dialect's
    ``env_http_headers_field`` map and drop those entries from ``headers``.
    Headers that are not env references stay on ``headers`` and are emitted
    inline.
    """
    if dialect.env_http_headers_field is None:
        return
    env_headers: dict[str, str] = {}
    for header_name, header_value in list(headers.items()):
        if not isinstance(header_value, str):
            continue
        env_name = env_reference_name(header_value)
        if env_name is None:
            continue
        env_headers[str(header_name)] = env_name
        headers.pop(header_name, None)
    if env_headers:
        field = tool_only.get(
            "env_http_headers_field",
            dialect.env_http_headers_field,
        )
        obj[str(field)] = env_headers
