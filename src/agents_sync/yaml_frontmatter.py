"""YAML-frontmatter primitives shared by every Markdown-based adapter.

Historically each adapter (claude_io, antigravity_io, opencode_io, codex_io)
hand-rolled the same 14-line parse-prelude (BOM strip + frontmatter regex
match + YAML load + isinstance-dict guard) with subtly different error
messages, and three of them imported the underscore-prefixed helpers from
``claude_io`` despite the helpers not being Claude-specific. This module
collects those helpers under one public surface so a fifth adapter is a
one-line consumer and a change to BOM handling or YAML loader options is
a one-place change.

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
from typing import Any

from ruamel.yaml import YAML


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
    """``ruamel.yaml.YAML`` configured for round-trip preservation."""
    yml = YAML(typ="rt")
    yml.preserve_quotes = True
    yml.width = 4096
    yml.indent(mapping=2, sequence=4, offset=2)
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
    text = normalize_markdown_text(text)
    match = FRONTMATTER_RE.match(text)
    if match is None:
        body = strip_bom_prefix(text)
        if strip_body:
            body = body.strip()
        return {}, body
    raw_frontmatter, body_raw = match.groups()
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
    loaded = yaml_load(raw)
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
    "extract_pair_id_from_md",
    "frontmatter_for_render",
    "make_yaml",
    "normalize_markdown_text",
    "split_frontmatter",
    "strip_bom_prefix",
    "yaml_dump",
    "yaml_load",
]
