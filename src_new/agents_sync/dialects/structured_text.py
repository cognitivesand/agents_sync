"""The shared structured-text codec — read/write a JSON or TOML file (pure, no I/O).

The one place a structured-text wire format is understood: ``deserialize`` parses a
file's ``text`` into a Python mapping, ``serialize`` writes a mapping back. The
keyed-map dialect (and the S11b whole-file dialect) call these instead of carrying
their own codec, so there is no parallel codec per tool (NFR-18).

Round-trip preserves **key order and data**; it does **not** preserve comments
(matching the current behaviour the conformance suite encodes). Stdlib only — no new
dependency: ``tomllib`` reads TOML and ``json`` reads JSON; TOML is written by a small
hand-rolled emitter (stdlib has no TOML writer) and JSON by ``json.dumps``. A malformed
document raises ``MalformedSurfaceError`` (a content error); an unsupported format
raises a plain ``ValueError`` (a recipe error, distinct from malformed content).
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from typing import Any

from agents_sync.dialects import MalformedSurfaceError
from agents_sync.dialects.field_mapping import (
    fold_fields_into_canonical,
    project_canonical_to_fields,
)
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import ToolSurface

_TOML_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


def deserialize(text: str, file_format: str) -> dict[str, Any]:
    """Parse ``text`` into a mapping; raise on malformed content or an unsupported format."""
    if not text.strip():
        return {}
    if file_format == "json":
        return _deserialize_json(text)
    if file_format == "toml":
        return _deserialize_toml(text)
    raise ValueError(f"unsupported structured-text format: {file_format!r}")


def serialize(obj: Mapping[str, Any], file_format: str) -> str:
    """Write ``obj`` back to text, preserving key order (not comments)."""
    if file_format == "json":
        return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    if file_format == "toml":
        lines: list[str] = []
        _emit_toml_table(lines, obj)
        return "\n".join(lines).rstrip() + "\n"
    raise ValueError(f"unsupported structured-text format: {file_format!r}")


# --- the whole-file dialect: the entire file is one field map ---


def parse(
    text: str,
    tool_surface: ToolSurface,
    prior_canonical: CanonicalDocument | None,
) -> CanonicalDocument:
    """Fold a whole structured-text file into the canonical document (raises if malformed).

    The body, when the artifact has one, is just a named field (e.g. codex's
    ``developer_instructions``) the recipe maps via ``known_fields``, so it folds through
    the shared recipe-application like any other field — no body argument here.
    """
    fields = deserialize(text, tool_surface.surface_format.file_format)
    return fold_fields_into_canonical(fields, tool_surface, prior_canonical, body=None)


def render(canonical: CanonicalDocument, tool_surface: ToolSurface, prior_text: str | None) -> str:
    """Render the canonical as a whole structured-text file.

    ``prior_text`` is unused: a whole-file artifact is a complete projection of the
    canonical, so the file is built fresh (in recipe order) rather than seeded from prior.
    """
    fields = project_canonical_to_fields(canonical, tool_surface)
    return serialize(fields, tool_surface.surface_format.file_format)


def extract_id(text: str, tool_surface: ToolSurface) -> str | None:
    """Return the file's embedded id; never raises on malformed text (FR-11)."""
    try:
        fields = deserialize(text, tool_surface.surface_format.file_format)
    except MalformedSurfaceError:
        return None
    value = fields.get(tool_surface.surface_format.id_field)
    return value if isinstance(value, str) and value else None


def _deserialize_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise MalformedSurfaceError(f"file is not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise MalformedSurfaceError("structured-text root must be an object")
    return parsed


def _deserialize_toml(text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise MalformedSurfaceError(f"file is not valid TOML: {error}") from error


def _emit_toml_table(
    lines: list[str], table: Mapping[str, Any], path: tuple[str, ...] = ()
) -> None:
    """Emit a TOML table: scalars first (in order), then nested tables as ``[a.b]`` sections."""
    scalars = [(key, value) for key, value in table.items() if not isinstance(value, Mapping)]
    tables = [(key, value) for key, value in table.items() if isinstance(value, Mapping)]
    for key, value in scalars:
        lines.append(f"{_toml_key(key)} = {_toml_scalar(value)}")
    for key, value in tables:
        if lines and lines[-1] != "":
            lines.append("")
        child_path = path + (key,)
        lines.append(f"[{'.'.join(_toml_key(part) for part in child_path)}]")
        _emit_toml_table(lines, value, child_path)


def _toml_key(key: str) -> str:
    return key if _TOML_BARE_KEY.fullmatch(key) else json.dumps(key, ensure_ascii=False)


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    if isinstance(value, Mapping):
        items = ", ".join(f"{_toml_key(k)} = {_toml_scalar(v)}" for k, v in value.items())
        return "{ " + items + " }"
    raise TypeError(f"unsupported TOML value: {type(value).__name__}")
