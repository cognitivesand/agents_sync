"""The markdown-frontmatter dialect — YAML front-matter + Markdown body (pure).

The first wire format the translation seam understands (proposal §10). It folds a
tool's Markdown file into the canonical document and renders it back:

- ``parse`` — split front-matter from body, map ``known_fields`` onto canonical
  attributes, keep ``tool_only_fields`` verbatim under ``per_tool_only[tool]`` and
  every other front-matter key under ``per_tool_extra[tool]`` (no-foreign-leak,
  NFR-06/16). Identity is carried through, never minted (FR-11/AD-2); ``kind`` is
  stamped from the surface (the text does not carry it). Fields the surface omits
  retain their prior-canonical value, so a tool need not repeat unchanged metadata.
- ``render`` — the inverse, emitting this tool's view and preserving the user's
  prior formatting (key order, comments) when given ``prior_text``.
- ``extract_id`` — the id in isolation, recovered from its own line even when the
  surrounding YAML will not parse; never raises (FR-11).

Pure: operates on ``text: str``, does no I/O, and applies no parse-size bounds —
that size-explosion hardening is a separate concern (``parser_bounds``, deferred
from S9; see the implementation plan's S24 gate).
"""

from __future__ import annotations

import io
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import replace
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

from agents_sync.dialects import MalformedSurfaceError
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import ToolSurface

# A leading ``---`` YAML block, then the body. Group 1 is the front-matter, group 2
# the body. ``\A`` anchors it to the document start so only a true front-matter block
# (not a horizontal rule mid-body) matches. The newline before the closing fence is
# optional so an empty block (``---\n---``) matches and resolves to metadata-less,
# rather than the literal fences leaking into the body (NFR-16).
_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)(?:\r?\n)?---[ \t]*(?:\r?\n|\Z)(.*)\Z",
    re.DOTALL,
)
# Canonical attributes whose front-matter value is a list (or a comma-separated string).
_LIST_ATTRIBUTES = frozenset({"tools", "disallowed_tools"})


def parse(
    text: str,
    tool_surface: ToolSurface,
    prior_canonical: CanonicalDocument | None,
) -> CanonicalDocument:
    """Fold a tool's Markdown text into the canonical document (raises if malformed)."""
    frontmatter, body = _split_frontmatter(text)
    surface_format = tool_surface.surface_format
    tool = tool_surface.tool

    base = prior_canonical or CanonicalDocument(artifact_id="", kind=tool_surface.kind)
    changes: dict[str, Any] = {
        "artifact_id": _recover_id(frontmatter, surface_format.id_field, base),
        "kind": tool_surface.kind,
        "body": body,
    }
    for front_matter_key, attribute in surface_format.known_fields:
        value = frontmatter.get(front_matter_key)
        # A present-but-null key (`description:` with no value) means "absent", not a
        # None written onto a str-typed canonical attribute (which would crash the
        # planner's normalised()/content_digest()); the field keeps its prior default.
        if value is not None:
            changes[attribute] = _coerce(attribute, value)

    consumed = (
        {key for key, _ in surface_format.known_fields}
        | set(surface_format.tool_only_fields)
        | {surface_format.id_field}
    )
    tool_only = {
        key: frontmatter[key] for key in surface_format.tool_only_fields if key in frontmatter
    }
    extra = {key: value for key, value in frontmatter.items() if key not in consumed}
    changes["per_tool_only"] = _with_tool_slot(base.per_tool_only, tool, tool_only)
    changes["per_tool_extra"] = _with_tool_slot(base.per_tool_extra, tool, extra)

    return replace(base, **changes)


def render(
    canonical: CanonicalDocument,
    tool_surface: ToolSurface,
    prior_text: str | None,
) -> str:
    """Render this tool's view of the canonical, preserving prior formatting if given."""
    surface_format = tool_surface.surface_format
    tool = tool_surface.tool
    values = canonical.to_dict()  # thawed to plain dict/list so the YAML emitter can serialise

    frontmatter = _base_frontmatter(prior_text)
    if canonical.artifact_id:
        frontmatter[surface_format.id_field] = canonical.artifact_id
    for front_matter_key, attribute in surface_format.known_fields:
        _set_or_drop(frontmatter, front_matter_key, _render_value(attribute, values.get(attribute)))
    for key, value in values["per_tool_only"].get(tool, {}).items():
        frontmatter[key] = value
    for key, value in values["per_tool_extra"].get(tool, {}).items():
        frontmatter[key] = value

    return _emit(frontmatter, canonical.body)


def extract_id(text: str, tool_surface: ToolSurface) -> str | None:
    """Return the embedded id, recovered in isolation; never raises (FR-11)."""
    id_field = tool_surface.surface_format.id_field
    block = _frontmatter_block(text)
    if block is None:
        return None
    try:
        loaded = _yaml().load(io.StringIO(block)) if block.strip() else None
    except YAMLError:
        return _isolated_id(block, id_field)
    if isinstance(loaded, Mapping):
        value = loaded.get(id_field)
        if isinstance(value, str) and value:
            return value
    return None


def _frontmatter_block(text: str) -> str | None:
    """Return the raw front-matter block, or ``None`` when the text has no leading block.

    The single home for "find the front-matter span", shared by the id-probe and the
    render-seed paths so they cannot drift from the same ``_FRONTMATTER_RE`` grammar.
    ``_split_frontmatter`` keeps its own match because it also needs the body offset.
    """
    match = _FRONTMATTER_RE.match(text)
    return match.group(1) if match else None


def _yaml() -> YAML:
    """A round-trip YAML configured to preserve quotes, width, and indentation."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split into (front-matter mapping, stripped body); raise if the block is malformed.

    A document with no leading ``---`` block is a valid metadata-less file: ``({}, body)``.
    A block that is present but not a YAML mapping (or unparseable) is malformed.
    """
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return {}, text.strip()
    raw_block = match.group(1)
    body = text[match.start(2) :].strip()
    if not raw_block.strip():
        return {}, body
    try:
        loaded = _yaml().load(io.StringIO(raw_block))
    except YAMLError as error:
        raise MalformedSurfaceError(f"front-matter is not valid YAML: {error}") from error
    if not isinstance(loaded, Mapping):
        raise MalformedSurfaceError("front-matter must be a YAML mapping")
    return dict(loaded), body


def _recover_id(frontmatter: Mapping[str, Any], id_field: str, base: CanonicalDocument) -> str:
    """Carry the embedded id through if present and a non-empty string, else the prior id."""
    embedded = frontmatter.get(id_field)
    if isinstance(embedded, str) and embedded:
        return embedded
    return base.artifact_id


def _coerce(attribute: str, value: Any) -> Any:
    """Coerce a front-matter value to the canonical attribute's shape."""
    if attribute in _LIST_ATTRIBUTES:
        return tuple(_as_string_list(value))
    return value


def _as_string_list(value: Any) -> list[str]:
    """A YAML list, or a comma-separated string, as a list of strings."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _with_tool_slot(
    bags: Mapping[str, Any],
    tool: str,
    slot: Mapping[str, Any],
) -> dict[str, Any]:
    """Replace this tool's per-tool bag with ``slot`` (an empty slot clears it), keeping others.

    The tool's own file is the source of truth for its bag, so an empty slot removes a
    field the user deleted; the other tools' bags are carried untouched (no-foreign-leak).
    """
    merged = dict(bags)
    if slot:
        merged[tool] = dict(slot)
    else:
        merged.pop(tool, None)
    return merged


def _base_frontmatter(prior_text: str | None) -> MutableMapping[str, Any]:
    """A mutable front-matter mapping seeded from ``prior_text`` to preserve formatting."""
    if prior_text is None:
        return CommentedMap()
    block = _frontmatter_block(prior_text)
    if block is None:
        return CommentedMap()
    try:
        loaded = _yaml().load(io.StringIO(block))
    except YAMLError:
        return CommentedMap()
    return loaded if isinstance(loaded, MutableMapping) else CommentedMap()


def _render_value(attribute: str, value: Any) -> Any:
    """Prepare a canonical value for the YAML emitter (list attributes emit as a list)."""
    if attribute in _LIST_ATTRIBUTES:
        return list(value) if value else None
    return value


def _set_or_drop(frontmatter: MutableMapping[str, Any], key: str, value: Any) -> None:
    """Set ``key`` to ``value``, or drop it when the value is empty (absent on the wire)."""
    if value is None or value == "" or value == []:
        frontmatter.pop(key, None)
    else:
        frontmatter[key] = value


def _emit(frontmatter: Mapping[str, Any], body: str) -> str:
    """Emit the front-matter block followed by the Markdown body."""
    buffer = io.StringIO()
    _yaml().dump(frontmatter, buffer)
    rendered = buffer.getvalue().rstrip("\n")
    if body:
        return f"---\n{rendered}\n---\n{body}\n"
    return f"---\n{rendered}\n---\n"


def _isolated_id(block: str, id_field: str) -> str | None:
    """Find the id on its own line when the surrounding YAML will not parse (FR-11)."""
    pattern = re.compile(
        rf"^[ \t]*{re.escape(id_field)}[ \t]*:[ \t]*[\"']?(?P<id>[^\s\"'#]+)",
        re.MULTILINE,
    )
    found = pattern.search(block)
    return found.group("id") if found else None
