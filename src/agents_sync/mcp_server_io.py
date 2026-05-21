"""JSON parse / render helpers for v0.5 ``mcp_server`` artifacts."""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents_sync.canonical import empty_canonical, new_pair_id
from agents_sync.mcp_secret_policy import (
    apply_mcp_secret_policy,
    bearer_env_reference_name,
    convert_env_references,
    env_reference_name,
    format_env_reference,
)


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


def extract_pair_id_from_mcp_server_json(
    slot_text: str,
    *,
    dialect: McpServerDialect = DEFAULT_MCP_SERVER_DIALECT,
    slot_format: str = "json",
) -> str | None:
    obj = _loads_slot(slot_text, slot_format=slot_format)
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
    secret_policy: str = "refuse",
) -> dict[str, Any]:
    """Parse one JSON slot into the canonical ``mcp_server`` shape."""
    del artifact_root
    obj = _loads_slot(slot_text, slot_format=slot_format)
    raw_artifact = obj.get(dialect.name_field) or obj.get("name")
    artifact = (
        str(raw_artifact)
        if raw_artifact is not None
        else (str(artifact_path) if artifact_path is not None else None)
    )
    obj, redactions = apply_mcp_secret_policy(
        obj, policy=secret_policy, artifact=artifact,
    )

    canonical = (
        dict(prior_canonical)
        if prior_canonical
        else empty_canonical("mcp_server")
    )
    _clear_mcp_fields(canonical)
    canonical["kind"] = "mcp_server"

    name = obj.get(dialect.name_field) or obj.get("name") or canonical.get("name")
    if not name:
        raise ValueError("mcp_server JSON slot must include a name")
    canonical["name"] = str(name)

    pair_id = obj.get(dialect.pair_id_field)
    canonical["pair_id"] = str(pair_id) if pair_id is not None else (
        canonical.get("pair_id") or new_pair_id()
    )

    transport, transport_field = _transport_from_slot(obj, dialect)
    canonical["transport"] = transport
    _copy_common_fields(obj, canonical, dialect)
    _copy_transport_fields(obj, canonical, transport, dialect)

    if redactions:
        canonical["secret_redactions"] = redactions
    else:
        canonical.pop("secret_redactions", None)

    tool_only = dict(canonical.get("per_agentic_tool_only") or {})
    tool_only[agentic_tool_name] = _tool_only_spellings(
        obj, dialect, transport_field=transport_field,
    )
    canonical["per_agentic_tool_only"] = tool_only

    extras = dict(canonical.get("per_agentic_tool_extra") or {})
    extras[agentic_tool_name] = {
        key: value
        for key, value in obj.items()
        if key not in _known_slot_fields(dialect)
    }
    canonical["per_agentic_tool_extra"] = extras

    return canonical


def render_mcp_server_json(
    canonical: dict[str, Any],
    prior_text: str | None = None,
    *,
    agentic_tool_name: str,
    dialect: McpServerDialect = DEFAULT_MCP_SERVER_DIALECT,
    slot_format: str = "json",
    secret_policy: str = "refuse",
) -> str:
    """Render one canonical ``mcp_server`` document as a JSON slot."""
    prior_obj = (
        _loads_slot(prior_text, slot_format=slot_format)
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
    transport_field = _render_field_name(
        tool_only.get("transport_field"),
        prior_obj,
        dialect.transport_fields,
        dialect.transport_fields[0],
    )
    if dialect.render_transport_field:
        obj[transport_field] = _render_transport_value(transport, tool_only, dialect)

    _render_common_fields(canonical, obj, dialect, tool_only, prior_obj)
    _render_transport_fields(canonical, obj, transport, dialect, tool_only, prior_obj)

    obj, _ = apply_mcp_secret_policy(
        obj,
        policy=secret_policy,
        artifact=str(canonical.get("name", "<unknown>")),
    )
    return _dumps_slot(obj, slot_format=slot_format)


def _loads_slot(text: str | None, *, slot_format: str = "json") -> dict[str, Any]:
    if text is None or not text.strip():
        return {}
    if slot_format == "json":
        obj = json.loads(text)
    elif slot_format == "toml":
        obj = tomllib.loads(text)
    else:
        raise ValueError(f"unknown mcp_server slot format: {slot_format!r}")
    if not isinstance(obj, dict):
        raise ValueError("mcp_server JSON slot must be an object")
    return obj


def _dumps_slot(obj: dict[str, Any], *, slot_format: str = "json") -> str:
    if slot_format == "json":
        return json.dumps(obj, indent=2, sort_keys=False) + "\n"
    if slot_format == "toml":
        from agents_sync.shared_keyed_map_formats import get_format

        return get_format("toml").serialize(obj)
    raise ValueError(f"unknown mcp_server slot format: {slot_format!r}")


def _transport_from_slot(
    obj: dict[str, Any],
    dialect: McpServerDialect,
) -> tuple[str, str | None]:
    for field in dialect.transport_fields:
        if field in obj:
            return dialect.canonical_transport(obj[field]), field
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
    disabled_field = _first_present(obj, dialect.disabled_fields)
    if disabled_field is not None:
        disabled_value = bool(obj[disabled_field])
        canonical["disabled"] = (
            not disabled_value if disabled_field == "enabled" else disabled_value
        )
    always_allow_field = _first_present(obj, dialect.always_allow_fields)
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
        if "command" not in obj:
            raise ValueError("stdio mcp_server requires command")
        if isinstance(obj["command"], list):
            command_parts = _as_string_list(obj["command"])
            if not command_parts:
                raise ValueError("stdio mcp_server command array must not be empty")
            canonical["command"] = command_parts[0]
            canonical["args"] = command_parts[1:]
        else:
            canonical["command"] = str(obj["command"])
        if "args" in obj and not isinstance(obj["command"], list):
            canonical["args"] = _as_string_list(obj["args"])
        env_field = _first_present(obj, dialect.env_fields)
        if env_field is not None:
            canonical["env"] = _canonicalize_env_refs(
                _as_mapping(obj[env_field], env_field)
            )
        if "cwd" in obj:
            canonical["cwd"] = str(obj["cwd"])
        if "timeout" in obj:
            canonical["timeout"] = obj["timeout"]
        return

    url_field = _first_present(obj, dialect.url_fields)
    if url_field is None:
        raise ValueError(f"{transport} mcp_server requires url")
    canonical["url"] = str(obj[url_field])
    headers = _headers_from_slot(obj, dialect)
    if headers:
        canonical["headers"] = headers
    auth_field = _first_present(obj, dialect.auth_fields)
    if auth_field is not None:
        canonical["auth"] = _canonicalize_env_refs(
            _as_mapping(obj[auth_field], auth_field)
        )


def _headers_from_slot(
    obj: dict[str, Any],
    dialect: McpServerDialect,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    headers_field = _first_present(obj, dialect.headers_fields)
    if headers_field is not None:
        headers.update(_as_mapping(obj[headers_field], headers_field))
    if dialect.env_http_headers_field and dialect.env_http_headers_field in obj:
        env_headers = _as_mapping(
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
    return _canonicalize_env_refs(headers)


def _canonicalize_env_refs(value: Any) -> Any:
    if isinstance(value, str):
        return convert_env_references(value, style="canonical")
    if isinstance(value, dict):
        return {str(key): _canonicalize_env_refs(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_canonicalize_env_refs(child) for child in value]
    return value


def _render_env_refs(value: Any, dialect: McpServerDialect) -> Any:
    if isinstance(value, str):
        return convert_env_references(value, style=dialect.env_reference_style)
    if isinstance(value, dict):
        return {str(key): _render_env_refs(child, dialect) for key, child in value.items()}
    if isinstance(value, list):
        return [_render_env_refs(child, dialect) for child in value]
    return value


def _render_common_fields(
    canonical: dict[str, Any],
    obj: dict[str, Any],
    dialect: McpServerDialect,
    tool_only: dict[str, Any],
    prior_obj: dict[str, Any],
) -> None:
    if "disabled" in canonical:
        field = _render_field_name(
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
        field = _render_field_name(
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
            env_field = _render_field_name(
                tool_only.get("env_field"),
                prior_obj,
                dialect.env_fields,
                dialect.env_fields[0],
            )
            obj[env_field] = _render_env_refs(canonical["env"], dialect)
        for key in ("cwd", "timeout"):
            if key in canonical:
                obj[key] = canonical[key]
        return

    url_field = _render_field_name(
        tool_only.get("url_field"),
        prior_obj,
        dialect.url_fields,
        dialect.url_fields[0],
    )
    obj[url_field] = canonical["url"]
    _render_http_headers(canonical, obj, dialect, tool_only, prior_obj)
    if "auth" in canonical and dialect.auth_render_field is not None:
        auth_field = _render_field_name(
            tool_only.get("auth_field"),
            prior_obj,
            dialect.auth_fields,
            dialect.auth_render_field,
        )
        obj[auth_field] = _render_env_refs(canonical["auth"], dialect)


def _render_http_headers(
    canonical: dict[str, Any],
    obj: dict[str, Any],
    dialect: McpServerDialect,
    tool_only: dict[str, Any],
    prior_obj: dict[str, Any],
) -> None:
    raw_headers = canonical.get("headers")
    if not isinstance(raw_headers, dict):
        return

    headers = dict(_render_env_refs(raw_headers, dialect))
    if dialect.bearer_token_env_var_field is not None:
        authorization = headers.get("Authorization")
        if isinstance(authorization, str):
            env_name = bearer_env_reference_name(authorization)
            if env_name is not None:
                field = tool_only.get(
                    "bearer_token_env_var_field",
                    dialect.bearer_token_env_var_field,
                )
                obj[str(field)] = env_name
                headers.pop("Authorization", None)

    if dialect.env_http_headers_field is not None:
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

    if headers:
        headers_field = _render_field_name(
            tool_only.get("headers_field"),
            prior_obj,
            dialect.headers_fields,
            dialect.headers_render_field,
        )
        obj[headers_field] = headers


def _render_field_name(
    preferred: Any,
    prior_obj: dict[str, Any],
    allowed: tuple[str, ...],
    default: str,
) -> str:
    if isinstance(preferred, str) and preferred in allowed:
        return preferred
    existing = _first_present(prior_obj, allowed)
    return existing or default


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
    url_field = _first_present(obj, dialect.url_fields)
    if url_field is not None and url_field != dialect.url_fields[0]:
        result["url_field"] = url_field
    headers_field = _first_present(obj, dialect.headers_fields)
    if headers_field is not None and headers_field != dialect.headers_render_field:
        result["headers_field"] = headers_field
    if dialect.env_http_headers_field and dialect.env_http_headers_field in obj:
        result["env_http_headers_field"] = dialect.env_http_headers_field
    if (
        dialect.bearer_token_env_var_field
        and dialect.bearer_token_env_var_field in obj
    ):
        result["bearer_token_env_var_field"] = dialect.bearer_token_env_var_field
    auth_field = _first_present(obj, dialect.auth_fields)
    if auth_field is not None and auth_field != dialect.auth_render_field:
        result["auth_field"] = auth_field
    always_allow_field = _first_present(obj, dialect.always_allow_fields)
    if (
        always_allow_field is not None
        and always_allow_field != dialect.always_allow_fields[0]
    ):
        result["always_allow_field"] = always_allow_field
    env_field = _first_present(obj, dialect.env_fields)
    if env_field is not None and env_field != dialect.env_fields[0]:
        result["env_field"] = env_field
    disabled_field = _first_present(obj, dialect.disabled_fields)
    if disabled_field is not None and disabled_field != dialect.disabled_fields[0]:
        result["disabled_field"] = disabled_field
    return result


def _first_present(obj: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key in obj:
            return key
    return None


def _known_slot_fields(dialect: McpServerDialect) -> set[str]:
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


def _clear_mcp_fields(canonical: dict[str, Any]) -> None:
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


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    raise ValueError("mcp_server args must be a list or string")


def _as_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"mcp_server {field_name} must be an object")
    return dict(value)


__all__ = [
    "DEFAULT_MCP_SERVER_DIALECT",
    "McpServerDialect",
    "extract_pair_id_from_mcp_server_json",
    "parse_mcp_server_json",
    "render_mcp_server_json",
]
