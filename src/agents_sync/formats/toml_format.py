"""TOML handler for SharedKeyedMapLayout shared files."""
from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping, MutableMapping
from typing import Any

from agents_sync.formats.jsonc_tokenizer import strip_utf8_bom
from agents_sync.parser_bounds import enforce_text_bound

_CORRUPTED_UTF8_BOM = "\u00ef\u00bb\u00bf"


def normalize_toml_text(text: str) -> str:
    """Strip TOML BOM variants before parsing."""
    text = strip_utf8_bom(text)
    if text.startswith(_CORRUPTED_UTF8_BOM):
        return text[len(_CORRUPTED_UTF8_BOM):]
    return text


def deserialize(text: str) -> MutableMapping[str, Any]:
    text = enforce_text_bound(text, label="shared keyed-map TOML")
    text = normalize_toml_text(text)
    if not text or not text.strip():
        return {}
    result = tomllib.loads(text)
    if not isinstance(result, dict):
        raise ValueError("shared keyed-map root must be a TOML table")
    return result


def serialize(obj: Mapping[str, Any]) -> str:
    lines: list[str] = []
    _emit_table(lines, obj)
    return "\n".join(lines).rstrip() + "\n"


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


def _emit_table(
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
        _emit_table(lines, value, path=child_path)
