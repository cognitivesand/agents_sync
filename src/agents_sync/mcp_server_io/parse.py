"""Parse one JSON ``mcp_server`` slot into the canonical shape."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agents_sync.canonical import empty_canonical, new_pair_id
from agents_sync.mcp_secret_policy import apply_mcp_secret_policy

from agents_sync.mcp_server_io._helpers import (
    as_mapping,
    as_string_list,
    canonicalize_env_refs,
    first_present,
)
from agents_sync.mcp_server_io._slot_codec import loads_slot
from agents_sync.mcp_server_io.dialect import (
    DEFAULT_MCP_SERVER_DIALECT,
    McpServerDialect,
)
from agents_sync.mcp_server_io.headers import headers_from_slot


def extract_pair_id_from_mcp_server_json(
    slot_text: str,
    *,
    dialect: McpServerDialect = DEFAULT_MCP_SERVER_DIALECT,
    slot_format: str = "json",
) -> str | None:
    obj = loads_slot(slot_text, slot_format=slot_format)
    pair_id = obj.get(dialect.pair_id_field)
    return pair_id if isinstance(pair_id, str) else None


def parse_mcp_server_json(
    slot_text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    agentic_tool_name: str,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
    dialect: McpServerDialect = DEFAULT_MCP_SERVER_DIALECT,
    slot_format: str = "json",
    secret_policy: str = "secrets_refused",
) -> dict[str, Any]:
    """Parse one JSON slot into the canonical ``mcp_server`` shape."""
    del artifact_root
    obj = loads_slot(slot_text, slot_format=slot_format)
    obj, redactions = _apply_secret_policy(obj, dialect, artifact_path, secret_policy)
    canonical = _extract_canonical(obj, prior_canonical, dialect)
    transport, transport_field = _transport_from_slot(obj, dialect)
    canonical["transport"] = transport
    _copy_common_fields(obj, canonical, dialect)
    _copy_transport_fields(obj, canonical, transport, dialect)
    if redactions:
        canonical["secret_redactions"] = redactions
    else:
        canonical.pop("secret_redactions", None)
    _build_per_tool_views(obj, canonical, dialect, agentic_tool_name, transport_field)
    return canonical


def _apply_secret_policy(
    obj: dict[str, Any],
    dialect: McpServerDialect,
    artifact_path: Path | None,
    secret_policy: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw_artifact = obj.get(dialect.name_field) or obj.get("name")
    artifact = (
        str(raw_artifact)
        if raw_artifact is not None
        else (str(artifact_path) if artifact_path is not None else None)
    )
    return apply_mcp_secret_policy(obj, policy=secret_policy, artifact=artifact)


def _extract_canonical(
    obj: dict[str, Any],
    prior_canonical: dict[str, Any] | None,
    dialect: McpServerDialect,
) -> dict[str, Any]:
    canonical = (
        dict(prior_canonical)
        if prior_canonical
        else empty_canonical("mcp_server")
    )
    clear_mcp_fields(canonical)
    canonical["kind"] = "mcp_server"

    name = obj.get(dialect.name_field) or obj.get("name") or canonical.get("name")
    if not name:
        raise ValueError("mcp_server JSON slot must include a name")
    canonical["name"] = str(name)

    pair_id = obj.get(dialect.pair_id_field)
    canonical["pair_id"] = str(pair_id) if pair_id is not None else (
        canonical.get("pair_id") or new_pair_id()
    )
    return canonical


def _build_per_tool_views(
    obj: dict[str, Any],
    canonical: dict[str, Any],
    dialect: McpServerDialect,
    agentic_tool_name: str,
    transport_field: str | None,
) -> None:
    tool_only = dict(canonical.get("per_agentic_tool_only") or {})
    tool_only[agentic_tool_name] = _tool_only_spellings(
        obj, dialect, transport_field=transport_field,
    )
    canonical["per_agentic_tool_only"] = tool_only

    extras = dict(canonical.get("per_agentic_tool_extra") or {})
    extras[agentic_tool_name] = {
        key: value
        for key, value in obj.items()
        if key not in known_slot_fields(dialect)
    }
    canonical["per_agentic_tool_extra"] = extras


def _transport_from_slot(
    obj: dict[str, Any],
    dialect: McpServerDialect,
) -> tuple[str, str | None]:
    for field in dialect.transport_fields:
        if field in obj:
            return dialect.canonical_transport(obj[field]), field
    for field, transport in dialect.transport_from_fields:
        if field in obj:
            return dialect.canonical_transport(transport), None
    if "command" in obj:
        return "stdio", None
    if any(field in obj for field in dialect.url_fields):
        return "http", None
    raise ValueError("mcp_server JSON slot must declare a transport, command, or url")


def _copy_common_fields(
    obj: dict[str, Any],
    canonical: dict[str, Any],
    dialect: McpServerDialect,
) -> None:
    disabled_field = first_present(obj, dialect.disabled_fields)
    if disabled_field is not None:
        disabled_value = bool(obj[disabled_field])
        canonical["disabled"] = (
            not disabled_value if disabled_field == "enabled" else disabled_value
        )
    always_allow_field = first_present(obj, dialect.always_allow_fields)
    if always_allow_field is not None:
        value = obj[always_allow_field]
        canonical["always_allow"] = value if isinstance(value, list) else [str(value)]


def _copy_transport_fields(
    obj: dict[str, Any],
    canonical: dict[str, Any],
    transport: str,
    dialect: McpServerDialect,
) -> None:
    if transport == "stdio":
        _copy_stdio_fields(obj, canonical, dialect)
        return
    url_field = first_present(obj, dialect.url_fields)
    if url_field is None:
        raise ValueError(f"{transport} mcp_server requires url")
    canonical["url"] = str(obj[url_field])
    headers = headers_from_slot(obj, dialect)
    if headers:
        canonical["headers"] = headers
    auth_field = first_present(obj, dialect.auth_fields)
    if auth_field is not None:
        canonical["auth"] = canonicalize_env_refs(
            as_mapping(obj[auth_field], auth_field)
        )


def _copy_stdio_fields(
    obj: dict[str, Any],
    canonical: dict[str, Any],
    dialect: McpServerDialect,
) -> None:
    if "command" not in obj:
        raise ValueError("stdio mcp_server requires command")
    if isinstance(obj["command"], list):
        command_parts = as_string_list(obj["command"])
        if not command_parts:
            raise ValueError("stdio mcp_server command array must not be empty")
        canonical["command"] = command_parts[0]
        canonical["args"] = command_parts[1:]
    else:
        canonical["command"] = str(obj["command"])
    if "args" in obj and not isinstance(obj["command"], list):
        canonical["args"] = as_string_list(obj["args"])
    env_field = first_present(obj, dialect.env_fields)
    if env_field is not None:
        canonical["env"] = canonicalize_env_refs(
            as_mapping(obj[env_field], env_field)
        )
    if "cwd" in obj:
        canonical["cwd"] = str(obj["cwd"])
    if "timeout" in obj:
        canonical["timeout"] = obj["timeout"]


def _tool_only_spellings(
    obj: dict[str, Any],
    dialect: McpServerDialect,
    *,
    transport_field: str | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if transport_field is not None:
        result["transport_field"] = transport_field
        result["transport_value"] = obj.get(transport_field)
    url_field = first_present(obj, dialect.url_fields)
    if url_field is not None and url_field != dialect.url_fields[0]:
        result["url_field"] = url_field
    headers_field = first_present(obj, dialect.headers_fields)
    if headers_field is not None and headers_field != dialect.headers_render_field:
        result["headers_field"] = headers_field
    if dialect.env_http_headers_field and dialect.env_http_headers_field in obj:
        result["env_http_headers_field"] = dialect.env_http_headers_field
    if (
        dialect.bearer_token_env_var_field
        and dialect.bearer_token_env_var_field in obj
    ):
        result["bearer_token_env_var_field"] = dialect.bearer_token_env_var_field
    auth_field = first_present(obj, dialect.auth_fields)
    if auth_field is not None and auth_field != dialect.auth_render_field:
        result["auth_field"] = auth_field
    always_allow_field = first_present(obj, dialect.always_allow_fields)
    if (
        always_allow_field is not None
        and always_allow_field != dialect.always_allow_fields[0]
    ):
        result["always_allow_field"] = always_allow_field
    env_field = first_present(obj, dialect.env_fields)
    if env_field is not None and env_field != dialect.env_fields[0]:
        result["env_field"] = env_field
    disabled_field = first_present(obj, dialect.disabled_fields)
    if disabled_field is not None and disabled_field != dialect.disabled_fields[0]:
        result["disabled_field"] = disabled_field
    return result


def known_slot_fields(dialect: McpServerDialect) -> set[str]:
    return {
        dialect.pair_id_field,
        dialect.name_field,
        "name",
        "command",
        "args",
        "env",
        *dialect.env_fields,
        "cwd",
        "timeout",
        "headers",
        *dialect.headers_fields,
        *((
            dialect.env_http_headers_field,
        ) if dialect.env_http_headers_field else ()),
        *((
            dialect.bearer_token_env_var_field,
        ) if dialect.bearer_token_env_var_field else ()),
        "auth",
        *dialect.auth_fields,
        "disabled",
        *dialect.disabled_fields,
        *dialect.transport_fields,
        *dialect.url_fields,
        *dialect.always_allow_fields,
    }


def clear_mcp_fields(canonical: dict[str, Any]) -> None:
    for key in (
        "transport",
        "command",
        "args",
        "env",
        "cwd",
        "timeout",
        "url",
        "headers",
        "auth",
        "disabled",
        "always_allow",
        "secret_redactions",
    ):
        canonical.pop(key, None)
