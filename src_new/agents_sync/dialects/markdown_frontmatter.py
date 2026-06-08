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
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

from agents_sync.dialects import MalformedSurfaceError
from agents_sync.dialects.field_mapping import (
    fold_fields_into_canonical,
    project_canonical_to_fields,
)
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


def parse(
    text: str,
    tool_surface: ToolSurface,
    prior_canonical: CanonicalDocument | None,
) -> CanonicalDocument:
    """Fold a tool's Markdown text into the canonical document (raises if malformed)."""
    frontmatter, body = _split_frontmatter(text)
    return fold_fields_into_canonical(frontmatter, tool_surface, prior_canonical, body=body)


def render(
    canonical: CanonicalDocument,
    tool_surface: ToolSurface,
    prior_text: str | None,
) -> str:
    """Render this tool's view of the canonical, preserving prior formatting if given."""
    frontmatter = project_canonical_to_fields(
        canonical, tool_surface, base=_base_frontmatter(prior_text)
    )
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
