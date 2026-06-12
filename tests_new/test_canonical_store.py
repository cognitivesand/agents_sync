"""Unit tests for the canonical store gateway (rebuild S15a, US-09 AC-4 / FR-14).

The store persists one JSON file per artifact under ``store_dir/canonical/`` and
returns exactly the planner's stored-canonical input type:
``CanonicalDocument`` (loaded), ``CorruptCanonical`` (quarantined, bytes preserved),
or ``None`` (absent). Corrupt files are MOVED to ``store_dir/quarantine/`` before
the load returns — fail-closed if the move fails. Real filesystem via tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agents_sync.canonical_store import (
    CANONICAL_SCHEMA_VERSION,
    list_canonical_ids,
    load_canonical,
    save_canonical,
)
from agents_sync.domain_model.artifact_identity import InvalidArtifactId
from agents_sync.domain_model.canonical_document import CanonicalDocument, CorruptCanonical
from agents_sync.store_quarantine import QuarantineError

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
_OTHER_ID = "22222222-2222-4222-8222-222222222222"


def _document(**overrides: Any) -> CanonicalDocument:
    fields: dict[str, Any] = {
        "artifact_id": _ARTIFACT_ID,
        "kind": "agent",
        "name": "code reviewer",
        "body": "Be terse.\n",
        "tools": ("read", "edit"),
    }
    fields.update(overrides)
    return CanonicalDocument(**fields)


def _canonical_file(store_dir: Path, artifact_id: str = _ARTIFACT_ID) -> Path:
    return store_dir / "canonical" / f"{artifact_id}.json"


def _quarantined_files(store_dir: Path) -> list[Path]:
    quarantine_dir = store_dir / "quarantine"
    return sorted(quarantine_dir.iterdir()) if quarantine_dir.is_dir() else []


# --- round-trip -------------------------------------------------------------------


def test_a_saved_document_loads_back_equal(tmp_path: Path) -> None:
    document = _document()

    save_canonical(tmp_path, document)
    loaded = load_canonical(tmp_path, _ARTIFACT_ID)

    assert loaded == document.normalised()


def test_save_normalises_for_byte_stable_output(tmp_path: Path) -> None:
    # Two saves of unnormalised-but-equivalent documents produce identical bytes,
    # so digests are stable across polls and the daemon never churns (FR-14).
    save_canonical(tmp_path, _document(tools=("read", "edit")))
    first_bytes = _canonical_file(tmp_path).read_bytes()
    save_canonical(tmp_path, _document(tools=("edit", "read")))

    assert _canonical_file(tmp_path).read_bytes() == first_bytes


def test_the_stored_file_carries_the_schema_version(tmp_path: Path) -> None:
    save_canonical(tmp_path, _document())

    stored = json.loads(_canonical_file(tmp_path).read_text())

    assert stored["schema_version"] == CANONICAL_SCHEMA_VERSION


def test_an_absent_canonical_loads_as_none(tmp_path: Path) -> None:
    assert load_canonical(tmp_path, _ARTIFACT_ID) is None


def test_an_invalid_artifact_id_is_a_recipe_error(tmp_path: Path) -> None:
    # A malformed id is a caller bug, not corrupt content — fail loud, no quarantine.
    with pytest.raises(InvalidArtifactId):
        load_canonical(tmp_path, "not-a-uuid")


# --- corrupt -> quarantine (US-09 AC-4) ---------------------------------------------


def test_unparseable_json_is_quarantined_and_reported_corrupt(tmp_path: Path) -> None:
    path = _canonical_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{truncated")

    result = load_canonical(tmp_path, _ARTIFACT_ID)

    assert isinstance(result, CorruptCanonical)
    assert not path.exists()  # moved, not copied — the next poll sees it as absent
    [quarantined] = _quarantined_files(tmp_path)
    assert quarantined.read_text() == "{truncated"  # bytes preserved for recovery


def test_a_non_object_root_is_quarantined(tmp_path: Path) -> None:
    path = _canonical_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('["not", "an", "object"]')

    assert isinstance(load_canonical(tmp_path, _ARTIFACT_ID), CorruptCanonical)
    assert len(_quarantined_files(tmp_path)) == 1


def test_a_missing_required_field_is_quarantined(tmp_path: Path) -> None:
    path = _canonical_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": CANONICAL_SCHEMA_VERSION, "name": "x"}))

    result = load_canonical(tmp_path, _ARTIFACT_ID)

    assert isinstance(result, CorruptCanonical)
    assert "artifact_id" in result.reason


def test_an_unsupported_schema_version_is_quarantined(tmp_path: Path) -> None:
    save_canonical(tmp_path, _document())
    stored = json.loads(_canonical_file(tmp_path).read_text())
    stored["schema_version"] = 999
    _canonical_file(tmp_path).write_text(json.dumps(stored))

    result = load_canonical(tmp_path, _ARTIFACT_ID)

    assert isinstance(result, CorruptCanonical)
    assert "schema_version" in result.reason


def test_a_type_corrupt_field_is_quarantined(tmp_path: Path) -> None:
    # A wrong container type (tools: 5) corrupts the document just like a missing
    # field: it must quarantine, not crash the poll loop on every load forever.
    path = _canonical_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": CANONICAL_SCHEMA_VERSION,
                "artifact_id": _ARTIFACT_ID,
                "kind": "agent",
                "tools": 5,
            }
        )
    )

    assert isinstance(load_canonical(tmp_path, _ARTIFACT_ID), CorruptCanonical)
    assert len(_quarantined_files(tmp_path)) == 1


def test_saving_an_invalid_artifact_id_is_a_recipe_error(tmp_path: Path) -> None:
    # The save side enforces the same id boundary as the load side: no file is
    # ever written under a garbage name.
    with pytest.raises(InvalidArtifactId):
        save_canonical(tmp_path, _document(artifact_id="not-a-uuid"))

    assert not (tmp_path / "canonical").exists()


def test_unreadable_bytes_are_quarantined(tmp_path: Path) -> None:
    path = _canonical_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe invalid utf-8 \xff")

    assert isinstance(load_canonical(tmp_path, _ARTIFACT_ID), CorruptCanonical)
    assert len(_quarantined_files(tmp_path)) == 1


def test_a_failed_quarantine_move_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the corrupt file cannot be moved aside, rebuilding would overwrite it —
    # the load must raise rather than return CorruptCanonical (US-09 AC-4).
    import os

    path = _canonical_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{truncated")

    def immovable(src: Any, dst: Any) -> None:
        raise OSError("read-only filesystem")

    monkeypatch.setattr(os, "replace", immovable)
    with pytest.raises(QuarantineError):
        load_canonical(tmp_path, _ARTIFACT_ID)

    assert path.read_text() == "{truncated"  # the corrupt bytes were not destroyed


def test_an_already_vanished_source_does_not_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The overlapping-daemon race the design survives (US-09 AC-3): the winner already
    # quarantined the file, so the loser's move finds nothing left to protect — it
    # must converge (report corrupt for this poll), not raise QuarantineError.
    import os

    path = _canonical_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{truncated")

    def already_gone(src: Any, dst: Any) -> None:
        raise FileNotFoundError(src)

    monkeypatch.setattr(os, "replace", already_gone)

    assert isinstance(load_canonical(tmp_path, _ARTIFACT_ID), CorruptCanonical)


def test_two_corrupt_loads_quarantine_two_distinct_files(tmp_path: Path) -> None:
    # Quarantine names must not collide when the same artifact corrupts twice.
    for content in ("{first", "{second"):
        path = _canonical_file(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        load_canonical(tmp_path, _ARTIFACT_ID)

    assert len(_quarantined_files(tmp_path)) == 2


# --- listing ------------------------------------------------------------------------


def test_list_canonical_ids_returns_sorted_valid_ids(tmp_path: Path) -> None:
    save_canonical(tmp_path, _document(artifact_id=_OTHER_ID))
    save_canonical(tmp_path, _document())
    (tmp_path / "canonical" / "not-a-uuid.json").write_text("{}")  # skipped, not an id

    assert list_canonical_ids(tmp_path) == [_ARTIFACT_ID, _OTHER_ID]


def test_listing_an_empty_store_returns_no_ids(tmp_path: Path) -> None:
    assert list_canonical_ids(tmp_path) == []
