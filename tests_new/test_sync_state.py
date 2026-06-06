"""Unit tests for the recorded-state input types (rebuild S5, grown in S6a).

`SyncState` is what the daemon recorded last poll (`artifact_id -> ArtifactRecord`);
`ArtifactRecord` holds each surface's recorded `RecordedSurface` (its location and
its content digest at last projection). S6a grew the surface value from a bare
location to `RecordedSurface` so the content rule can detect a change by comparing
an observed digest to the recorded one. The load-bearing contract under test is
the value objects' immutability — frozen alone leaves the surface map mutable in
place, the trap the canonical-document deep-freeze already proved (so the maps are
exposed read-only).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from agents_sync.domain_model.sync_state import ArtifactRecord, RecordedSurface, SyncState

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
_LOCATION = Path("/home/u/.claude/agents/reviewer.md")
_RECORDED = RecordedSurface(location=_LOCATION, content_digest="d1")


def test_recorded_surface_is_an_immutable_value_object() -> None:
    a_surface = RecordedSurface(location=_LOCATION, content_digest="d1")

    assert a_surface == RecordedSurface(location=_LOCATION, content_digest="d1")
    assert a_surface != RecordedSurface(location=_LOCATION, content_digest="d2")
    with pytest.raises(FrozenInstanceError):
        a_surface.content_digest = "changed"  # type: ignore[misc]


def test_artifact_record_carries_its_recorded_name() -> None:
    # The recorded name is what reconcile_known compares the canonical's slug against
    # to detect a rename (S6b); it defaults empty so the field is additive.
    record = ArtifactRecord(name="reviewer", surfaces={"claude": _RECORDED})

    assert record.name == "reviewer"


def test_artifact_record_carries_its_recorded_canonical_digest() -> None:
    # The recorded canonical digest is what reconcile_known compares the stored
    # canonical against to detect an out-of-band change (S6c); additive default.
    record = ArtifactRecord(canonical_digest="abc123", surfaces={"claude": _RECORDED})

    assert record.canonical_digest == "abc123"


def test_artifact_record_exposes_its_surfaces_read_only() -> None:
    record = ArtifactRecord(surfaces={"claude": _RECORDED})

    with pytest.raises(TypeError):
        record.surfaces["codex"] = _RECORDED  # type: ignore[index]


def test_sync_state_exposes_its_records_read_only() -> None:
    state = SyncState(records={_ARTIFACT_ID: ArtifactRecord(surfaces={"claude": _RECORDED})})

    with pytest.raises(TypeError):
        state.records["other"] = ArtifactRecord()  # type: ignore[index]


def test_recorded_state_is_value_equal_by_content() -> None:
    one = SyncState(records={_ARTIFACT_ID: ArtifactRecord(surfaces={"claude": _RECORDED})})
    same = SyncState(records={_ARTIFACT_ID: ArtifactRecord(surfaces={"claude": _RECORDED})})
    other_digest = RecordedSurface(location=_LOCATION, content_digest="d9")
    other = SyncState(records={_ARTIFACT_ID: ArtifactRecord(surfaces={"claude": other_digest})})

    assert one == same
    assert one != other
