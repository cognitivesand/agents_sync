"""Customization library export and import for US-12.

A customization library export is a single zip file capturing every
managed customization_artifact's canonical document plus a small
manifest. It is portable across hosts: `state.json` and the on-disk
`archive/` directory are deliberately excluded because they hold
host-specific bytes.

Two operations:

  - `export_to_zip`: writes the export. Read-only against the source
    state directory; the zip is materialised atomically (write to a
    sibling temp file, then `os.replace`).
  - `import_from_zip`: reads an export and synchronously projects every
    accepted customization_artifact onto every locally enabled,
    supporting, and `available` agentic_tool. Reuses `render_to_agentic_tool`
    and `update_state_n_way` from `rendering` — no new sync-engine
    code. Collision strategy is one of `skip`, `mtime_wins` (the
    default, mirroring US-06), or `overwrite`. Decisions are made fully
    in memory before any disk write, so a mid-import failure cannot
    leave `state.json` half-updated (AC-10).

`last_modified` is a wall-clock POSIX timestamp persisted in state by
Phase 0 (US-12). It is the source of truth for the `mtime_wins`
comparison. Wall-clock is not monotonic across hosts; clock skew is
tie-broken in favour of the local artifact (AC-6 tie rule).
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import platform
import shutil
import socket
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from agents_sync.agentic_tool_spec import AgenticToolSpec
from agents_sync.archive import archive_canonical
from agents_sync.canonical import (
    canonical_last_modified,
    canonical_metadata,
    canonical_path,
    list_canonical_ids,
    load_canonical,
    set_canonical_metadata,
)
from agents_sync.identity import InvalidPairId, validate_pair_id
from agents_sync.mcp_secret_policy import (
    find_mcp_secret_literals,
    normalize_secret_policy,
)
from agents_sync.state import (
    CustomizationArtifactState,
    load_state,
    target_slug,
)
from agents_sync.tool_status import ToolStatusTracker

PORTABLE_ARCHIVE_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
CANONICAL_PREFIX = "canonical/"

CollisionStrategy = Literal["skip", "mtime_wins", "overwrite"]
ALLOWED_STRATEGIES: frozenset[CollisionStrategy] = frozenset({"skip", "mtime_wins", "overwrite"})


class PortableArchiveError(ValueError):
    """Raised when a portable archive is malformed or refuses to import."""


@dataclass
class ExportReport:
    archive_path: Path
    artifact_count: int
    contains_secret_literals: bool = False
    skipped_secret_artifacts: list[str] = field(default_factory=list)


@dataclass
class ImportReport:
    accepted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    archived_local: list[tuple[str, str]] = field(default_factory=list)
    skipped_secret_artifacts: list[str] = field(default_factory=list)


# ---------------- export ----------------


def _agents_sync_version() -> str:
    from agents_sync import __version__

    return __version__


def _build_manifest(
    artifact_count: int,
    *,
    contains_secret_literals: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": PORTABLE_ARCHIVE_SCHEMA_VERSION,
        "exported_at": _dt.datetime.now(tz=_dt.UTC).isoformat(),
        "source_host": socket.gethostname(),
        "source_platform": platform.system(),
        "agents_sync_version": _agents_sync_version(),
        "artifact_count": artifact_count,
        "contains_secret_literals": contains_secret_literals,
    }


def export_to_zip(
    state_dir: Path,
    zip_path: Path,
    *,
    secret_policy: str = "secrets_refused",
) -> ExportReport:
    """Write a customization library export to ``zip_path`` (atomic replace).

    Applies the configured secret policy per-artifact (US-12 AC-12 / AC-13 /
    AC-14). Under ``secrets_refused``, canonicals carrying literal secret
    material are skipped with one structured WARNING each; the clean
    canonicals still ship. Under ``secrets_accepted``, every canonical is
    included verbatim and one summary WARNING lists the affected
    ``customization_artifact_id``s. The manifest carries a
    ``contains_secret_literals`` boolean reflecting what actually shipped
    (always ``False`` under ``secrets_refused`` since the filter removed
    anything that would have flipped it).
    """
    normalized_policy = normalize_secret_policy(
        secret_policy,
        source="export_to_zip",
        warn_deprecated=False,
    )
    state = load_state(state_dir)
    canonicals: dict[str, dict[str, Any]] = {}
    skipped_secret_artifacts: list[str] = []
    secret_bearing_artifacts: list[str] = []
    for pair_id in state:
        canonical = load_canonical(state_dir, pair_id)
        if canonical is None:
            logging.warning(
                "Skipping pair with missing canonical during export: pair_id=%s",
                pair_id,
            )
            continue
        findings = find_mcp_secret_literals(canonical)
        if findings:
            field_paths = [f.field_path for f in findings]
            if normalized_policy == "secrets_refused":
                logging.warning(
                    "Skipping export of artifact with literal secret material "
                    "under secret_policy=secrets_refused: "
                    "pair_id=%s fields=%s",
                    pair_id,
                    field_paths,
                )
                skipped_secret_artifacts.append(pair_id)
                continue
            # secrets_accepted — include verbatim, summary warning emitted below
            secret_bearing_artifacts.append(pair_id)
        canonicals[pair_id] = dict(canonical)

    if secret_bearing_artifacts:
        logging.warning(
            "Customization library export under secret_policy=secrets_accepted: "
            "%d artifact(s) carry literal secret material: %s",
            len(secret_bearing_artifacts),
            secret_bearing_artifacts,
        )

    contains_secret_literals = bool(secret_bearing_artifacts)
    manifest = _build_manifest(
        len(canonicals),
        contains_secret_literals=contains_secret_literals,
    )
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{zip_path.name}.", suffix=".tmp", dir=str(zip_path.parent)
    )
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            for pair_id, entry in sorted(canonicals.items()):
                zf.writestr(
                    f"{CANONICAL_PREFIX}{pair_id}.json",
                    json.dumps(entry, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                )
        os.replace(tmp_path, zip_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return ExportReport(
        archive_path=zip_path,
        artifact_count=len(canonicals),
        contains_secret_literals=contains_secret_literals,
        skipped_secret_artifacts=skipped_secret_artifacts,
    )


# ---------------- import ----------------


def _read_zip_entries(
    zip_path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Return (manifest, {pair_id: canonical_with_last_modified}).

    Validates structure but not semantics — semantic checks (pair_id
    canonicality, schema version range) happen in the caller so error
    messages stay precise.
    """
    if not zip_path.exists():
        raise PortableArchiveError(f"Archive not found: {zip_path}")
    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile as exc:
        raise PortableArchiveError(f"Not a valid zip file: {zip_path}") from exc
    with zf:
        names = set(zf.namelist())
        if MANIFEST_NAME not in names:
            raise PortableArchiveError(f"Archive is missing {MANIFEST_NAME}: {zip_path}")
        try:
            manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PortableArchiveError(f"Archive {MANIFEST_NAME} is unparseable: {exc}") from exc
        if not isinstance(manifest, dict):
            raise PortableArchiveError("Archive manifest is not a JSON object")
        canonicals: dict[str, dict[str, Any]] = {}
        for name in sorted(names):
            if not name.startswith(CANONICAL_PREFIX) or not name.endswith(".json"):
                continue
            pair_id = name[len(CANONICAL_PREFIX) : -len(".json")]
            try:
                validate_pair_id(pair_id)
            except InvalidPairId as exc:
                raise PortableArchiveError(f"Archive entry has invalid pair_id: {name}") from exc
            try:
                doc = json.loads(zf.read(name).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise PortableArchiveError(f"Archive entry is unparseable: {name}: {exc}") from exc
            if not isinstance(doc, dict):
                raise PortableArchiveError(f"Archive entry is not a JSON object: {name}")
            if doc.get("pair_id") != pair_id:
                raise PortableArchiveError(
                    f"Archive entry pair_id mismatch: filename={pair_id} "
                    f"document={doc.get('pair_id')!r}"
                )
            if "kind" not in doc or "name" not in doc:
                raise PortableArchiveError(f"Archive entry missing kind/name: {name}")
            canonicals[pair_id] = doc
    return manifest, canonicals


def _validate_manifest_version(manifest: dict[str, Any]) -> None:
    version = manifest.get("schema_version")
    if not isinstance(version, int):
        raise PortableArchiveError(
            f"Archive manifest.schema_version must be an integer, got {version!r}"
        )
    if version > PORTABLE_ARCHIVE_SCHEMA_VERSION:
        raise PortableArchiveError(
            f"Archive schema_version={version} is newer than this tool supports "
            f"(max={PORTABLE_ARCHIVE_SCHEMA_VERSION}). Upgrade agents-sync."
        )


def _local_last_modified(
    state: dict[str, CustomizationArtifactState], state_dir: Path, pair_id: str
) -> float:
    """The local last_modified for a pair, read from canonical metadata."""
    canonical = load_canonical(state_dir, pair_id)
    if canonical is not None:
        return canonical_last_modified(canonical) or 0.0
    return 0.0


@dataclass
class _ImportDecision:
    """One per accepted-or-skipped artifact, fully resolved before disk writes."""

    pair_id: str  # the imported candidate's id (the loser id when merged away)
    canonical: dict[str, Any]
    last_modified: float
    generation: int
    accepted: bool
    displaces_local_pair_id: str | None  # local pair whose bytes the next poll archives
    surviving_pair_id: str  # id the winning content is written under (local-id reuse)


def _build_slug_index(state_dir: Path) -> dict[tuple[str, str], str]:
    """Map `(kind, target_slug(name))` to pair_id for every canonical in the store.

    Keyed on the canonical store (the source of truth, NFR-16/FR-16) rather than on
    managed state, so a sequence of imports reconciles against on-disk canonicals —
    including ones an earlier import wrote that the daemon has not yet adopted into
    state — and never mints a duplicate at the same slug.
    """
    slug_index: dict[tuple[str, str], str] = {}
    for local_pair_id in list_canonical_ids(state_dir):
        canonical = load_canonical(state_dir, local_pair_id)
        if canonical is None:
            continue
        slug = target_slug(canonical["name"])
        slug_index[(canonical["kind"], slug)] = local_pair_id
    return slug_index


def _decide_collision(
    *,
    imported_last_modified: float,
    local_last_modified: float,
    strategy: CollisionStrategy,
) -> bool:
    """Whether the import wins against a colliding local artifact (US-12 AC-6).

    ``mtime_wins`` uses wall-clock ``last_modified`` (FR-12 / AC-17); ties favour
    the local artifact (default-deny on rewrite). The host-local ``generation``
    counter is not a cross-host discriminator.
    """
    if strategy == "skip":
        return False
    if strategy == "overwrite":
        return True
    return imported_last_modified > local_last_modified


def _classify(
    canonicals: dict[str, dict[str, Any]],
    state: dict[str, CustomizationArtifactState],
    state_dir: Path,
    strategy: CollisionStrategy,
) -> list[_ImportDecision]:
    """Reconcile imported candidates by ``(kind, target_slug(name))`` — across the
    imported set (AC-17) and against local state (AC-6/AC-7) — to one winner per
    slug. The winning content is written under the local id when one exists at
    that slug (AC-17 reuse), else the winner's own id; losers are retired.
    """
    slug_index = _build_slug_index(state_dir)

    # Group imported candidates by slug (sorted ids → stable lexicographic tie).
    groups: dict[tuple[str, str], list[str]] = {}
    meta: dict[str, tuple[dict[str, Any], float]] = {}
    for imported_pair_id in sorted(canonicals):
        doc_copy = dict(canonicals[imported_pair_id])
        metadata = canonical_metadata(doc_copy)
        if metadata:
            last_modified = canonical_last_modified(doc_copy) or 0.0
        else:
            last_modified = float(doc_copy.pop("last_modified", 0.0))
            generation = int(doc_copy.pop("generation", 0))
            set_canonical_metadata(
                doc_copy,
                last_modified=last_modified,
                generation=generation,
            )
        kind = doc_copy["kind"]
        slug = target_slug(doc_copy["name"])
        meta[imported_pair_id] = (doc_copy, last_modified)
        groups.setdefault((kind, slug), []).append(imported_pair_id)

    decisions: list[_ImportDecision] = []
    for (kind, slug), candidate_ids in groups.items():
        # Intra-import winner: highest last_modified; ties → lexicographically
        # first (candidate_ids is sorted), per AC-17.
        winner = max(candidate_ids, key=lambda pid: meta[pid][1])
        winner_doc, winner_lm = meta[winner]

        winner_has_canonical = canonical_path(state_dir, winner).exists()
        local_pair_id = winner if winner_has_canonical else slug_index.get((kind, slug))
        if local_pair_id is None:
            accepted, displaces, surviving = True, None, winner
        else:
            accepted = _decide_collision(
                imported_last_modified=winner_lm,
                local_last_modified=_local_last_modified(state, state_dir, local_pair_id),
                strategy=strategy,
            )
            displaces = local_pair_id if accepted else None
            surviving = local_pair_id  # reuse the local id (AC-17)

        decisions.append(
            _ImportDecision(
                pair_id=winner,
                canonical=winner_doc,
                last_modified=winner_lm,
                generation=0,
                accepted=accepted,
                displaces_local_pair_id=displaces,
                surviving_pair_id=surviving,
            )
        )
        # Losers in this group are retired (merged away).
        for loser in candidate_ids:
            if loser == winner:
                continue
            decisions.append(
                _ImportDecision(
                    pair_id=loser,
                    canonical=meta[loser][0],
                    last_modified=meta[loser][1],
                    generation=0,
                    accepted=False,
                    displaces_local_pair_id=None,
                    surviving_pair_id=loser,
                )
            )
    return decisions


def preview_import(
    state_dir: Path,
    zip_path: Path,
    *,
    strategy: CollisionStrategy,
) -> tuple[list[str], list[str]]:
    """Return (would_overwrite, would_skip) pair_ids without touching disk.

    ``would_overwrite`` lists every local pair_id that this import would
    displace or rewrite. Useful for CLI gating: ``--force`` requirement
    is only meaningful when this list is non-empty (audit slice 08 ·
    CQ-07).
    """
    manifest, canonicals = _read_zip_entries(zip_path)
    _validate_manifest_version(manifest)
    state = load_state(state_dir)
    decisions = _classify(canonicals, state, state_dir, strategy)
    would_overwrite: list[str] = []
    would_skip: list[str] = []
    for decision in decisions:
        if decision.accepted and decision.displaces_local_pair_id is not None:
            would_overwrite.append(decision.displaces_local_pair_id)
        elif not decision.accepted:
            would_skip.append(decision.pair_id)
    return would_overwrite, would_skip


def import_from_zip(
    state_dir: Path,
    zip_path: Path,
    *,
    strategy: CollisionStrategy,
    config: dict[str, Any],
    agentic_tools: dict[str, AgenticToolSpec],
) -> ImportReport:
    """Restore artifacts from a customization library export.

    Transactional contract (AC-10):

    1. Decisions are computed entirely in memory before any disk write.
    2. Every accepted canonical is staged to ``state_dir/.import_pending_<uuid>/``
       first; only after *all* stagings succeed are the staged files
       promoted into the live ``canonical/`` directory via ``os.replace``.
       If staging raises midway, the pending directory is removed and no
       canonical is touched.
    3. ``state.json`` is the last thing written. A failure during the
       tool-side projection step does not corrupt state.json — the next
       sync poll will reconcile from a clean ``canonical/`` directory.

    Note: tool-side files are *not* staged in Phase 1; a mid-import
    failure during tool projection still leaves the already-projected
    tool files in place. Adding tool-side staging requires the
    polymorphic ``FileLayout`` from Phase 2; it is tracked separately.
    """
    if strategy not in ALLOWED_STRATEGIES:
        raise PortableArchiveError(
            f"Unknown collision strategy: {strategy!r}; expected one of "
            f"{sorted(ALLOWED_STRATEGIES)}"
        )

    manifest, canonicals = _read_zip_entries(zip_path)
    _validate_manifest_version(manifest)

    state = load_state(state_dir)
    decisions = _classify(canonicals, state, state_dir, strategy)

    skipped_secret_artifacts = _filter_secret_bearing_decisions(decisions, config)

    tool_status = ToolStatusTracker(config, agentic_tools)
    tool_status.refresh()

    accepted_decisions = [d for d in decisions if d.accepted]

    # Canonical-only import (US-12 AC-5): write the winning canonical under its
    # surviving id; `import` writes neither state.json nor any tool root. The next
    # sync_once adopts each new canonical (orphan -> stub -> project, FR-16) and
    # re-projects each overwritten canonical via FR-14 digest mismatch — making
    # state.json solely the daemon's to write, so a concurrent poll cannot lose a
    # state update (FR-15).
    _stage_and_promote_canonicals(state_dir, accepted_decisions)
    return _build_import_report(decisions, strategy, skipped_secret_artifacts)


def _filter_secret_bearing_decisions(
    decisions: list[_ImportDecision], config: dict[str, Any]
) -> list[str]:
    """Per-artifact secret filter (US-12 AC-15 / AC-16). The receiver's policy
    ALWAYS overrides whatever the source-host policy was. Under secrets_refused,
    secret-bearing canonicals are de-accepted with one structured WARNING each;
    under secrets_accepted, all are imported verbatim and one summary WARNING is
    emitted. Returns the pair_ids skipped under secrets_refused."""
    raw_policy = str(
        config.get("secret_policy") or config.get("mcp_server_secret_policy") or "secrets_refused"
    )
    normalized_policy = normalize_secret_policy(
        raw_policy,
        source="import_from_zip",
        warn_deprecated=False,
    )
    skipped_secret_artifacts: list[str] = []
    secret_bearing_artifacts: list[str] = []
    for decision in decisions:
        if not decision.accepted:
            continue
        findings = find_mcp_secret_literals(decision.canonical)
        if not findings:
            continue
        field_paths = [f.field_path for f in findings]
        if normalized_policy == "secrets_refused":
            logging.warning(
                "Skipping import of artifact with literal secret material "
                "under secret_policy=secrets_refused: "
                "pair_id=%s fields=%s",
                decision.pair_id,
                field_paths,
            )
            decision.accepted = False
            skipped_secret_artifacts.append(decision.pair_id)
        else:
            secret_bearing_artifacts.append(decision.pair_id)

    if secret_bearing_artifacts:
        logging.warning(
            "Customization library import under secret_policy=secrets_accepted: "
            "%d artifact(s) carry literal secret material: %s",
            len(secret_bearing_artifacts),
            secret_bearing_artifacts,
        )
    return skipped_secret_artifacts


def _stage_and_promote_canonicals(
    state_dir: Path, accepted_decisions: list[_ImportDecision]
) -> None:
    """Stage every accepted canonical under its SURVIVING id, then promote
    atomically per-artifact (FR-13). A displaced live canonical is archived before
    overwrite (NFR-01, US-12 AC-17). A failure leaves a strict prefix promoted and
    state untouched."""
    pending_dir = state_dir / f".import_pending_{uuid.uuid4().hex[:8]}"
    pending_dir.mkdir(parents=True, exist_ok=True)
    try:
        staged: list[tuple[Path, Path, str]] = []  # (pending_path, live_path, surviving_id)
        for decision in accepted_decisions:
            canonical = dict(decision.canonical)
            canonical["pair_id"] = decision.surviving_pair_id
            pending_path = pending_dir / f"{decision.surviving_pair_id}.json"
            save_canonical_to(pending_path, canonical)
            staged.append(
                (
                    pending_path,
                    canonical_path(state_dir, decision.surviving_pair_id),
                    decision.surviving_pair_id,
                )
            )
    except Exception:
        shutil.rmtree(pending_dir, ignore_errors=True)
        raise
    try:
        for pending_path, live_path, surviving_id in staged:
            live_path.parent.mkdir(parents=True, exist_ok=True)
            if live_path.exists():
                # Overwrite: preserve the displaced local canonical before it is
                # replaced (NFR-01 archive-before-write for the canonical store;
                # the import loser is archived per US-12 AC-17). Covers the
                # stub-overwrite case where no tool-side files exist to recover from.
                archive_canonical(state_dir, surviving_id)
            os.replace(pending_path, live_path)
    finally:
        shutil.rmtree(pending_dir, ignore_errors=True)


def _build_import_report(
    decisions: list[_ImportDecision],
    strategy: str,
    skipped_secret_artifacts: list[str],
) -> ImportReport:
    """Build the import report. `import` writes canonical-only and never touches
    state.json (FR-16): the next sync_once adopts each new canonical (orphan → stub
    → project) and re-projects each overwritten managed canonical via the FR-14
    digest mismatch (the recorded digest is naturally stale because state was not
    touched). state.json stays solely the daemon's to write (FR-15)."""
    report = ImportReport(skipped_secret_artifacts=skipped_secret_artifacts)
    for decision in decisions:
        if not decision.accepted:
            report.skipped.append(decision.pair_id)
            logging.info(
                "Import skipped/merged (strategy=%s): pair_id=%s", strategy, decision.pair_id
            )
            continue
        report.accepted.append(decision.surviving_pair_id)
        logging.info("Import accepted (canonical-only): pair_id=%s", decision.surviving_pair_id)
    return report


def save_canonical_to(path: Path, canonical: dict[str, Any]) -> None:
    """Write a canonical document directly to ``path`` (no pair_id derivation).

    Used by ``import_from_zip`` to stage canonicals into a pending directory
    before promoting them into the live ``canonical/`` tree.
    """
    from agents_sync.state import atomic_write_text

    atomic_write_text(
        path,
        json.dumps(canonical, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )
