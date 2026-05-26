"""Per-slot serialise/deserialise for JSON and TOML formats."""
from __future__ import annotations

import json
import tomllib
from typing import Any

from agents_sync.parser_bounds import enforce_text_bound


def loads_slot(text: str | None, *, slot_format: str = "json") -> dict[str, Any]:
    if text is None or not text.strip():
        return {}
    text = enforce_text_bound(text, label=f"mcp_server {slot_format} slot")
    if slot_format == "json":
        obj = json.loads(text)
    elif slot_format == "toml":
        obj = tomllib.loads(text)
    else:
        raise ValueError(f"unknown mcp_server slot format: {slot_format!r}")
    if not isinstance(obj, dict):
        raise ValueError("mcp_server JSON slot must be an object")
    return obj


def dumps_slot(obj: dict[str, Any], *, slot_format: str = "json") -> str:
    if slot_format == "json":
        return json.dumps(obj, indent=2, sort_keys=False) + "\n"
    if slot_format == "toml":
        from agents_sync.shared_keyed_map_formats import get_format

        return get_format("toml").serialize(obj)
    raise ValueError(f"unknown mcp_server slot format: {slot_format!r}")
