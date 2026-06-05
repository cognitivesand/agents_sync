"""Unit tests for the first pure planner step — recover_identity (rebuild S5).

`recover_identity` partitions this poll's surface observations into *managed*
(grouped under an `artifact_id` recovered from a well-formed embedded id, else from
the recorded state that owns the surface's location) and *candidates* (the id-less
remainder). It is the FR-11 guarantee made executable: an id is *recovered*, never
minted, and recovered independently of the rest of the metadata (proposal §7.1).
These are pure in-memory tests — no filesystem, no clock, no mocks.
"""

from __future__ import annotations

from pathlib import Path

from agents_sync.domain_model.observation import SurfaceObservation
from agents_sync.domain_model.plan.recover_identity import recover_identity
from agents_sync.domain_model.sync_state import ArtifactRecord, RecordedSurface, SyncState
from agents_sync.domain_model.tool_surface import SurfaceFormat, ToolSurface

_MARKDOWN = SurfaceFormat(dialect="markdown_frontmatter")
# Two distinct canonical UUIDv4 ids and one malformed id, fixed for determinism.
_ID_X = "11111111-1111-4111-8111-111111111111"
_ID_Y = "22222222-2222-4222-9222-222222222222"
_MALFORMED_ID = "not-a-canonical-uuid"


def _observation(tool: str, path: str, embedded_id: str | None) -> SurfaceObservation:
    surface = ToolSurface(
        tool=tool,
        kind="agent",
        location=Path(path),
        surface_format=_MARKDOWN,
    )
    return SurfaceObservation(tool_surface=surface, embedded_id=embedded_id)


def _state_owning(artifact_id: str, tool: str, path: str) -> SyncState:
    recorded = RecordedSurface(location=Path(path), content_digest="")
    return SyncState(records={artifact_id: ArtifactRecord(surfaces={tool: recorded})})


def test_well_formed_embedded_id_is_recovered_not_minted() -> None:
    observation = _observation("claude", "/u/.claude/agents/reviewer.md", _ID_X)

    recovery = recover_identity([observation], SyncState())

    assert recovery.managed == {_ID_X: (observation,)}
    assert recovery.candidates == ()


def test_id_less_surface_at_a_recorded_location_recovers_the_recorded_id() -> None:
    path = "/u/.claude/agents/reviewer.md"
    observation = _observation("claude", path, None)

    recovery = recover_identity([observation], _state_owning(_ID_Y, "claude", path))

    assert recovery.managed == {_ID_Y: (observation,)}
    assert recovery.candidates == ()


def test_id_less_surface_at_an_unowned_location_is_a_candidate() -> None:
    observation = _observation("claude", "/u/.claude/agents/new.md", None)

    recovery = recover_identity([observation], SyncState())

    assert recovery.candidates == (observation,)
    assert recovery.managed == {}


def test_malformed_embedded_id_at_an_unowned_location_is_a_candidate() -> None:
    # A present-but-malformed id tag is not a valid recovery, and no id is minted:
    # the surface falls through to a candidate (FR-11 well-formed precondition).
    observation = _observation("claude", "/u/.claude/agents/new.md", _MALFORMED_ID)

    recovery = recover_identity([observation], SyncState())

    assert recovery.candidates == (observation,)
    assert recovery.managed == {}


def test_malformed_embedded_id_falls_through_to_recorded_location() -> None:
    path = "/u/.claude/agents/reviewer.md"
    observation = _observation("claude", path, _MALFORMED_ID)

    recovery = recover_identity([observation], _state_owning(_ID_Y, "claude", path))

    assert recovery.managed == {_ID_Y: (observation,)}
    assert recovery.candidates == ()


def test_embedded_id_takes_precedence_over_a_conflicting_recorded_owner() -> None:
    # Proposal §7.1: group "by embedded id, then by the state that owns the
    # location" — a well-formed embedded id wins over a different recorded owner.
    path = "/u/.claude/agents/reviewer.md"
    observation = _observation("claude", path, _ID_X)

    recovery = recover_identity([observation], _state_owning(_ID_Y, "claude", path))

    assert recovery.managed == {_ID_X: (observation,)}


def test_surfaces_resolving_to_one_id_are_grouped_together() -> None:
    path = "/u/.claude/agents/reviewer.md"
    by_embedded = _observation("claude", "/u/.claude/agents/reviewer.md", _ID_X)
    by_location = _observation("codex", path, None)

    recovery = recover_identity(
        [by_embedded, by_location],
        _state_owning(_ID_X, "codex", path),
    )

    assert recovery.managed == {_ID_X: (by_embedded, by_location)}
    assert recovery.candidates == ()


def test_recovery_only_ever_yields_embedded_or_recorded_ids() -> None:
    # The FR-11 never-mint guarantee across a mixed poll: every managed id must be
    # an observed embedded id or a recorded id — recover_identity invents none.
    recorded_path = "/u/.claude/agents/recorded.md"
    observations = [
        _observation("claude", "/u/.claude/agents/embedded.md", _ID_X),
        _observation("codex", recorded_path, None),
        _observation("gemini", "/u/.gemini/agents/fresh.md", None),
    ]
    state = _state_owning(_ID_Y, "codex", recorded_path)

    recovery = recover_identity(observations, state)

    known_ids = {_ID_X} | set(state.records)
    assert set(recovery.managed) <= known_ids
    assert recovery.managed == {_ID_X: (observations[0],), _ID_Y: (observations[1],)}
    assert recovery.candidates == (observations[2],)
