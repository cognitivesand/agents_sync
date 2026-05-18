"""File-format handlers for ``SharedKeyedMapLayout``.

A ``SharedKeyedMapLayout`` projects an artifact to one slot inside a
shared keyed-map file (e.g. ``~/.cursor/mcp.json[mcpServers][github]``).
The layout is format-agnostic; this module supplies the pluggable
``deserialize`` / ``serialize`` pair that converts the shared file's
text into a Python mapping and back.

v0.5-mcp-server ships only the JSON handler. TOML (Codex
``config.toml[mcp_servers]``) and YAML (Continue, Goose) handlers are
registered by their tool-adapter PRs without touching this module's
core or the layout class.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class SharedKeyedMapFormat:
    """A pair of callables that round-trip the shared file's text.

    ``extension`` is the file extension used for archive naming
    (``<slot>.<extension>.<ISO-timestamp>``). It is informational; the
    layout reads and writes via the configured shared-file path
    regardless of suffix.
    """

    extension: str
    deserialize: Callable[[str], MutableMapping[str, Any]]
    serialize: Callable[[Mapping[str, Any]], str]


_FORMAT_REGISTRY: dict[str, SharedKeyedMapFormat] = {}


def register_format(name: str, format_handler: SharedKeyedMapFormat) -> None:
    """Register a handler under ``name``. Re-registration replaces the
    prior entry (last writer wins) so adapter PRs can override defaults
    in their own test fixtures if needed."""
    _FORMAT_REGISTRY[name] = format_handler


def get_format(name: str) -> SharedKeyedMapFormat:
    """Return the registered handler for ``name`` or raise ``KeyError``."""
    try:
        return _FORMAT_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(
            f"no SharedKeyedMapFormat registered for '{name}'; "
            f"known formats: {sorted(_FORMAT_REGISTRY)}"
        ) from exc


def _json_deserialize(text: str) -> MutableMapping[str, Any]:
    if not text or not text.strip():
        return {}
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("shared keyed-map root must be a JSON object")
    return result


def _json_serialize(obj: Mapping[str, Any]) -> str:
    return json.dumps(obj, indent=2, sort_keys=False) + "\n"


register_format(
    "json",
    SharedKeyedMapFormat(
        extension=".json",
        deserialize=_json_deserialize,
        serialize=_json_serialize,
    ),
)
