"""Canonical store — persistence gateway for canonical documents (US-09 AC-4, FR-14).

One JSON file per artifact under ``store_dir/canonical/<artifact_id>.json``, written
atomically and normalised (byte-stable: equivalent documents produce identical bytes,
so digests never churn). ``load_canonical`` returns exactly the planner's
stored-canonical input type: a ``CanonicalDocument``, a ``CorruptCanonical`` (the
unreadable file was MOVED to ``store_dir/quarantine/`` first, bytes preserved for
recovery), or ``None`` (absent). If the quarantine move itself fails, the load fails
closed with ``store_quarantine.QuarantineError`` — rebuilding would overwrite the
corrupt bytes. The structured-error logging for quarantine events lands with the
daemon (S22); until then ``CorruptCanonical.reason`` carries the cause.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents_sync.atomic_file_writer import write_text_atomic
from agents_sync.domain_model.artifact_identity import InvalidArtifactId, validate_artifact_id
from agents_sync.domain_model.canonical_document import CanonicalDocument, CorruptCanonical
from agents_sync.store_quarantine import quarantine_corrupt_file

CANONICAL_SCHEMA_VERSION = 1


def save_canonical(store_dir: Path, document: CanonicalDocument) -> None:
    """Persist ``document`` normalised, atomically, with the schema version stamped."""
    payload: dict[str, Any] = {"schema_version": CANONICAL_SCHEMA_VERSION}
    payload.update(document.normalised().to_dict())
    write_text_atomic(
        _canonical_file_path(store_dir, document.artifact_id),
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )


def load_canonical(
    store_dir: Path, artifact_id: str
) -> CanonicalDocument | CorruptCanonical | None:
    """Return the stored canonical, ``None`` if absent, or quarantine-and-report corrupt."""
    path = _canonical_file_path(store_dir, artifact_id)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _quarantine(store_dir, path, "unreadable bytes")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _quarantine(store_dir, path, "JSON parse error")
    if not isinstance(data, dict):
        return _quarantine(store_dir, path, "root is not a JSON object")
    if data.get("schema_version") != CANONICAL_SCHEMA_VERSION:
        return _quarantine(
            store_dir, path, f"unsupported schema_version: {data.get('schema_version')!r}"
        )
    try:
        return CanonicalDocument.from_dict(data)
    except (TypeError, ValueError) as error:
        # TypeError covers type-corrupt fields (e.g. tools: 5 -> tuple(5)); leaving
        # it uncaught would re-crash every poll on the same file, never healing.
        return _quarantine(store_dir, path, str(error))


def list_canonical_ids(store_dir: Path) -> list[str]:
    """The sorted artifact ids present in the store (invalid filename stems skipped)."""
    canonical_dir = store_dir / "canonical"
    if not canonical_dir.is_dir():
        return []
    artifact_ids: list[str] = []
    for path in sorted(canonical_dir.glob("*.json")):
        try:
            artifact_ids.append(validate_artifact_id(path.stem))
        except InvalidArtifactId:
            continue
    return artifact_ids


def _canonical_file_path(store_dir: Path, artifact_id: str) -> Path:
    return store_dir / "canonical" / f"{validate_artifact_id(artifact_id)}.json"


def _quarantine(store_dir: Path, source: Path, reason: str) -> CorruptCanonical:
    """Quarantine ``source`` (raises ``QuarantineError`` on failure) and report why."""
    quarantine_corrupt_file(store_dir, source, reason)
    return CorruptCanonical(reason=reason)
