"""Sync state store — ``state.json`` persistence gateway (US-09 AC-3/AC-4, FR-15).

Persists the ``SyncState`` entity atomically (single intended writer; an
overlapping-daemon race is survived because one atomic write wins entirely and the
loser's delta is recomputed from disk next poll). The state is recomputable, so
every corrupt-load outcome converges to: quarantine the file (bytes preserved,
``store_quarantine``) and return an empty state — except a failed quarantine move,
which fails closed. Surface locations serialize tagged: a per-file path as
``{"path": ...}``, a keyed-map slot as ``{"file": ..., "slot": ...}``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents_sync.atomic_file_writer import write_text_atomic
from agents_sync.domain_model.sync_state import (
    ArtifactRecord,
    RecordedSurface,
    SurfaceLocation,
    SyncState,
)
from agents_sync.domain_model.tool_surface import KeyedMapSlot
from agents_sync.store_quarantine import quarantine_corrupt_file

STATE_SCHEMA_VERSION = 1


def save_sync_state(state_dir: Path, sync_state: SyncState) -> None:
    """Persist ``sync_state`` atomically with the schema version stamped (byte-stable)."""
    envelope = {
        "schema_version": STATE_SCHEMA_VERSION,
        "records": {
            artifact_id: _record_to_dict(record)
            for artifact_id, record in sync_state.records.items()
        },
    }
    write_text_atomic(
        _state_file_path(state_dir),
        json.dumps(envelope, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )


def load_sync_state(state_dir: Path) -> SyncState:
    """Return the recorded state; absent or corrupt (quarantined) loads as empty."""
    path = _state_file_path(state_dir)
    if not path.exists():
        return SyncState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("root is not a JSON object")
        if data.get("schema_version") != STATE_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {data.get('schema_version')!r}")
        return _state_from_dict(data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        # The state is recomputable from disk: quarantine (fail-closed inside) and
        # start empty rather than half-load a damaged record set.
        quarantine_corrupt_file(state_dir, path, str(error))
        return SyncState()


def _state_file_path(state_dir: Path) -> Path:
    return state_dir / "state.json"


def _record_to_dict(record: ArtifactRecord) -> dict[str, Any]:
    return {
        "name": record.name,
        "canonical_digest": record.canonical_digest,
        "surfaces": {
            tool: {
                "location": _location_to_dict(surface.location),
                "content_digest": surface.content_digest,
            }
            for tool, surface in record.surfaces.items()
        },
    }


def _location_to_dict(location: SurfaceLocation) -> dict[str, str]:
    if isinstance(location, KeyedMapSlot):
        return {"file": str(location.file), "slot": location.slot}
    return {"path": str(location)}


def _state_from_dict(data: dict[str, Any]) -> SyncState:
    records_data = data.get("records")
    if not isinstance(records_data, dict):
        raise ValueError("records is not a JSON object")
    return SyncState(
        records={
            str(artifact_id): _record_from_dict(record_data)
            for artifact_id, record_data in records_data.items()
        }
    )


def _record_from_dict(data: Any) -> ArtifactRecord:
    if not isinstance(data, dict):
        raise ValueError("artifact record is not a JSON object")
    # Saves always write every key: a record without them is damage, not a minimal
    # record — strictness routes it to quarantine instead of a silent partial load.
    missing_keys = [key for key in ("name", "canonical_digest", "surfaces") if key not in data]
    if missing_keys:
        raise ValueError(f"artifact record missing keys: {missing_keys}")
    surfaces_data = data["surfaces"]
    if not isinstance(surfaces_data, dict):
        raise ValueError("record surfaces is not a JSON object")
    return ArtifactRecord(
        name=str(data["name"]),
        canonical_digest=str(data["canonical_digest"]),
        surfaces={
            str(tool): _surface_from_dict(surface_data)
            for tool, surface_data in surfaces_data.items()
        },
    )


def _surface_from_dict(data: Any) -> RecordedSurface:
    if not isinstance(data, dict):
        raise ValueError("recorded surface is not a JSON object")
    # Same strictness as the record level: saves always write both keys.
    missing_keys = [key for key in ("location", "content_digest") if key not in data]
    if missing_keys:
        raise ValueError(f"recorded surface missing keys: {missing_keys}")
    return RecordedSurface(
        location=_location_from_dict(data["location"]),
        content_digest=str(data["content_digest"]),
    )


def _location_from_dict(data: Any) -> SurfaceLocation:
    if isinstance(data, dict) and "slot" in data and "file" in data:
        return KeyedMapSlot(file=Path(str(data["file"])), slot=str(data["slot"]))
    if isinstance(data, dict) and "path" in data:
        return Path(str(data["path"]))
    raise ValueError(f"recorded surface location has an unknown shape: {data!r}")
