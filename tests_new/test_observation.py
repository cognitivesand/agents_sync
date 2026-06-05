"""Unit tests for the surface-observation input type (rebuild S5).

`SurfaceObservation` is what the read phase (S17) gathers for one tool surface in
one poll; the pure planner consumes it. S5 builds only the two fields
`recover_identity` reads — the `tool_surface` and the `embedded_id` recovered in
isolation (FR-11); the digest / mtime / parsed-canonical fields grow with their
consumers in S6 / S17. The contract under test is the immutable value-object
contract the planner relies on (it groups and compares observations).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.observation import ParseFailure, SurfaceObservation
from agents_sync.domain_model.tool_surface import SurfaceFormat, ToolSurface

_SURFACE = ToolSurface(
    tool="claude",
    kind="agent",
    location=Path("/home/u/.claude/agents/reviewer.md"),
    surface_format=SurfaceFormat(dialect="markdown_frontmatter"),
)
_EMBEDDED_ID = "11111111-1111-4111-8111-111111111111"


def test_surface_observation_is_immutable() -> None:
    observation = SurfaceObservation(tool_surface=_SURFACE, embedded_id=_EMBEDDED_ID)

    with pytest.raises(FrozenInstanceError):
        observation.embedded_id = None  # type: ignore[misc]


def test_surface_observations_are_value_equal_by_their_fields() -> None:
    one = SurfaceObservation(tool_surface=_SURFACE, embedded_id=_EMBEDDED_ID)
    same = SurfaceObservation(tool_surface=_SURFACE, embedded_id=_EMBEDDED_ID)
    id_less = SurfaceObservation(tool_surface=_SURFACE, embedded_id=None)

    assert one == same
    assert one != id_less


def test_surface_observation_carries_the_read_phase_fields() -> None:
    # The fields S6a's reconciliation reads: the change-detection digest, the
    # conflict-tiebreak modified_time, and the parsed canonical (or parse failure).
    parsed = CanonicalDocument(artifact_id=_EMBEDDED_ID, kind="agent", name="reviewer")
    observation = SurfaceObservation(
        tool_surface=_SURFACE,
        content_digest="d1",
        modified_time=12.5,
        parsed=parsed,
        embedded_id=_EMBEDDED_ID,
    )

    assert observation.content_digest == "d1"
    assert observation.modified_time == 12.5
    assert observation.parsed is parsed


def test_parse_failure_is_an_immutable_value_object() -> None:
    a_failure = ParseFailure(reason="bad front-matter")

    assert a_failure == ParseFailure(reason="bad front-matter")
    assert a_failure != ParseFailure(reason="other")
    with pytest.raises(FrozenInstanceError):
        a_failure.reason = "changed"  # type: ignore[misc]
