"""Shared helpers for the mcp_server_io package."""
from __future__ import annotations

from typing import Any

from agents_sync.mcp_secret_policy import convert_env_references
from agents_sync.mcp_server_io.dialect import McpServerDialect


def first_present(obj: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key in obj:
            return key
    return None


def as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    raise ValueError("mcp_server args must be a list or string")


def as_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"mcp_server {field_name} must be an object")
    return dict(value)


def canonicalize_env_refs(value: Any) -> Any:
    if isinstance(value, str):
        return convert_env_references(value, style="canonical")
    if isinstance(value, dict):
        return {str(key): canonicalize_env_refs(child) for key, child in value.items()}
    if isinstance(value, list):
        return [canonicalize_env_refs(child) for child in value]
    return value


def render_env_refs(value: Any, dialect: McpServerDialect) -> Any:
    if isinstance(value, str):
        return convert_env_references(value, style=dialect.env_reference_style)
    if isinstance(value, dict):
        return {str(key): render_env_refs(child, dialect) for key, child in value.items()}
    if isinstance(value, list):
        return [render_env_refs(child, dialect) for child in value]
    return value


def render_field_name(
    preferred: Any,
    prior_obj: dict[str, Any],
    allowed: tuple[str, ...],
    default: str,
) -> str:
    if isinstance(preferred, str) and preferred in allowed:
        return preferred
    existing = first_present(prior_obj, allowed)
    return existing or default
