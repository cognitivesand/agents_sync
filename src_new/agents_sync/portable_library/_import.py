"""Customization library import — restore an export into the canonical store (S23c/S23d).

``import_library`` reconciles each imported canonical against the local store by the
single ``last_modified_wins`` rule (FR-12; ties favour the local artifact), two ways:
a same-id overwrite (AC-6), and a cross-identity slug merge where an imported artifact
whose ``(customization_type, slug)`` matches a *different* local id reconciles onto the
**local** id — the winner's content written under that reused id (files not re-stamped),
the imported id retired (AC-7). The imported ``last_modified`` is preserved on write, so
re-importing an unchanged library is a no-op (FR-12) and cross-host compares hold.

The reconciliation is decided fully in memory (``read_export`` validates the manifest and
every entry first, AC-9), so a malformed export, or an unforced displacement, aborts
before any write. ``import_library`` refuses to replace a local artifact's content unless
``force`` is set, and ``preview_import`` reports read-only what would merge or be displaced
(AC-18). Writes are canonical-only and atomic per artifact (AC-5/AC-10, FR-13/FR-16) —
a displaced local is archived first when its content changes (NFR-01/07) — and the
receiver's ``secret_policy`` governs egress, logged once per artifact (AC-15/16, NFR-13).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path

from agents_sync.artifact_archive import archive_copy
from agents_sync.canonical_store import (
    CanonicalMetadata,
    canonical_file_path,
    list_canonical_ids,
    load_canonical_metadata,
    save_imported_canonical,
)
from agents_sync.domain_model.artifact_naming import ReconciliationKey, candidate_key
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.portable_library._import_read import ImportEntry, read_export
from agents_sync.portable_library._shared import PortableLibraryError, read_canonical_document
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
class ImportPreview:
    """What an import would do, computed read-only before any write (AC-18).

    ``merges`` pairs each imported id with the *different* local id it reconciles onto
    by slug (cross-identity, AC-7), reported whichever side wins. ``displaced_local_ids``
    lists the local artifacts whose on-disk content the import would replace (a same-id
    overwrite or a cross-identity merge the import wins) — the set the ``--force`` gate
    protects."""

    merges: tuple[tuple[str, str], ...]
    displaced_local_ids: tuple[str, ...]

    @property
    def requires_force(self) -> bool:
        return bool(self.displaced_local_ids)


@dataclass(frozen=True)
class _ImportDecision:
    """The fate of one imported artifact, resolved before any write."""

    artifact_id: str  # the imported entry's id (retired when it merges onto a local id)
    surviving_id: str  # the id the content is written under (a reused local id on merge)
    document: CanonicalDocument  # re-keyed to surviving_id, ready to persist
    metadata: CanonicalMetadata
    accepted: bool  # wins last_modified_wins AND not secret-refused
    displaced: bool  # accepted, and replaces a different-content local (archive + --force)
    merged: bool  # surviving_id != artifact_id (cross-identity reconciliation onto a local id)
    skipped_secret: bool
    secret_field_paths: tuple[str, ...]  # for the one NFR-13 egress WARNING (empty if clean)


def import_library(
    state_dir: Path,
    import_path: Path,
    *,
    secret_policy: str = SECRET_POLICY_REFUSED,
    force: bool = False,
) -> ImportReport:
    """Restore the library export at ``import_path`` into ``state_dir``'s canonical store.

    Reconciles by ``last_modified_wins`` (FR-12), merging an imported artifact whose slug
    matches a different local one onto the local id (AC-7), and applies the receiver's
    secret policy (AC-15/16). Refuses to displace any local artifact unless ``force`` is
    set (AC-18). A malformed export (AC-9) or an unforced displacement raises
    ``PortableLibraryError`` before any write. Writes the canonical store only, so the
    next poll adopts each new canonical (FR-16)."""
    _require_known_policy(secret_policy)
    decisions = _plan(state_dir, import_path, secret_policy)
    _guard_displacement(decisions, force)
    _log_secret_egress(decisions, secret_policy)
    _apply(state_dir, decisions)
    return _report(decisions)


def preview_import(
    state_dir: Path, import_path: Path, *, secret_policy: str = SECRET_POLICY_REFUSED
) -> ImportPreview:
    """Report what importing ``import_path`` into ``state_dir`` would do — no disk writes.

    Enumerates the cross-identity slug merges and the local artifacts the import would
    displace under ``secret_policy``, so a caller can gate on ``--force`` (AC-18)."""
    _require_known_policy(secret_policy)
    return _preview(_plan(state_dir, import_path, secret_policy))


def _require_known_policy(secret_policy: str) -> None:
    if secret_policy not in ALLOWED_SECRET_POLICIES:
        raise ValueError(
            f"unknown secret_policy: {secret_policy!r} (allowed: {sorted(ALLOWED_SECRET_POLICIES)})"
        )


def _plan(state_dir: Path, import_path: Path, secret_policy: str) -> list[_ImportDecision]:
    """Resolve every export entry's fate in memory (AC-9 read; no writes)."""
    entries = read_export(import_path)
    slug_index = _build_slug_index(state_dir)
    return [
        _decide(state_dir, slug_index, artifact_id, entry, secret_policy)
        for artifact_id, entry in sorted(entries.items())
    ]


def _build_slug_index(state_dir: Path) -> dict[ReconciliationKey, str]:
    """Map each local canonical's ``(customization_type, slug)`` to its id (AC-7).

    Keyed on the canonical store (the source of truth, FR-16) and read non-mutatingly —
    a corrupt local is skipped, never quarantined, so preview stays read-only."""
    slug_index: dict[ReconciliationKey, str] = {}
    for local_id in list_canonical_ids(state_dir):
        document = _read_local_document(state_dir, local_id)
        if document is not None:
            slug_index[candidate_key(document.kind, document.name)] = local_id
    return slug_index


def _decide(
    state_dir: Path,
    slug_index: dict[ReconciliationKey, str],
    artifact_id: str,
    entry: ImportEntry,
    secret_policy: str,
) -> _ImportDecision:
    """Resolve one entry by ``last_modified_wins`` (AC-6/AC-7) then the secret egress."""
    local_id = _resolve_local_id(state_dir, slug_index, artifact_id, entry.document)
    surviving_id = artifact_id if local_id is None else local_id
    document = (
        entry.document
        if surviving_id == artifact_id
        else replace(entry.document, artifact_id=surviving_id)
    )
    local_metadata = None if local_id is None else load_canonical_metadata(state_dir, local_id)
    wins = local_metadata is None or entry.metadata.last_modified > local_metadata.last_modified
    findings = find_secret_literals(entry.document)
    skipped_secret = wins and bool(findings) and secret_policy == SECRET_POLICY_REFUSED
    accepted = wins and not skipped_secret
    displaced = (
        accepted and local_id is not None and _content_differs(state_dir, surviving_id, document)
    )
    return _ImportDecision(
        artifact_id=artifact_id,
        surviving_id=surviving_id,
        document=document,
        metadata=entry.metadata,
        accepted=accepted,
        displaced=displaced,
        merged=surviving_id != artifact_id,
        skipped_secret=skipped_secret,
        secret_field_paths=tuple(finding.field_path for finding in findings),
    )


def _resolve_local_id(
    state_dir: Path,
    slug_index: dict[ReconciliationKey, str],
    artifact_id: str,
    document: CanonicalDocument,
) -> str | None:
    """The local id this import reconciles onto: the same id when one exists (AC-6), else
    a different local id sharing its ``(customization_type, slug)`` (AC-7), else ``None``
    for a fresh import. Same-id takes precedence over a slug match."""
    if load_canonical_metadata(state_dir, artifact_id) is not None:
        return artifact_id
    return slug_index.get(candidate_key(document.kind, document.name))


def _read_local_document(state_dir: Path, artifact_id: str) -> CanonicalDocument | None:
    """The local canonical's document, or ``None`` if absent/unreadable. Non-mutating: a
    corrupt local is never quarantined here (the content load path owns that)."""
    try:
        raw = canonical_file_path(state_dir, artifact_id).read_bytes()
    except OSError:
        return None
    return read_canonical_document(raw)


def _content_differs(state_dir: Path, artifact_id: str, document: CanonicalDocument) -> bool:
    """Whether the local canonical at ``artifact_id`` differs in content from ``document``.

    The caller keys both to the same id before this compare, so the content digest (which
    includes the id) reflects only a real content change; an unreadable local counts as
    differing (default to preserving it via archive)."""
    local = _read_local_document(state_dir, artifact_id)
    return local is None or local.content_digest() != document.content_digest()


def _guard_displacement(decisions: list[_ImportDecision], force: bool) -> None:
    """Refuse to displace any local artifact's content without ``force`` (AC-18) — raised
    before any write, so a refused import leaves the store untouched."""
    if force:
        return
    displaced = sorted(decision.surviving_id for decision in decisions if decision.displaced)
    if displaced:
        raise PortableLibraryError(
            f"import would displace {len(displaced)} local artifact(s) without --force: "
            f"{displaced}"
        )


def _log_secret_egress(decisions: list[_ImportDecision], secret_policy: str) -> None:
    """Emit one structured WARNING per secret-bearing artifact that reached egress (won
    its compare), whether skipped (refused) or imported (accepted) — NFR-13."""
    for decision in decisions:
        if not decision.secret_field_paths or not (decision.accepted or decision.skipped_secret):
            continue
        _LOGGER.warning(
            "library import %s secret-bearing canonical under secret_policy=%s: "
            "artifact_id=%s fields=%s",
            "skipping" if decision.skipped_secret else "importing",
            secret_policy,
            decision.artifact_id,
            list(decision.secret_field_paths),
        )


def _apply(state_dir: Path, decisions: list[_ImportDecision]) -> None:
    """Write each accepted canonical atomically under its surviving id (FR-13), archiving
    a displaced local canonical first to preserve its bytes (NFR-01/07)."""
    for decision in decisions:
        if not decision.accepted:
            continue
        if decision.displaced:
            archive_copy(
                state_dir,
                decision.surviving_id,
                _CANONICAL_SIDE,
                canonical_file_path(state_dir, decision.surviving_id),
            )
        save_imported_canonical(state_dir, decision.document, decision.metadata)


def _report(decisions: list[_ImportDecision]) -> ImportReport:
    accepted: list[str] = []
    skipped: list[str] = []
    skipped_secret: list[str] = []
    for decision in decisions:
        if decision.accepted:
            accepted.append(decision.surviving_id)
            _LOGGER.info(
                "library import accepted (canonical-only): artifact_id=%s", decision.surviving_id
            )
        elif decision.skipped_secret:
            skipped_secret.append(decision.artifact_id)
        else:
            skipped.append(decision.artifact_id)
            _LOGGER.info(
                "library import skipped (last_modified_wins): artifact_id=%s", decision.artifact_id
            )
    return ImportReport(tuple(accepted), tuple(skipped), tuple(skipped_secret))


def _preview(decisions: list[_ImportDecision]) -> ImportPreview:
    merges = tuple(
        (decision.artifact_id, decision.surviving_id) for decision in decisions if decision.merged
    )
    displaced = tuple(decision.surviving_id for decision in decisions if decision.displaced)
    return ImportPreview(merges=merges, displaced_local_ids=displaced)
