"""File-format handlers for ``SharedKeyedMapLayout``.

A ``SharedKeyedMapLayout`` projects an artifact to one slot inside a
shared keyed-map file (e.g. ``~/.cursor/mcp.json[mcpServers][github]``).
The layout is format-agnostic; this module supplies the pluggable
``deserialize`` / ``serialize`` pair that converts the shared file's
text into a Python mapping and back.

v0.5-mcp-server ships JSON/JSONC and TOML handlers. YAML (Continue,
Goose) handlers can be registered by their tool-adapter PRs without
touching this module's core or the layout class.
"""
from __future__ import annotations

import json
import re
import tomllib
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
    text = _without_utf8_bom(text)
    if not text or not text.strip():
        return {}
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = json.loads(_normalize_jsonc(text))
    if not isinstance(result, dict):
        raise ValueError("shared keyed-map root must be a JSON object")
    return result


def _json_serialize(obj: Mapping[str, Any]) -> str:
    return json.dumps(obj, indent=2, sort_keys=False) + "\n"


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_key(key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key
    return _toml_string(key)


def _toml_scalar(value: Any) -> str:
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    if isinstance(value, Mapping):
        return _toml_inline_table(value)
    raise TypeError(f"unsupported TOML scalar: {type(value).__name__}")


def _toml_inline_table(value: Mapping[str, Any]) -> str:
    items = [
        f"{_toml_key(str(key))} = {_toml_scalar(child)}"
        for key, child in value.items()
    ]
    return "{ " + ", ".join(items) + " }"


def _toml_section_name(parts: tuple[str, ...]) -> str:
    return ".".join(_toml_key(part) for part in parts)


def _emit_toml_table(
    lines: list[str],
    table: Mapping[str, Any],
    *,
    path: tuple[str, ...] = (),
) -> None:
    scalars: list[tuple[str, Any]] = []
    tables: list[tuple[str, Mapping[str, Any]]] = []

    for key, value in table.items():
        if isinstance(value, Mapping):
            tables.append((key, value))
        else:
            scalars.append((key, value))

    for key, value in scalars:
        lines.append(f"{_toml_key(key)} = {_toml_scalar(value)}")

    for key, value in tables:
        if lines and lines[-1] != "":
            lines.append("")
        child_path = path + (key,)
        lines.append(f"[{_toml_section_name(child_path)}]")
        _emit_toml_table(lines, value, path=child_path)


def _toml_deserialize(text: str) -> MutableMapping[str, Any]:
    text = _without_utf8_bom(text)
    if not text or not text.strip():
        return {}
    result = tomllib.loads(text)
    if not isinstance(result, dict):
        raise ValueError("shared keyed-map root must be a TOML table")
    return result


def _toml_serialize(obj: Mapping[str, Any]) -> str:
    lines: list[str] = []
    _emit_toml_table(lines, obj)
    return "\n".join(lines).rstrip() + "\n"


register_format(
    "json",
    SharedKeyedMapFormat(
        extension=".json",
        deserialize=_json_deserialize,
        serialize=_json_serialize,
    ),
)


def _normalize_jsonc(text: str) -> str:
    """Strip JSONC comments and trailing commas before stdlib JSON parsing."""
    without_comments = _strip_jsonc_comments(_without_utf8_bom(text))
    return _strip_trailing_json_commas(without_comments)


def _without_utf8_bom(text: str) -> str:
    return text.removeprefix("\ufeff")


def _strip_jsonc_comments(text: str) -> str:
    result: list[str] = []
    in_string = False
    escaped = False
    in_line_comment = False
    in_block_comment = False
    index = 0

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if in_line_comment:
            if char in "\r\n":
                in_line_comment = False
                result.append(char)
            index += 1
            continue

        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
            else:
                index += 1
            continue

        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "\"":
                in_string = False
            index += 1
            continue

        if char == "\"":
            in_string = True
            result.append(char)
            index += 1
            continue

        if char == "/" and next_char == "/":
            in_line_comment = True
            index += 2
            continue

        if char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue

        result.append(char)
        index += 1

    return "".join(result)


def _strip_trailing_json_commas(text: str) -> str:
    result: list[str] = []
    in_string = False
    escaped = False
    index = 0

    while index < len(text):
        char = text[index]
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "\"":
                in_string = False
            index += 1
            continue

        if char == "\"":
            in_string = True
            result.append(char)
            index += 1
            continue

        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue

        result.append(char)
        index += 1

    return "".join(result)

register_format(
    "toml",
    SharedKeyedMapFormat(
        extension=".toml",
        deserialize=_toml_deserialize,
        serialize=_toml_serialize,
    ),
)
