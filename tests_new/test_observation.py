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

from agents_sync.domain_model.observation import SurfaceObservation
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
