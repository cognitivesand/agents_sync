"""JSON parse / render helpers for v0.5 ``mcp_server`` artifacts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents_sync.canonical import empty_canonical, new_pair_id
from agents_sync.mcp_secret_policy import apply_mcp_secret_policy


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
    transport_fields: tuple[str, ...] = ("transport", "type", "transportType")
    url_fields: tuple[str, ...] = ("url", "httpUrl", "serverUrl")
    always_allow_fields: tuple[str, ...] = (
        "always_allow",
        "alwaysAllow",
        "allowedTools",
    )
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
) -> str | None:
    try:
        obj = _loads_slot(slot_text)
    except (json.JSONDecodeError, ValueError):
        return None
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
    secret_policy: str = "refuse",
) -> dict[str, Any]:
    """Parse one JSON slot into the canonical ``mcp_server`` shape."""
    del artifact_root
    obj = _loads_slot(slot_text)
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
    secret_policy: str = "refuse",
) -> str:
    """Render one canonical ``mcp_server`` document as a JSON slot."""
    prior_obj = _loads_slot(prior_text) if prior_text else {}
    tool_only = canonical.get("per_agentic_tool_only", {}).get(
        agentic_tool_name, {},
    )

    obj: dict[str, Any] = {}
    obj.update(canonical.get("per_agentic_tool_extra", {}).get(agentic_tool_name, {}))

    pair_id = canonical.get("pair_id")
    if pair_id:
        obj[dialect.pair_id_field] = pair_id
    obj[dialect.name_field] = str(canonical["name"])

    transport = dialect.canonical_transport(canonical.get("transport"))
    transport_field = _render_field_name(
        tool_only.get("transport_field"),
        prior_obj,
        dialect.transport_fields,
        dialect.transport_fields[0],
    )
    obj[transport_field] = _render_transport_value(transport, tool_only, dialect)

    _render_common_fields(canonical, obj, dialect, tool_only, prior_obj)
    _render_transport_fields(canonical, obj, transport, dialect, tool_only, prior_obj)

    obj, _ = apply_mcp_secret_policy(
        obj,
        policy=secret_policy,
        artifact=str(canonical.get("name", "<unknown>")),
    )
    return json.dumps(obj, indent=2, sort_keys=False) + "\n"


def _loads_slot(text: str | None) -> dict[str, Any]:
    if text is None or not text.strip():
        return {}
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("mcp_server JSON slot must be an object")
    return obj


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
    if "disabled" in obj:
        canonical["disabled"] = bool(obj["disabled"])
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
        canonical["command"] = str(obj["command"])
        if "args" in obj:
            canonical["args"] = _as_string_list(obj["args"])
        if "env" in obj:
            canonical["env"] = _as_mapping(obj["env"], "env")
        if "cwd" in obj:
            canonical["cwd"] = str(obj["cwd"])
        if "timeout" in obj:
            canonical["timeout"] = obj["timeout"]
        return

    url_field = _first_present(obj, dialect.url_fields)
    if url_field is None:
        raise ValueError(f"{transport} mcp_server requires url")
    canonical["url"] = str(obj[url_field])
    if "headers" in obj:
        canonical["headers"] = _as_mapping(obj["headers"], "headers")
    if "auth" in obj:
        canonical["auth"] = _as_mapping(obj["auth"], "auth")


def _render_common_fields(
    canonical: dict[str, Any],
    obj: dict[str, Any],
    dialect: McpServerDialect,
    tool_only: dict[str, Any],
    prior_obj: dict[str, Any],
) -> None:
    if "disabled" in canonical:
        obj["disabled"] = bool(canonical["disabled"])
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
        obj["command"] = canonical["command"]
        for key in ("args", "env", "cwd", "timeout"):
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
    for key in ("headers", "auth"):
        if key in canonical:
            obj[key] = canonical[key]


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
    always_allow_field = _first_present(obj, dialect.always_allow_fields)
    if (
        always_allow_field is not None
        and always_allow_field != dialect.always_allow_fields[0]
    ):
        result["always_allow_field"] = always_allow_field
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
        "cwd",
        "timeout",
        "headers",
        "auth",
        "disabled",
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
