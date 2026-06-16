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

The store envelope also carries a nested ``metadata`` block (``last_modified``,
``generation``) the runtime model keeps out of the document (glossary, amendment
008): ``save_canonical`` stamps a fresh ``last_modified`` and the next
``generation`` iff the content digest changes — unchanged content preserves them,
so a heal/reproject never moves ``last_modified`` — and the block is excluded from
the content digest, so change detection stays content-only (FR-14).
``load_canonical_metadata`` reads it back for the library export/import compare (S23).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents_sync.atomic_file_writer import write_text_atomic
from agents_sync.domain_model.artifact_identity import InvalidArtifactId, validate_artifact_id
from agents_sync.domain_model.canonical_document import CanonicalDocument, CorruptCanonical
from agents_sync.store_quarantine import quarantine_corrupt_file

CANONICAL_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CanonicalMetadata:
    """A canonical's runtime metadata: when its content last changed and how often.

    ``last_modified`` is a wall-clock POSIX timestamp of the last content change
    (not the file write time); ``generation`` is a per-artifact monotonic counter
    incremented on each content change. Both live in the store envelope, never in
    the content-only ``CanonicalDocument``.
    """

    last_modified: float
    generation: int


def save_canonical(
    store_dir: Path, document: CanonicalDocument, *, clock: Callable[[], float] = time.time
) -> None:
    """Persist ``document`` normalised, atomically, with the schema version and the
    runtime ``metadata`` block stamped.

    ``last_modified``/``generation`` advance iff the content digest changes; a
    re-save of unchanged content preserves them (a heal/reproject must not move
    ``last_modified`` — amendment 008). The block is excluded from the content
    digest, so FR-14 change detection stays content-only. The clock is injected."""
    path = canonical_file_path(store_dir, document.artifact_id)
    metadata = _next_metadata(path, document, clock)
    payload: dict[str, Any] = {
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "metadata": {
            "last_modified": metadata.last_modified,
            "generation": metadata.generation,
        },
    }
    payload.update(document.normalised().to_dict())
    write_text_atomic(
        path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def load_canonical_metadata(store_dir: Path, artifact_id: str) -> CanonicalMetadata | None:
    """Return the canonical's runtime metadata, or ``None`` when the file is absent.

    The library export and import-collision compare read this (S23). It never
    quarantines — corruption handling is the content load path's job."""
    data = _read_store_file(canonical_file_path(store_dir, artifact_id))
    return None if data is None else _metadata_from_dict(data)


def load_canonical(
    store_dir: Path, artifact_id: str
) -> CanonicalDocument | CorruptCanonical | None:
    """Return the stored canonical, ``None`` if absent, or quarantine-and-report corrupt."""
    path = canonical_file_path(store_dir, artifact_id)
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


def canonical_file_path(store_dir: Path, artifact_id: str) -> Path:
    """Where this artifact's canonical lives — public so the executor can archive it."""
    return store_dir / "canonical" / f"{validate_artifact_id(artifact_id)}.json"


def _quarantine(store_dir: Path, source: Path, reason: str) -> CorruptCanonical:
    """Quarantine ``source`` (raises ``QuarantineError`` on failure) and report why."""
    quarantine_corrupt_file(store_dir, source, reason)
    return CorruptCanonical(reason=reason)


def _next_metadata(
    path: Path, document: CanonicalDocument, clock: Callable[[], float]
) -> CanonicalMetadata:
    """Preserve the prior block when the content is unchanged, else stamp a fresh
    ``last_modified`` and the next ``generation``."""
    prior = _read_prior(path)
    if prior is not None:
        prior_digest, prior_metadata = prior
        if prior_digest == document.content_digest() and prior_metadata.generation >= 1:
            return prior_metadata
        previous_generation = prior_metadata.generation
    else:
        previous_generation = 0
    return CanonicalMetadata(last_modified=clock(), generation=previous_generation + 1)


def _read_prior(path: Path) -> tuple[str, CanonicalMetadata] | None:
    """Best-effort ``(content_digest, metadata)`` of the canonical already at ``path``.

    ``None`` when absent or unreadable — a corrupt prior is not this writer's to
    quarantine (the load path owns that); it just yields a fresh metadata stamp."""
    data = _read_store_file(path)
    if data is None:
        return None
    try:
        document = CanonicalDocument.from_dict(data)
    except (TypeError, ValueError):
        return None
    return document.content_digest(), _metadata_from_dict(data)


def _read_store_file(path: Path) -> dict[str, Any] | None:
    """The stored envelope as a dict, or ``None`` if absent/unreadable/non-object."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _metadata_from_dict(data: dict[str, Any]) -> CanonicalMetadata:
    """Read the stored ``metadata`` block; an absent block reads as generation 0."""
    block = data.get("metadata")
    if not isinstance(block, dict):
        return CanonicalMetadata(last_modified=0.0, generation=0)
    return CanonicalMetadata(
        last_modified=float(block.get("last_modified", 0.0)),
        generation=int(block.get("generation", 0)),
    )
