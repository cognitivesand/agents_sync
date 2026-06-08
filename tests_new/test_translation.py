"""Unit tests for the translation seam's dialect dispatch (rebuild S9).

`file_to_canonical` / `canonical_to_file` / `extract_artifact_id` are the single
translation entry points; they dispatch on `tool_surface.surface_format.dialect` to
a dialect mechanism. These tests cover the dispatch contract itself — that a known
dialect is routed and an unknown one fails loud — independent of any one dialect's
wire behaviour (which is covered per-dialect, e.g. test_markdown_frontmatter).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import SurfaceFormat, ToolSurface
from agents_sync.translation import (
    canonical_to_file,
    extract_artifact_id,
    file_to_canonical,
)

_ID = "11111111-1111-4111-8111-111111111111"
_MARKDOWN = SurfaceFormat(
    dialect="markdown_frontmatter",
    id_field="pair_id",
    known_fields=(("name", "name"),),
)


def _surface(dialect_format: SurfaceFormat) -> ToolSurface:
    return ToolSurface(
        tool="claude",
        kind="agent",
        location=Path("/u/.claude/agents/reviewer.md"),
        surface_format=dialect_format,
    )


def test_a_known_dialect_is_routed_to_its_mechanism() -> None:
    # The markdown dialect is registered, so a markdown surface translates rather
    # than raising "unknown dialect" — the round-trip proves the route reached it.
    surface = _surface(_MARKDOWN)
    text = "---\npair_id: " + _ID + "\nname: reviewer\n---\nbody\n"

    canonical = file_to_canonical(text, surface, None)

    assert canonical.name == "reviewer"
    assert "name: reviewer" in canonical_to_file(canonical, surface, None)


def test_file_to_canonical_fails_loud_on_an_unknown_dialect() -> None:
    surface = _surface(SurfaceFormat(dialect="no_such_dialect"))

    with pytest.raises(ValueError, match="no_such_dialect"):
        file_to_canonical("text", surface, None)


def test_canonical_to_file_fails_loud_on_an_unknown_dialect() -> None:
    surface = _surface(SurfaceFormat(dialect="no_such_dialect"))
    canonical = CanonicalDocument(artifact_id=_ID, kind="agent", name="reviewer")

    with pytest.raises(ValueError, match="no_such_dialect"):
        canonical_to_file(canonical, surface, None)


def test_extract_artifact_id_fails_loud_on_an_unknown_dialect() -> None:
    # extract_artifact_id never raises on malformed *text*, but an unregistered
    # dialect is a registry/programming error, not malformed input — fail loud.
    surface = _surface(SurfaceFormat(dialect="no_such_dialect"))

    with pytest.raises(ValueError, match="no_such_dialect"):
        extract_artifact_id("text", surface)
