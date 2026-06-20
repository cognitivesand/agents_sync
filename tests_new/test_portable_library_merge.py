"""Cross-identity merge and the preview/``--force`` gate (rebuild S23d) — US-12.

Two behaviours land here on top of the S23c import core:

- **Cross-identity slug merge (AC-7):** an imported canonical whose
  ``(customization_type, target_slug(name))`` matches a *different* local artifact
  reconciles onto the **local** id by ``last_modified_wins`` — the winning content is
  written under the local id (reused, not re-stamped) and the imported id is retired.
- **Preview honesty + the ``--force`` gate (AC-18):** ``preview_import`` enumerates,
  before any disk write, every imported id that merges-by-slug or overwrites a local,
  and ``import_library`` refuses to displace a local artifact unless ``force=True``.

Real filesystem via ``tmp_path``; exports are produced by ``export_library`` for
round-trip realism. ``_LOCAL_ID`` is seeded into the target; ``_IMPORT_ID`` is the
independently-minted id the export carries for the same logical artifact.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agents_sync.canonical_store import load_canonical, load_canonical_metadata, save_canonical
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.portable_library import (
    ExportEnvironment,
    PortableLibraryError,
    export_library,
    import_library,
    preview_import,
)
from agents_sync.secret_policy import SECRET_POLICY_ACCEPTED, SECRET_POLICY_REFUSED

_LOCAL_ID = "44444444-4444-4444-8444-444444444444"
_IMPORT_ID = "55555555-5555-4555-8555-555555555555"

_ENV = ExportEnvironment(
    now=datetime(2026, 6, 20, tzinfo=UTC),
    source_host="source-host",
    source_platform="TestOS",
    agents_sync_version="9.9.9",
)


def _agent(artifact_id: str, *, name: str = "reviewer", body: str = "body\n") -> CanonicalDocument:
    return CanonicalDocument(artifact_id=artifact_id, kind="agent", name=name, body=body)


def _server(artifact_id: str, *, env: dict[str, str]) -> CanonicalDocument:
    return CanonicalDocument(artifact_id=artifact_id, kind="mcp_server", name="db", env=env)


def _save_local(target: Path, document: CanonicalDocument, last_modified: float) -> None:
    save_canonical(target, document, clock=lambda: last_modified)


def _export(
    tmp_path: Path,
    document: CanonicalDocument,
    last_modified: float,
    *,
    secret_policy: str = SECRET_POLICY_REFUSED,
    name: str = "lib.zip",
) -> Path:
    source = tmp_path / f"source-{name}"
    save_canonical(source, document, clock=lambda: last_modified)
    export_path = tmp_path / name
    export_library(source, export_path, secret_policy=secret_policy, environment=_ENV)
    return export_path


def test_cross_identity_import_wins_writes_under_the_local_id(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _save_local(target, _agent(_LOCAL_ID, body="local\n"), 1000.0)
    export_path = _export(tmp_path, _agent(_IMPORT_ID, body="imported\n"), 2000.0)

    report = import_library(target, export_path, force=True)

    survivor = load_canonical(target, _LOCAL_ID)
    assert isinstance(survivor, CanonicalDocument)
    assert survivor.body == "imported\n"  # the winner's content (AC-7)
    assert load_canonical(target, _IMPORT_ID) is None  # imported id retired (AC-7)
    assert load_canonical_metadata(target, _LOCAL_ID).last_modified == 2000.0  # import lm preserved
    assert report.accepted == (_LOCAL_ID,)  # written under the reused local id
    archived = list((target / "archive" / _LOCAL_ID / "_canonical").iterdir())
    assert len(archived) == 1  # the displaced local canonical's bytes preserved (NFR-01)
    assert "local" in archived[0].read_text()


def test_cross_identity_local_wins_keeps_the_local_and_retires_the_import(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _save_local(target, _agent(_LOCAL_ID, body="local\n"), 2000.0)
    export_path = _export(tmp_path, _agent(_IMPORT_ID, body="imported\n"), 1000.0)

    report = import_library(target, export_path)  # local wins → no displacement → no --force

    assert load_canonical(target, _LOCAL_ID).body == "local\n"  # local content unchanged
    assert load_canonical(target, _IMPORT_ID) is None  # imported id retired
    assert report.skipped == (_IMPORT_ID,)


def test_same_content_cross_identity_merges_without_force_or_archive(tmp_path: Path) -> None:
    # Re-key-before-compare: same body under two ids must read as same content, so the merge
    # neither requires --force nor archives (NFR-07) — only last_modified advances.
    target = tmp_path / "target"
    _save_local(target, _agent(_LOCAL_ID, body="same\n"), 1000.0)
    export_path = _export(tmp_path, _agent(_IMPORT_ID, body="same\n"), 2000.0)

    preview = preview_import(target, export_path)
    assert preview.merges == ((_IMPORT_ID, _LOCAL_ID),)
    assert preview.requires_force is False  # same content → nothing displaced

    report = import_library(target, export_path)  # no --force needed
    assert load_canonical(target, _IMPORT_ID) is None  # imported id retired
    assert load_canonical_metadata(target, _LOCAL_ID).last_modified == 2000.0  # lm advanced
    assert not (target / "archive").exists()  # no content lost → no archive (NFR-07)
    assert report.accepted == (_LOCAL_ID,)


def test_preview_reports_a_cross_identity_merge_that_displaces(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _save_local(target, _agent(_LOCAL_ID, body="local\n"), 1000.0)
    export_path = _export(tmp_path, _agent(_IMPORT_ID, body="imported\n"), 2000.0)

    preview = preview_import(target, export_path)

    assert preview.merges == ((_IMPORT_ID, _LOCAL_ID),)
    assert preview.displaced_local_ids == (_LOCAL_ID,)
    assert preview.requires_force is True
    assert load_canonical(target, _LOCAL_ID).body == "local\n"  # read-only: local untouched
    assert load_canonical(target, _IMPORT_ID) is None


def test_preview_reports_a_merge_even_when_the_local_wins(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _save_local(target, _agent(_LOCAL_ID, body="local\n"), 2000.0)
    export_path = _export(tmp_path, _agent(_IMPORT_ID, body="imported\n"), 1000.0)

    preview = preview_import(target, export_path)

    assert preview.merges == ((_IMPORT_ID, _LOCAL_ID),)  # the slug reconciliation is reported
    assert preview.displaced_local_ids == ()  # but no local content is displaced
    assert preview.requires_force is False


def test_preview_reports_a_same_id_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _save_local(target, _agent(_LOCAL_ID, body="local\n"), 1000.0)
    export_path = _export(tmp_path, _agent(_LOCAL_ID, body="imported\n"), 2000.0)

    preview = preview_import(target, export_path)

    assert preview.merges == ()  # same id → an overwrite, not a slug merge
    assert preview.displaced_local_ids == (_LOCAL_ID,)
    assert preview.requires_force is True


def test_preview_is_clean_for_a_fresh_import(tmp_path: Path) -> None:
    target = tmp_path / "target"
    export_path = _export(tmp_path, _agent(_IMPORT_ID), 1000.0)

    preview = preview_import(target, export_path)

    assert preview.merges == ()
    assert preview.displaced_local_ids == ()
    assert preview.requires_force is False


def test_import_without_force_refuses_to_displace_a_local(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _save_local(target, _agent(_LOCAL_ID, body="local\n"), 1000.0)
    export_path = _export(tmp_path, _agent(_IMPORT_ID, body="imported\n"), 2000.0)

    with pytest.raises(PortableLibraryError):
        import_library(target, export_path)  # would displace _LOCAL_ID without --force (AC-18)

    assert load_canonical(target, _LOCAL_ID).body == "local\n"  # nothing written
    assert load_canonical(target, _IMPORT_ID) is None
    assert not (target / "archive").exists()  # nothing archived


def test_a_secret_refused_overwrite_does_not_require_force(tmp_path: Path) -> None:
    # A would-be overwrite that the receiver's secret policy skips never displaces, so it must
    # not trip the --force gate (the gate keys on accepted displacement, not on "import wins").
    target = tmp_path / "target"
    _save_local(target, _server(_LOCAL_ID, env={}), 1000.0)
    export_path = _export(
        tmp_path, _server(_LOCAL_ID, env={"API_KEY": "s3cr3t-literal"}), 2000.0,
        secret_policy=SECRET_POLICY_ACCEPTED,
    )

    report = import_library(target, export_path, secret_policy=SECRET_POLICY_REFUSED)  # no force

    assert report.skipped_secret == (_LOCAL_ID,)
    assert load_canonical(target, _LOCAL_ID).env == {}  # local unchanged (no displacement)
