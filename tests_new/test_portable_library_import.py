"""Unit tests for the customization-library import (rebuild S23c) — US-12.

``import_library`` restores a library export into the local canonical store. It
reconciles each imported canonical against the local one by the single
``last_modified_wins`` rule (FR-12): the newer content prevails, ties favour the
local artifact. The imported ``last_modified`` is preserved, so re-importing an
unchanged library is a no-op (FR-12 idempotency). Import writes the canonical store
only — never ``state.json`` or any tool root — so the next poll adopts each new
canonical (FR-16/AC-5). A malformed export aborts before any write (AC-9); a
displaced local canonical is archived first when its content changes (NFR-01/07).
The receiver's secret policy governs the import egress (AC-15/16). Real filesystem
via ``tmp_path``; exports are produced by ``export_library`` for round-trip realism.
"""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agents_sync.canonical_store import load_canonical, load_canonical_metadata, save_canonical
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.portable_library import (
    ExportEnvironment,
    PortableLibraryError,
    export_library,
    import_library,
)
from agents_sync.secret_policy import SECRET_POLICY_ACCEPTED, SECRET_POLICY_REFUSED

_ID_A = "11111111-1111-4111-8111-111111111111"
_ID_B = "22222222-2222-4222-8222-222222222222"
_SECRET_ID = "33333333-3333-4333-8333-333333333333"

_ENV = ExportEnvironment(
    now=datetime(2026, 6, 20, tzinfo=UTC),
    source_host="source-host",
    source_platform="TestOS",
    agents_sync_version="9.9.9",
)


def _agent(artifact_id: str, body: str = "Be terse.\n") -> CanonicalDocument:
    return CanonicalDocument(artifact_id=artifact_id, kind="agent", name="reviewer", body=body)


def _secret_server(artifact_id: str = _SECRET_ID) -> CanonicalDocument:
    return CanonicalDocument(
        artifact_id=artifact_id, kind="mcp_server", name="db", env={"API_KEY": "s3cr3t-literal"}
    )


def _exported(
    tmp_path: Path,
    entries: list[tuple[CanonicalDocument, float]],
    *,
    name: str = "lib.zip",
    secret_policy: str = SECRET_POLICY_REFUSED,
) -> Path:
    """Save ``entries`` (document, last_modified) into a fresh source store and export it."""
    source = tmp_path / f"source-{name}"
    for document, last_modified in entries:
        save_canonical(source, document, clock=lambda value=last_modified: value)
    export_path = tmp_path / name
    export_library(source, export_path, secret_policy=secret_policy, environment=_ENV)
    return export_path


def _hand_written_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return path


def _manifest_bytes(**overrides: Any) -> bytes:
    manifest = {"schema_version": 1, "artifact_count": 1, "contains_secret_literals": False}
    manifest.update(overrides)
    return json.dumps(manifest).encode("utf-8")


def _reexported_with_manifest(source_path: Path, target_path: Path, **overrides: Any) -> Path:
    """Copy a zip, replacing only its ``manifest.json`` with one carrying ``overrides``."""
    with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(target_path, "w") as out:
        for item in source.namelist():
            payload = _manifest_bytes(**overrides) if item == "manifest.json" else source.read(item)
            out.writestr(item, payload)
    return target_path


def test_import_adopts_new_canonicals_writing_canonical_only(tmp_path: Path) -> None:
    export_path = _exported(tmp_path, [(_agent(_ID_A), 1000.0), (_agent(_ID_B), 1234.0)])
    target = tmp_path / "target"

    report = import_library(target, export_path)

    assert load_canonical(target, _ID_A) == _agent(_ID_A).normalised()
    assert load_canonical_metadata(target, _ID_B).last_modified == 1234.0  # source lm preserved
    assert not (target / "state.json").exists()  # canonical-only (FR-16/AC-5)
    assert set(report.accepted) == {_ID_A, _ID_B}


def test_import_overwrites_when_the_import_is_newer(tmp_path: Path) -> None:
    target = tmp_path / "target"
    save_canonical(target, _agent(_ID_A, body="local\n"), clock=lambda: 1000.0)
    export_path = _exported(tmp_path, [(_agent(_ID_A, body="imported\n"), 2000.0)])

    report = import_library(target, export_path, force=True)  # displaces the local (AC-18)

    assert load_canonical(target, _ID_A) == _agent(_ID_A, body="imported\n").normalised()
    assert load_canonical_metadata(target, _ID_A).last_modified == 2000.0
    assert report.accepted == (_ID_A,)


def test_import_skips_when_the_local_is_newer(tmp_path: Path) -> None:
    target = tmp_path / "target"
    save_canonical(target, _agent(_ID_A, body="local\n"), clock=lambda: 2000.0)
    export_path = _exported(tmp_path, [(_agent(_ID_A, body="imported\n"), 1000.0)])

    report = import_library(target, export_path)

    assert load_canonical(target, _ID_A) == _agent(_ID_A, body="local\n").normalised()
    assert report.accepted == ()
    assert report.skipped == (_ID_A,)


def test_reimporting_an_unchanged_library_is_a_noop(tmp_path: Path) -> None:
    export_path = _exported(tmp_path, [(_agent(_ID_A), 1000.0)])
    target = tmp_path / "target"
    import_library(target, export_path)
    before = (target / "canonical" / f"{_ID_A}.json").read_bytes()

    report = import_library(target, export_path)  # FR-12: same lm preserved → tie → skip

    assert report.accepted == ()
    assert report.skipped == (_ID_A,)
    assert (target / "canonical" / f"{_ID_A}.json").read_bytes() == before


def test_secrets_refused_skips_secret_bearing_canonicals(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # The export carries the secret (built under secrets_accepted); the receiver refuses.
    export_path = _exported(
        tmp_path,
        [(_agent(_ID_A), 1000.0), (_secret_server(), 2000.0)],
        secret_policy=SECRET_POLICY_ACCEPTED,
    )
    target = tmp_path / "target"

    caplog.clear()  # drop the fixture export's own secret WARNING; assert only the import egress
    with caplog.at_level(logging.WARNING):
        report = import_library(target, export_path, secret_policy=SECRET_POLICY_REFUSED)

    assert load_canonical(target, _ID_A) == _agent(_ID_A).normalised()
    assert load_canonical(target, _SECRET_ID) is None  # secret-bearing not written
    assert report.skipped_secret == (_SECRET_ID,)
    egress = [
        r for r in caplog.records if r.levelno == logging.WARNING and _SECRET_ID in r.getMessage()
    ]
    assert len(egress) == 1  # exactly one NFR-13 egress WARNING names the skipped secret


def test_secrets_accepted_imports_secret_material_verbatim(tmp_path: Path) -> None:
    export_path = _exported(
        tmp_path,
        [(_secret_server(), 2000.0)],
        secret_policy=SECRET_POLICY_ACCEPTED,
    )
    target = tmp_path / "target"

    import_library(target, export_path, secret_policy=SECRET_POLICY_ACCEPTED)

    imported = load_canonical(target, _SECRET_ID)
    assert isinstance(imported, CanonicalDocument)
    assert imported.env == {"API_KEY": "s3cr3t-literal"}


def test_import_aborts_on_a_missing_manifest(tmp_path: Path) -> None:
    export_path = _hand_written_zip(
        tmp_path / "lib.zip", {f"canonical/{_ID_A}.json": b'{"artifact_id":"x","kind":"agent"}'}
    )
    target = tmp_path / "target"

    with pytest.raises(PortableLibraryError):
        import_library(target, export_path)

    assert not (target / "canonical").exists()  # nothing written


def test_import_aborts_on_an_unsupported_schema_version(tmp_path: Path) -> None:
    export_path = _exported(tmp_path, [(_agent(_ID_A), 1000.0)])
    # Rewrite the manifest to a future schema version the importer must reject (AC-9).
    rewritten = _reexported_with_manifest(export_path, tmp_path / "future.zip", schema_version=999)
    target = tmp_path / "target"

    with pytest.raises(PortableLibraryError):
        import_library(target, rewritten)

    assert not (target / "canonical").exists()


def test_import_aborts_on_an_unparseable_entry(tmp_path: Path) -> None:
    export_path = _hand_written_zip(
        tmp_path / "lib.zip",
        {"manifest.json": _manifest_bytes(), f"canonical/{_ID_A}.json": b"{truncated"},
    )
    target = tmp_path / "target"

    with pytest.raises(PortableLibraryError):
        import_library(target, export_path)

    assert not (target / "canonical").exists()


def test_import_aborts_on_an_invalid_artifact_id(tmp_path: Path) -> None:
    # AC-9: a canonical/<id>.json whose filename-derived id is not a canonical UUIDv4
    # aborts before any write, naming the offender (NFR-13).
    export_path = _hand_written_zip(
        tmp_path / "lib.zip",
        {
            "manifest.json": _manifest_bytes(),
            "canonical/not-a-uuid.json": b'{"artifact_id":"not-a-uuid","kind":"agent"}',
        },
    )
    target = tmp_path / "target"

    with pytest.raises(PortableLibraryError, match=r"invalid id"):
        import_library(target, export_path)

    assert not (target / "canonical").exists()  # nothing written


def test_import_aborts_on_an_id_filename_mismatch(tmp_path: Path) -> None:
    # AC-9: the document's embedded artifact_id disagreeing with its filename id is a
    # data-corruption shape that must abort before any write (NFR-13).
    export_path = _hand_written_zip(
        tmp_path / "lib.zip",
        {
            "manifest.json": _manifest_bytes(),
            f"canonical/{_ID_A}.json": json.dumps(
                {"artifact_id": _ID_B, "kind": "agent"}
            ).encode("utf-8"),
        },
    )
    target = tmp_path / "target"

    with pytest.raises(PortableLibraryError, match=r"id mismatch"):
        import_library(target, export_path)

    assert not (target / "canonical").exists()  # nothing written


def test_a_displaced_local_canonical_is_archived(tmp_path: Path) -> None:
    target = tmp_path / "target"
    save_canonical(target, _agent(_ID_A, body="local\n"), clock=lambda: 1000.0)
    before = (target / "canonical" / f"{_ID_A}.json").read_bytes()
    export_path = _exported(tmp_path, [(_agent(_ID_A, body="imported\n"), 2000.0)])

    import_library(target, export_path, force=True)  # displaces the local (AC-18)

    archived = list((target / "archive" / _ID_A / "_canonical").iterdir())
    assert len(archived) == 1  # the displaced local canonical's bytes preserved (NFR-01)
    assert archived[0].read_bytes() == before  # verbatim bytes, not just a substring (NFR-01)


def test_a_same_content_newer_import_is_not_archived(tmp_path: Path) -> None:
    # NFR-07: an overwrite that loses no content (same content, newer lm) must not archive.
    target = tmp_path / "target"
    save_canonical(target, _agent(_ID_A, body="same\n"), clock=lambda: 1000.0)
    export_path = _exported(tmp_path, [(_agent(_ID_A, body="same\n"), 2000.0)])

    import_library(target, export_path)

    assert not (target / "archive").exists()
