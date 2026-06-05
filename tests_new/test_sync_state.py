"""Unit tests for the recorded-state input types (rebuild S5).

`SyncState` is what the daemon recorded last poll (`artifact_id -> ArtifactRecord`);
`ArtifactRecord` holds where that artifact's surfaces live. S5 builds only the
recorded surface *locations* that `recover_identity` reads to recover an id-less
surface by ownership; the recorded digests / kind / canonical_digest grow with
their consumers in S6. The load-bearing contract under test is the value objects'
immutability — frozen alone would leave the surface map mutable in place, the trap
the canonical-document deep-freeze already proved (so the maps are exposed
read-only).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.domain_model.sync_state import ArtifactRecord, SyncState

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
_LOCATION = Path("/home/u/.claude/agents/reviewer.md")


def test_artifact_record_exposes_its_surfaces_read_only() -> None:
    record = ArtifactRecord(surfaces={"claude": _LOCATION})

    with pytest.raises(TypeError):
        record.surfaces["codex"] = Path("/elsewhere.md")  # type: ignore[index]


def test_sync_state_exposes_its_records_read_only() -> None:
    state = SyncState(records={_ARTIFACT_ID: ArtifactRecord(surfaces={"claude": _LOCATION})})

    with pytest.raises(TypeError):
        state.records["other"] = ArtifactRecord()  # type: ignore[index]


def test_recorded_state_is_value_equal_by_content() -> None:
    one = SyncState(records={_ARTIFACT_ID: ArtifactRecord(surfaces={"claude": _LOCATION})})
    same = SyncState(records={_ARTIFACT_ID: ArtifactRecord(surfaces={"claude": _LOCATION})})
    other = SyncState(records={_ARTIFACT_ID: ArtifactRecord(surfaces={"codex": _LOCATION})})

    assert one == same
    assert one != other
