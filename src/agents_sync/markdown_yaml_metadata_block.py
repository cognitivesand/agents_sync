"""Markdown YAML metadata-block primitives shared by Markdown-based adapters.

Historically each adapter (claude_io, antigravity_io, opencode_io, codex_io,
cursor_io, copilot_io, gemini_cli_io, rules_io, and slash_command_io)
hand-rolled the same 14-line parse-prelude (BOM strip + frontmatter regex
match + YAML load + isinstance-dict guard) with subtly different error
messages, and three of them imported the underscore-prefixed helpers from
``claude_io`` despite the helpers not being Claude-specific. This module
collects the helpers for the YAML metadata block at the top of Markdown
files under one public surface, so a new adapter is a one-line consumer
and a change to BOM handling or YAML loader options is a one-place change.

Public API:

- ``FRONTMATTER_RE``
- ``make_yaml`` — ``ruamel.yaml.YAML`` factory with the project's
  round-trip settings (preserve quotes, 4096 width, mapping=2/sequence=4
  indent).
- ``yaml_load`` / ``yaml_dump``
- ``strip_bom_prefix``
- ``normalize_markdown_text`` (alias of ``strip_bom_prefix`` kept for
  readability at call sites).
- ``split_frontmatter(text, *, label)`` — returns ``(frontmatter_dict,
  body_text)``. ``label`` is the human-readable adapter name used in the
  exception message when the frontmatter is not a YAML mapping; raises
  :class:`AdapterParseError` so callers can catch one shared type.
- ``frontmatter_for_render(prior_text)`` — load the prior frontmatter as
  a ruamel-mutable dict (or an empty one) for render-time mutation.
- ``AdapterParseError`` — common parse-error type across adapters.
"""
from __future__ import annotations

import io
import re
from collections.abc import Iterable
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


FRONTMATTER_RE = re.compile(
    r"\A(?:﻿)?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z",
    re.DOTALL,
)

_CORRUPTED_UTF8_BOM = "ï»¿"


class AdapterParseError(ValueError):
    """A Markdown-frontmatter adapter failed to parse its input.

    Common exception type for every parser in :mod:`claude_io`,
    :mod:`codex_io`, :mod:`antigravity_io`, and :mod:`opencode_io`. The
    string includes the adapter ``label`` so callers can disambiguate.
    """


def make_yaml() -> YAML:
    """``ruamel.yaml.YAML`` configured for round-trip preservation.

    The composer is the bounded variant defined in
    :mod:`agents_sync.parser_bounds`, which counts node compositions and
    aborts pathological YAML alias graphs (Phase 3 / SEC-C-01). The cap
    is set high enough that legitimate frontmatter never trips it.
    """
    # Lazy import — parser_bounds imports AdapterParseError from this
    # module; bringing parser_bounds in at module load time would form a
    # cycle. The composer class is a stable callable cached by ruamel
    # internals after first construction.
    from agents_sync.parser_bounds import make_bounded_composer_class

    yml = YAML(typ="rt")
    yml.preserve_quotes = True
    yml.width = 4096
    yml.indent(mapping=2, sequence=4, offset=2)
    yml.Composer = make_bounded_composer_class()
    return yml


def yaml_load(text: str) -> Any:
    """Parse a YAML document. Empty input returns ``None``."""
    if not text.strip():
        return None
    return make_yaml().load(io.StringIO(text))


def yaml_dump(data: Any) -> str:
    """Round-trip-friendly dump of a ruamel-loaded structure."""
    buf = io.StringIO()
    make_yaml().dump(data, buf)
    return buf.getvalue()


def render_markdown_with_metadata_block(
    metadata: dict[str, Any],
    body: str,
    *,
    final_newline: bool = True,
) -> str:
    """Render ``metadata`` as a leading YAML block followed by Markdown body."""
    rendered_metadata = yaml_dump(metadata).rstrip("\n")
    suffix = "\n" if final_newline and body else ""
    if body:
        return f"---\n{rendered_metadata}\n---\n{body}{suffix}"
    return f"---\n{rendered_metadata}\n---\n"


def strip_bom_prefix(text: str) -> str:
    """Strip a real UTF-8 BOM and the common 'BOM-rendered-as-text' bytes.

    The second form (``ï»¿``) shows up when an editor opens
    a file in a non-UTF-8 codepage and re-saves the BOM as literal
    characters. We treat both as no-op text prefixes.
    """
    if text.startswith("﻿"):
        return text[1:]
    if text.startswith(_CORRUPTED_UTF8_BOM):
        return text[3:]
    return text


def normalize_markdown_text(text: str) -> str:
    """Strip BOMs from incoming Markdown text. Alias of
    :func:`strip_bom_prefix`; the two names live side by side because
    call sites read more clearly when the operation is described as
    "normalise text" at parse time and as "strip BOM" elsewhere.
    """
    return strip_bom_prefix(text)


def split_frontmatter(
    text: str, *, label: str, strip_body: bool = True,
) -> tuple[dict[str, Any], str]:
    """Split a Markdown document into ``(frontmatter_dict, body_text)``.

    - ``label`` is included in the :class:`AdapterParseError` raised when
      the frontmatter is not a YAML mapping.
    - Empty or missing frontmatter yields ``({}, body)`` with ``body``
      equal to the BOM-stripped input.
    - ``frontmatter_dict`` is a plain ``dict`` (the ruamel ordered-mapping
      is converted at the boundary so downstream code can treat it as a
      normal mapping).
    - ``strip_body=True`` (default) trims leading/trailing whitespace from
      the body — appropriate for SKILL.md / agent .md style files where
      the body is paragraph content. ``strip_body=False`` preserves the
      body verbatim — required for prompt-template artifacts (slash
      commands) where trailing whitespace is semantically significant.
    """
    # Lazy import (parser_bounds depends on this module for
    # AdapterParseError).
    from agents_sync.parser_bounds import enforce_frontmatter_window

    text = normalize_markdown_text(text)
    # Bound the FRONTMATTER_RE linear scan to the leading window so a
    # multi-MB body cannot make the regex walk the whole document. The
    # body past the window is preserved by slicing the original text
    # from ``match.start(2)`` after the regex finds the frontmatter span
    # inside ``head``.
    head = enforce_frontmatter_window(text)
    match = FRONTMATTER_RE.match(head)
    if match is None:
        body = strip_bom_prefix(text)
        if strip_body:
            body = body.strip()
        return {}, body
    raw_frontmatter = match.group(1)
    body_raw = text[match.start(2):]
    body = strip_bom_prefix(body_raw)
    if strip_body:
        body = body.strip()
    loaded = yaml_load(raw_frontmatter)
    if loaded is None:
        return {}, body
    if not isinstance(loaded, dict):
        raise AdapterParseError(
            f"{label} frontmatter must be a YAML mapping"
        )
    return dict(loaded), body


def set_or_remove_empty_metadata_field(
    metadata: dict[str, Any],
    key: str,
    value: Any,
) -> None:
    """Set ``key`` to ``value`` or remove it when the value means "absent"."""
    if value is None or value == "" or value == []:
        metadata.pop(key, None)
        return
    metadata[key] = value


def as_string_list(value: Any) -> list[str]:
    """Coerce a metadata scalar/list value to a list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value)]


def metadata_subset(
    metadata: dict[str, Any],
    field_names: Iterable[str],
) -> dict[str, Any]:
    """Return the fields from ``metadata`` that are named in ``field_names``."""
    return {
        field_name: metadata[field_name]
        for field_name in field_names
        if field_name in metadata
    }


def unknown_metadata_fields(
    metadata: dict[str, Any],
    known_fields: frozenset[str],
    foreign_fields: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Return fields not owned by this adapter or known to another adapter."""
    return {
        key: value
        for key, value in metadata.items()
        if key not in known_fields and key not in foreign_fields
    }


def frontmatter_for_render(prior_text: str | None) -> Any:
    """Return a ruamel-mutable mapping seeded from ``prior_text``.

    If ``prior_text`` is empty or has no frontmatter, returns an empty
    ruamel mapping (suitable for fresh renders). If the prior
    frontmatter is unparseable or not a mapping, also returns an empty
    mapping — callers preserve user formatting on the happy path and
    safely fall back when the user's frontmatter is malformed.
    """
    yml = make_yaml()
    if prior_text is None:
        return yml.load("{}\n")
    prior_text = normalize_markdown_text(prior_text)
    prior_match = FRONTMATTER_RE.match(prior_text)
    if prior_match is None:
        return yml.load("{}\n")
    raw, _ = prior_match.groups()
    try:
        loaded = yaml_load(raw)
    except YAMLError:
        return yml.load("{}\n")
    if isinstance(loaded, dict):
        return loaded
    return yml.load("{}\n")


def extract_pair_id_from_md(text: str) -> str | None:
    """Return the ``pair_id`` from a Markdown document's frontmatter,
    or ``None`` if absent / unparseable. Adapter-agnostic — every Markdown-
    shaped adapter (Claude, Antigravity, opencode, Codex skill) uses the
    same convention of a string ``pair_id`` field in YAML frontmatter.
    """
    text = normalize_markdown_text(text)
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    loaded = yaml_load(match.group(1))
    if isinstance(loaded, dict) and isinstance(loaded.get("pair_id"), str):
        return loaded["pair_id"]
    return None


__all__ = [
    "AdapterParseError",
    "FRONTMATTER_RE",
    "as_string_list",
    "extract_pair_id_from_md",
    "frontmatter_for_render",
    "make_yaml",
    "metadata_subset",
    "normalize_markdown_text",
    "render_markdown_with_metadata_block",
    "set_or_remove_empty_metadata_field",
    "split_frontmatter",
    "strip_bom_prefix",
    "unknown_metadata_fields",
    "yaml_dump",
    "yaml_load",
]
