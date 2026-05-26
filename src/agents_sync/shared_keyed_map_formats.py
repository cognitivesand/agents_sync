"""Format-handler registry for ``SharedKeyedMapLayout``.

A ``SharedKeyedMapLayout`` projects an artifact to one slot inside a
shared keyed-map file (e.g. ``~/.cursor/mcp.json[mcpServers][github]``).
The layout is format-agnostic; this module registers the pluggable
``deserialize`` / ``serialize`` pair that converts the shared file's
text into a Python mapping and back.

v0.5-mcp-server ships JSON/JSONC and TOML handlers, implemented in
:mod:`agents_sync.formats.json_format` and
:mod:`agents_sync.formats.toml_format`. YAML (Continue, Goose)
handlers can be registered by their tool-adapter PRs without touching
this module's core or the layout class.
"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any, Callable

from agents_sync.formats import json_format, toml_format


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


register_format(
    "json",
    SharedKeyedMapFormat(
        extension=".json",
        deserialize=json_format.deserialize,
        serialize=json_format.serialize,
    ),
)


register_format(
    "toml",
    SharedKeyedMapFormat(
        extension=".toml",
        deserialize=toml_format.deserialize,
        serialize=toml_format.serialize,
    ),
)
