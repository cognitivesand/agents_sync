"""Unit tests for the customization-library export (rebuild S23b) — US-12.

``export_library`` writes a single zip capturing every canonical in the store plus
a manifest, read-only against the source state directory (AC-1) and reading each
store file's bytes once for a point-in-time snapshot (AC-2). The secret policy
guards the egress (NFR-15): under ``secrets_refused`` a secret-bearing canonical is
skipped and the manifest flag stays false (AC-12/AC-13); under ``secrets_accepted``
it ships verbatim and the flag is true (AC-14). The zip is materialised atomically,
so a non-writable path aborts with no partial export (AC-4). Real filesystem via
``tmp_path``; the manifest's host/runtime facts are injected for determinism.
"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agents_sync.canonical_store import save_canonical
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.portable_library import (
    PORTABLE_LIBRARY_SCHEMA_VERSION,
    ExportEnvironment,
    PortableLibraryError,
    export_library,
)
from agents_sync.secret_policy import SECRET_POLICY_ACCEPTED, SECRET_POLICY_REFUSED

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
_OTHER_ID = "22222222-2222-4222-8222-222222222222"
_SECRET_ID = "33333333-3333-4333-8333-333333333333"

_ENVIRONMENT = ExportEnvironment(
    now=datetime(2026, 6, 20, 12, 0, tzinfo=UTC),
    source_host="test-host",
    source_platform="TestOS",
    agents_sync_version="9.9.9",
)


def _agent(artifact_id: str = _ARTIFACT_ID, **overrides: Any) -> CanonicalDocument:
    fields: dict[str, Any] = {
        "artifact_id": artifact_id,
        "kind": "agent",
        "name": "code reviewer",
        "body": "Be terse.\n",
    }
    fields.update(overrides)
    return CanonicalDocument(**fields)


def _secret_server(artifact_id: str = _SECRET_ID) -> CanonicalDocument:
    # A literal under ``env`` is a secret finding regardless of shape (NFR-15).
    return CanonicalDocument(
        artifact_id=artifact_id, kind="mcp_server", name="db", env={"API_KEY": "s3cr3t-literal"}
    )


def _read_export(export_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    with zipfile.ZipFile(export_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        entries = {
            name[len("canonical/") : -len(".json")]: json.loads(archive.read(name))
            for name in archive.namelist()
            if name.startswith("canonical/")
        }
    return manifest, entries


def test_export_writes_one_entry_per_canonical_with_manifest(tmp_path: Path) -> None:
    save_canonical(tmp_path, _agent(_ARTIFACT_ID), clock=lambda: 1000.0)
    save_canonical(tmp_path, _agent(_OTHER_ID), clock=lambda: 2000.0)
    export_path = tmp_path / "library.zip"

    report = export_library(
        tmp_path, export_path, secret_policy=SECRET_POLICY_REFUSED, environment=_ENVIRONMENT
    )
    manifest, entries = _read_export(export_path)

    assert set(entries) == {_ARTIFACT_ID, _OTHER_ID}
    assert manifest == {
        "schema_version": PORTABLE_LIBRARY_SCHEMA_VERSION,
        "exported_at": "2026-06-20T12:00:00+00:00",
        "source_host": "test-host",
        "source_platform": "TestOS",
        "agents_sync_version": "9.9.9",
        "artifact_count": 2,
        "contains_secret_literals": False,  # AC-12: refused + no secrets
    }
    assert report.artifact_count == 2
    assert report.skipped_secret_artifacts == ()


def test_export_leaves_the_source_canonicals_unchanged(tmp_path: Path) -> None:
    save_canonical(tmp_path, _agent(), clock=lambda: 1000.0)
    canonical_file = tmp_path / "canonical" / f"{_ARTIFACT_ID}.json"
    before = canonical_file.read_bytes()

    export_library(tmp_path, tmp_path / "library.zip", environment=_ENVIRONMENT)

    assert canonical_file.read_bytes() == before
    assert not (tmp_path / "quarantine").exists()


def test_export_entry_carries_the_canonicals_last_modified(tmp_path: Path) -> None:
    # The entry carries last_modified so S23c's import last_modified_wins can compare.
    save_canonical(tmp_path, _agent(), clock=lambda: 1234.0)
    export_path = tmp_path / "library.zip"

    export_library(tmp_path, export_path, environment=_ENVIRONMENT)
    _manifest, entries = _read_export(export_path)

    assert entries[_ARTIFACT_ID]["metadata"]["last_modified"] == 1234.0
    assert entries[_ARTIFACT_ID]["artifact_id"] == _ARTIFACT_ID


def test_secrets_refused_skips_secret_bearing_canonicals(tmp_path: Path) -> None:
    save_canonical(tmp_path, _agent(_ARTIFACT_ID), clock=lambda: 1000.0)
    save_canonical(tmp_path, _secret_server(), clock=lambda: 2000.0)
    export_path = tmp_path / "library.zip"

    report = export_library(
        tmp_path, export_path, secret_policy=SECRET_POLICY_REFUSED, environment=_ENVIRONMENT
    )
    manifest, entries = _read_export(export_path)

    assert set(entries) == {_ARTIFACT_ID}  # the secret-bearing one is not shipped
    assert manifest["contains_secret_literals"] is False
    assert report.skipped_secret_artifacts == (_SECRET_ID,)


def test_secrets_accepted_ships_secret_material_and_flags_it(tmp_path: Path) -> None:
    save_canonical(tmp_path, _agent(_ARTIFACT_ID), clock=lambda: 1000.0)
    save_canonical(tmp_path, _secret_server(), clock=lambda: 2000.0)
    export_path = tmp_path / "library.zip"

    report = export_library(
        tmp_path, export_path, secret_policy=SECRET_POLICY_ACCEPTED, environment=_ENVIRONMENT
    )
    manifest, entries = _read_export(export_path)

    assert set(entries) == {_ARTIFACT_ID, _SECRET_ID}
    assert manifest["contains_secret_literals"] is True
    assert entries[_SECRET_ID]["env"]["API_KEY"] == "s3cr3t-literal"  # verbatim
    assert report.skipped_secret_artifacts == ()


def test_export_to_an_unwritable_path_aborts_without_partial(tmp_path: Path) -> None:
    save_canonical(tmp_path, _agent(), clock=lambda: 1000.0)
    export_path = tmp_path / "missing-parent" / "library.zip"

    with pytest.raises(PortableLibraryError):
        export_library(tmp_path, export_path, environment=_ENVIRONMENT)

    assert not export_path.exists()  # no partial export left behind (AC-4)


def test_an_empty_store_exports_a_zero_count_manifest(tmp_path: Path) -> None:
    export_path = tmp_path / "library.zip"

    export_library(tmp_path, export_path, environment=_ENVIRONMENT)
    manifest, entries = _read_export(export_path)

    assert entries == {}
    assert manifest["artifact_count"] == 0
    assert manifest["contains_secret_literals"] is False


def test_a_corrupt_canonical_is_skipped_without_quarantine(tmp_path: Path) -> None:
    # A store file that will not parse is skipped, and — because export is read-only
    # (AC-1) — it is left in place, never quarantined.
    save_canonical(tmp_path, _agent(_ARTIFACT_ID), clock=lambda: 1000.0)
    corrupt = tmp_path / "canonical" / f"{_OTHER_ID}.json"
    corrupt.write_text("{truncated")
    export_path = tmp_path / "library.zip"

    export_library(tmp_path, export_path, environment=_ENVIRONMENT)
    _manifest, entries = _read_export(export_path)

    assert set(entries) == {_ARTIFACT_ID}
    assert corrupt.read_text() == "{truncated"  # left in place, not quarantined
    assert not (tmp_path / "quarantine").exists()
