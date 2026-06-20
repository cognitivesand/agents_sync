"""Library export reading and validation (S23c, split out in S23d) — US-12 AC-9.

``read_export`` opens the export zip and validates its manifest and every entry
**fully in memory**, returning one ``ImportEntry`` per artifact id. A malformed
export — a missing/unsupported manifest, an unparseable entry, an invalid id, or an
id/filename mismatch — raises ``PortableLibraryError`` naming the offender (AC-9)
before the import touches any canonical. The reconciliation and write live in
``_import``; this module never writes.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from agents_sync.canonical_store import CanonicalMetadata, read_envelope_metadata
from agents_sync.domain_model.artifact_identity import InvalidArtifactId, validate_artifact_id
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.portable_library._shared import (
    CANONICAL_PREFIX,
    MANIFEST_NAME,
    PORTABLE_LIBRARY_SCHEMA_VERSION,
    PortableLibraryError,
)


@dataclass(frozen=True)
class ImportEntry:
    """One validated export entry: its document and the source metadata it carried."""

    document: CanonicalDocument
    metadata: CanonicalMetadata


def read_export(import_path: Path) -> dict[str, ImportEntry]:
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
        entries: dict[str, ImportEntry] = {}
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


def _read_entry(name: str, artifact_id: str, raw: bytes) -> ImportEntry:
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
    return ImportEntry(document=document, metadata=read_envelope_metadata(data))
