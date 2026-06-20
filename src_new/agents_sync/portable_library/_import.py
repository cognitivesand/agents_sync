"""Customization library import — restore an export into the canonical store (S23c).

``import_library`` reconciles each imported canonical against the local one by the
single ``last_modified_wins`` rule (FR-12): the newer content prevails, ties favour
the local artifact. The imported ``last_modified`` is preserved on write
(``save_imported_canonical``), so re-importing an unchanged library is a no-op
(FR-12 idempotency) and cross-host comparisons stay correct (amendment 008).

Three invariants govern it:

- **Validate before writing** (AC-9): the manifest and every entry are validated
  fully in memory; a malformed export raises ``PortableLibraryError`` naming the
  offender before any canonical is touched.
- **Canonical-only, atomic per artifact** (AC-5/AC-10, FR-13/FR-16): each accepted
  canonical is written atomically; ``state.json`` and tool roots are never touched,
  so the next poll adopts each new canonical. A failure leaves a strict prefix
  written, each entry whole.
- **Egress guarded** (AC-15/16): the receiver's ``secret_policy`` governs — a
  secret-bearing canonical is skipped under ``secrets_refused`` and imported verbatim
  under ``secrets_accepted``, each logged once (NFR-13). A displaced local canonical
  is archived first when its content changes (NFR-01/07).

Cross-identity (slug) merge and the preview/``--force`` gate land in S23d.
"""

from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

from agents_sync.artifact_archive import archive_copy
from agents_sync.canonical_store import (
    CanonicalMetadata,
    canonical_file_path,
    load_canonical_metadata,
    read_envelope_metadata,
    save_imported_canonical,
)
from agents_sync.domain_model.artifact_identity import InvalidArtifactId, validate_artifact_id
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.portable_library._shared import (
    CANONICAL_PREFIX,
    MANIFEST_NAME,
    PORTABLE_LIBRARY_SCHEMA_VERSION,
    PortableLibraryError,
    read_canonical_document,
)
from agents_sync.secret_policy import (
    ALLOWED_SECRET_POLICIES,
    SECRET_POLICY_REFUSED,
    find_secret_literals,
)

_LOGGER = logging.getLogger(__name__)
_CANONICAL_SIDE = "_canonical"


@dataclass(frozen=True)
class ImportReport:
    """What an import did: ids written, ids skipped by ``last_modified_wins``, and ids
    skipped by the receiver's secret policy."""

    accepted: tuple[str, ...]
    skipped: tuple[str, ...]
    skipped_secret: tuple[str, ...]


@dataclass(frozen=True)
class _ImportEntry:
    """One validated export entry: its document and the source metadata it carried."""

    document: CanonicalDocument
    metadata: CanonicalMetadata


@dataclass(frozen=True)
class _ImportDecision:
    """The fate of one imported artifact, resolved before any write."""

    artifact_id: str
    entry: _ImportEntry
    accepted: bool
    displaced: bool  # an accepted import overwriting an existing local canonical
    skipped_secret: bool


def import_library(
    state_dir: Path, import_path: Path, *, secret_policy: str = SECRET_POLICY_REFUSED
) -> ImportReport:
    """Restore the library export at ``import_path`` into ``state_dir``'s canonical store.

    Reconciles by ``last_modified_wins`` (FR-12) and applies the receiver's secret
    policy (AC-15/16). Decisions are made fully in memory; a malformed export (AC-9)
    raises ``PortableLibraryError`` before any write. Writes the canonical store only,
    so the next poll adopts each new canonical (FR-16)."""
    if secret_policy not in ALLOWED_SECRET_POLICIES:
        raise ValueError(
            f"unknown secret_policy: {secret_policy!r} (allowed: {sorted(ALLOWED_SECRET_POLICIES)})"
        )
    entries = _read_export(import_path)
    decisions = [
        _decide(state_dir, artifact_id, entry, secret_policy)
        for artifact_id, entry in sorted(entries.items())
    ]
    _apply(state_dir, decisions)
    return _report(decisions)


def _read_export(import_path: Path) -> dict[str, _ImportEntry]:
    """Validate and read the export's manifest and entries (AC-9) — no disk writes."""
    if not import_path.exists():
        raise PortableLibraryError(f"library export not found: {import_path}")
    try:
        archive = zipfile.ZipFile(import_path)
    except zipfile.BadZipFile as error:
        raise PortableLibraryError(f"library export is not a valid zip: {import_path}") from error
    with archive:
        names = set(archive.namelist())
        if MANIFEST_NAME not in names:
            raise PortableLibraryError(f"library export is missing {MANIFEST_NAME}: {import_path}")
        _validate_manifest(archive.read(MANIFEST_NAME))
        entries: dict[str, _ImportEntry] = {}
        for name in sorted(names):
            if name.startswith(CANONICAL_PREFIX) and name.endswith(".json"):
                artifact_id = name[len(CANONICAL_PREFIX) : -len(".json")]
                entries[artifact_id] = _read_entry(name, artifact_id, archive.read(name))
    return entries


def _validate_manifest(raw: bytes) -> None:
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PortableLibraryError(
            f"library export {MANIFEST_NAME} is unparseable: {error}"
        ) from error
    if not isinstance(manifest, dict):
        raise PortableLibraryError(f"library export {MANIFEST_NAME} is not a JSON object")
    schema_version = manifest.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise PortableLibraryError(
            f"library export {MANIFEST_NAME}.schema_version must be an integer, "
            f"got {schema_version!r}"
        )
    if schema_version > PORTABLE_LIBRARY_SCHEMA_VERSION:
        raise PortableLibraryError(
            f"library export schema_version={schema_version} exceeds the supported "
            f"{PORTABLE_LIBRARY_SCHEMA_VERSION}; upgrade agents_sync"
        )


def _read_entry(name: str, artifact_id: str, raw: bytes) -> _ImportEntry:
    try:
        validate_artifact_id(artifact_id)
    except InvalidArtifactId as error:
        raise PortableLibraryError(f"library export entry has an invalid id: {name}") from error
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PortableLibraryError(
            f"library export entry is unparseable: {name} ({error})"
        ) from error
    if not isinstance(data, dict):
        raise PortableLibraryError(f"library export entry is not a JSON object: {name}")
    try:
        document = CanonicalDocument.from_dict(data)
    except (TypeError, ValueError) as error:
        raise PortableLibraryError(
            f"library export entry is not a valid canonical: {name} ({error})"
        ) from error
    if document.artifact_id != artifact_id:
        raise PortableLibraryError(
            f"library export entry id mismatch: filename={artifact_id} "
            f"document={document.artifact_id}"
        )
    return _ImportEntry(document=document, metadata=read_envelope_metadata(data))


def _decide(
    state_dir: Path, artifact_id: str, entry: _ImportEntry, secret_policy: str
) -> _ImportDecision:
    """Resolve one entry's fate by ``last_modified_wins`` then the secret egress."""
    local = load_canonical_metadata(state_dir, artifact_id)
    wins = local is None or entry.metadata.last_modified > local.last_modified
    skipped_secret = wins and _refuses_secret(artifact_id, entry.document, secret_policy)
    accepted = wins and not skipped_secret
    return _ImportDecision(
        artifact_id=artifact_id,
        entry=entry,
        accepted=accepted,
        displaced=accepted and local is not None,
        skipped_secret=skipped_secret,
    )


def _refuses_secret(artifact_id: str, document: CanonicalDocument, secret_policy: str) -> bool:
    """Log a secret finding (NFR-13) and report whether the receiver refuses it."""
    findings = find_secret_literals(document)
    if not findings:
        return False
    field_paths = [finding.field_path for finding in findings]
    refused = secret_policy == SECRET_POLICY_REFUSED
    _LOGGER.warning(
        "library import %s secret-bearing canonical under secret_policy=%s: "
        "artifact_id=%s fields=%s",
        "skipping" if refused else "importing",
        secret_policy,
        artifact_id,
        field_paths,
    )
    return refused


def _apply(state_dir: Path, decisions: list[_ImportDecision]) -> None:
    """Write each accepted canonical atomically (FR-13), archiving a displaced local
    canonical first when its content changes (NFR-01/07)."""
    for decision in decisions:
        if not decision.accepted:
            continue
        if decision.displaced:
            _archive_if_content_differs(state_dir, decision.artifact_id, decision.entry.document)
        save_imported_canonical(state_dir, decision.entry.document, decision.entry.metadata)


def _archive_if_content_differs(
    state_dir: Path, artifact_id: str, imported: CanonicalDocument
) -> None:
    if _local_content_digest(state_dir, artifact_id) == imported.content_digest():
        return  # same content, newer last_modified — no content lost, no archive (NFR-07)
    archive_copy(
        state_dir, artifact_id, _CANONICAL_SIDE, canonical_file_path(state_dir, artifact_id)
    )


def _local_content_digest(state_dir: Path, artifact_id: str) -> str | None:
    path = canonical_file_path(state_dir, artifact_id)
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    document = read_canonical_document(raw)
    return None if document is None else document.content_digest()


def _report(decisions: list[_ImportDecision]) -> ImportReport:
    accepted: list[str] = []
    skipped: list[str] = []
    skipped_secret: list[str] = []
    for decision in decisions:
        if decision.accepted:
            accepted.append(decision.artifact_id)
            _LOGGER.info(
                "library import accepted (canonical-only): artifact_id=%s", decision.artifact_id
            )
        elif decision.skipped_secret:
            skipped_secret.append(decision.artifact_id)
        else:
            skipped.append(decision.artifact_id)
            _LOGGER.info(
                "library import skipped (last_modified_wins): artifact_id=%s", decision.artifact_id
            )
    return ImportReport(tuple(accepted), tuple(skipped), tuple(skipped_secret))
