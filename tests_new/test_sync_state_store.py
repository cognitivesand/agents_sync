"""Unit tests for the sync state store gateway (rebuild S15b, US-09 AC-3/AC-4, FR-15).

``state.json`` persists the ``SyncState`` entity (artifact records with their
recorded surfaces). The state is recomputable from disk, so every corrupt-load
outcome converges to: quarantine the file (bytes preserved) and return an empty
state for this poll — except a failed quarantine move, which fails closed.
Real filesystem via tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agents_sync.domain_model.sync_state import ArtifactRecord, RecordedSurface, SyncState
from agents_sync.domain_model.tool_surface import KeyedMapSlot
from agents_sync.store_quarantine import QuarantineError
from agents_sync.sync_state_store import (
    STATE_SCHEMA_VERSION,
    load_sync_state,
    save_sync_state,
)

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"


def _populated_state() -> SyncState:
    return SyncState(
        records={
            _ARTIFACT_ID: ArtifactRecord(
                name="code reviewer",
                canonical_digest="abc123",
                surfaces={
                    "claude": RecordedSurface(
                        location=Path("/u/.claude/agents/code-reviewer.md"),
                        content_digest="d1",
                    ),
                    "cursor": RecordedSurface(
                        location=KeyedMapSlot(file=Path("/u/.cursor/mcp.json"), slot="github"),
                        content_digest="d2",
                    ),
                },
            )
        }
    )


def _state_file(state_dir: Path) -> Path:
    return state_dir / "state.json"


def _quarantined_files(state_dir: Path) -> list[Path]:
    quarantine_dir = state_dir / "quarantine"
    return sorted(quarantine_dir.iterdir()) if quarantine_dir.is_dir() else []


# --- round-trip -------------------------------------------------------------------


def test_a_saved_state_loads_back_equal(tmp_path: Path) -> None:
    # Both surface-location shapes (per-file path and keyed-map slot) survive the trip.
    state = _populated_state()

    save_sync_state(tmp_path, state)

    assert load_sync_state(tmp_path) == state


def test_an_empty_state_round_trips(tmp_path: Path) -> None:
    save_sync_state(tmp_path, SyncState())

    assert load_sync_state(tmp_path) == SyncState()


def test_the_stored_file_carries_the_schema_version(tmp_path: Path) -> None:
    save_sync_state(tmp_path, SyncState())

    stored = json.loads(_state_file(tmp_path).read_text())

    assert stored["schema_version"] == STATE_SCHEMA_VERSION


def test_saves_are_byte_stable(tmp_path: Path) -> None:
    # Identical states write identical bytes — no churn across polls.
    save_sync_state(tmp_path, _populated_state())
    first_bytes = _state_file(tmp_path).read_bytes()
    save_sync_state(tmp_path, _populated_state())

    assert _state_file(tmp_path).read_bytes() == first_bytes


def test_an_absent_state_file_loads_as_empty(tmp_path: Path) -> None:
    assert load_sync_state(tmp_path) == SyncState()


# --- corrupt -> quarantine + empty (recompute-from-disk heals, US-09 AC-3/AC-4) -----


def test_unparseable_json_is_quarantined_and_loads_empty(tmp_path: Path) -> None:
    _state_file(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    _state_file(tmp_path).write_text("{truncated")

    assert load_sync_state(tmp_path) == SyncState()
    assert not _state_file(tmp_path).exists()  # moved, not copied
    [quarantined] = _quarantined_files(tmp_path)
    assert quarantined.read_text() == "{truncated"  # bytes preserved for recovery


def test_a_non_object_root_is_quarantined(tmp_path: Path) -> None:
    _state_file(tmp_path).write_text("[1, 2]")

    assert load_sync_state(tmp_path) == SyncState()
    assert len(_quarantined_files(tmp_path)) == 1


def test_an_unsupported_schema_version_is_quarantined(tmp_path: Path) -> None:
    _state_file(tmp_path).write_text(json.dumps({"schema_version": 999, "records": {}}))

    assert load_sync_state(tmp_path) == SyncState()
    assert len(_quarantined_files(tmp_path)) == 1


def test_a_malformed_record_shape_is_quarantined(tmp_path: Path) -> None:
    # A structurally wrong record (location tag neither path nor slot) corrupts the
    # whole file: the state is recomputable, so quarantine + empty beats a partial load.
    stored = {
        "schema_version": STATE_SCHEMA_VERSION,
        "records": {
            _ARTIFACT_ID: {
                "name": "x",
                "canonical_digest": "d",
                "surfaces": {"claude": {"location": {"bogus": True}, "content_digest": "d"}},
            }
        },
    }
    _state_file(tmp_path).write_text(json.dumps(stored))

    assert load_sync_state(tmp_path) == SyncState()
    assert len(_quarantined_files(tmp_path)) == 1


def test_a_record_missing_required_keys_is_quarantined(tmp_path: Path) -> None:
    # Saves always write every key; a record without them is damage, not a minimal
    # record — quarantine + empty beats silently loading defaulted fields.
    stored = {"schema_version": STATE_SCHEMA_VERSION, "records": {_ARTIFACT_ID: {}}}
    _state_file(tmp_path).write_text(json.dumps(stored))

    assert load_sync_state(tmp_path) == SyncState()
    assert len(_quarantined_files(tmp_path)) == 1


def test_a_surface_missing_its_digest_is_quarantined(tmp_path: Path) -> None:
    # The same strictness one level down: saves always write content_digest, so a
    # surface without it is damage, not a minimal surface.
    stored = {
        "schema_version": STATE_SCHEMA_VERSION,
        "records": {
            _ARTIFACT_ID: {
                "name": "x",
                "canonical_digest": "d",
                "surfaces": {"claude": {"location": {"path": "/u/a.md"}}},
            }
        },
    }
    _state_file(tmp_path).write_text(json.dumps(stored))

    assert load_sync_state(tmp_path) == SyncState()
    assert len(_quarantined_files(tmp_path)) == 1


def test_a_failed_quarantine_move_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    _state_file(tmp_path).write_text("{truncated")

    def immovable(src: Any, dst: Any) -> None:
        raise OSError("read-only filesystem")

    monkeypatch.setattr(os, "replace", immovable)
    with pytest.raises(QuarantineError):
        load_sync_state(tmp_path)

    assert _state_file(tmp_path).read_text() == "{truncated"
