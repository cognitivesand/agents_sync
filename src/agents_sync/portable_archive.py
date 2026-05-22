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

from agents_sync import archive
from agents_sync.agentic_tool_spec import AgenticToolSpec, SharedKeyedMapLayout
from agents_sync.canonical import canonical_path, load_canonical, save_canonical
from agents_sync.filesystem_windows_retry import retry_fs
from agents_sync.identity import InvalidPairId, validate_pair_id
from agents_sync.mcp_secret_policy import (
    find_mcp_secret_literals,
    normalize_secret_policy,
)
from agents_sync.rendering import render_to_agentic_tool, update_state_n_way
from agents_sync.shared_keyed_map_io import apply_slot, read_slots
from agents_sync.state import (
    CustomizationArtifactState,
    load_state,
    save_state,
    target_slug,
)
from agents_sync.sync_types import RenderResult
from agents_sync.tool_status import ToolStatusTracker


PORTABLE_ARCHIVE_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
CANONICAL_PREFIX = "canonical/"

CollisionStrategy = Literal["skip", "mtime_wins", "overwrite"]
ALLOWED_STRATEGIES: frozenset[CollisionStrategy] = frozenset(
    {"skip", "mtime_wins", "overwrite"}
)


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
    artifact_count: int, *, contains_secret_literals: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": PORTABLE_ARCHIVE_SCHEMA_VERSION,
        "exported_at": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(),
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
        secret_policy, source="export_to_zip", warn_deprecated=False,
    )
    state = load_state(state_dir)
    canonicals: dict[str, dict[str, Any]] = {}
    skipped_secret_artifacts: list[str] = []
    secret_bearing_artifacts: list[str] = []
    for pair_id, ps in state.items():
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
                    pair_id, field_paths,
                )
                skipped_secret_artifacts.append(pair_id)
                continue
            # secrets_accepted — include verbatim, summary warning emitted below
            secret_bearing_artifacts.append(pair_id)
        entry = dict(canonical)
        entry["last_modified"] = (
            ps.last_modified if ps.last_modified is not None else 0.0
        )
        entry["generation"] = ps.generation
        canonicals[pair_id] = entry

    if secret_bearing_artifacts:
        logging.warning(
            "Customization library export under secret_policy=secrets_accepted: "
            "%d artifact(s) carry literal secret material: %s",
            len(secret_bearing_artifacts), secret_bearing_artifacts,
        )

    contains_secret_literals = bool(secret_bearing_artifacts)
    manifest = _build_manifest(
        len(canonicals), contains_secret_literals=contains_secret_literals,
    )
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{zip_path.name}.", suffix=".tmp", dir=str(zip_path.parent)
    )
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            )
            for pair_id, entry in sorted(canonicals.items()):
                zf.writestr(
                    f"{CANONICAL_PREFIX}{pair_id}.json",
                    json.dumps(entry, indent=2, sort_keys=True, ensure_ascii=False)
                    + "\n",
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
            raise PortableArchiveError(
                f"Archive is missing {MANIFEST_NAME}: {zip_path}"
            )
        try:
            manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PortableArchiveError(
                f"Archive {MANIFEST_NAME} is unparseable: {exc}"
            ) from exc
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
                raise PortableArchiveError(
                    f"Archive entry has invalid pair_id: {name}"
                ) from exc
            try:
                doc = json.loads(zf.read(name).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise PortableArchiveError(
                    f"Archive entry is unparseable: {name}: {exc}"
                ) from exc
            if not isinstance(doc, dict):
                raise PortableArchiveError(
                    f"Archive entry is not a JSON object: {name}"
                )
            if doc.get("pair_id") != pair_id:
                raise PortableArchiveError(
                    f"Archive entry pair_id mismatch: filename={pair_id} "
                    f"document={doc.get('pair_id')!r}"
                )
            if "kind" not in doc or "name" not in doc:
                raise PortableArchiveError(
                    f"Archive entry missing kind/name: {name}"
                )
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
    state: dict[str, CustomizationArtifactState], pair_id: str
) -> float:
    ps = state.get(pair_id)
    if ps is None or ps.last_modified is None:
        return 0.0
    return ps.last_modified


def _local_generation(
    state: dict[str, CustomizationArtifactState], pair_id: str
) -> int:
    ps = state.get(pair_id)
    return ps.generation if ps is not None else 0


@dataclass
class _ImportDecision:
    """One per accepted-or-skipped artifact, fully resolved before disk writes."""

    pair_id: str
    canonical: dict[str, Any]
    last_modified: float
    generation: int
    accepted: bool
    displaces_local_pair_id: str | None  # pair_id whose tool-side files to archive


def _build_slug_index(
    state: dict[str, CustomizationArtifactState], state_dir: Path
) -> dict[tuple[str, str], str]:
    """Map `(kind, target_slug(name))` to local pair_id for every managed pair."""
    slug_index: dict[tuple[str, str], str] = {}
    for local_pair_id, ps in state.items():
        canonical = load_canonical(state_dir, local_pair_id)
        if canonical is None:
            continue
        slug = target_slug(canonical["name"])
        slug_index[(ps.kind, slug)] = local_pair_id
    return slug_index


def _decide_collision(
    *,
    imported_pair_id: str,
    imported_last_modified: float,
    imported_generation: int,
    local_pair_id: str,
    local_last_modified: float,
    local_generation: int,
    strategy: CollisionStrategy,
) -> tuple[bool, str | None]:
    """Return (accept_import, displaces_local_pair_id_or_None) per strategy.

    AC-6 tie rule: ties on ``mtime_wins`` favour the local artifact
    (default-deny on rewrite — protects against clock skew).

    Comparison order: ``generation`` (monotonic, host-local) wins outright,
    with ``last_modified`` only as a tiebreaker when generations are equal.
    The generation field is host-local and only valid as a discriminator
    when imported state was produced on the same host that holds the local
    state, but for that common case it removes wall-clock-skew artifacts.
    """
    if strategy == "skip":
        return False, None
    if strategy == "overwrite":
        return True, local_pair_id
    # mtime_wins
    if imported_generation != local_generation:
        if imported_generation > local_generation:
            return True, local_pair_id
        return False, None
    if imported_last_modified > local_last_modified:
        return True, local_pair_id
    return False, None


def _classify(
    canonicals: dict[str, dict[str, Any]],
    state: dict[str, CustomizationArtifactState],
    state_dir: Path,
    strategy: CollisionStrategy,
) -> list[_ImportDecision]:
    slug_index = _build_slug_index(state, state_dir)
    decisions: list[_ImportDecision] = []
    for imported_pair_id, doc in canonicals.items():
        doc_copy = dict(doc)
        imported_last_modified = float(doc_copy.pop("last_modified", 0.0))
        try:
            imported_generation = int(doc_copy.pop("generation", 0) or 0)
        except (TypeError, ValueError):
            imported_generation = 0
        kind = doc_copy["kind"]
        slug = target_slug(doc_copy["name"])

        local_pair_id: str | None = None
        if imported_pair_id in state:
            local_pair_id = imported_pair_id
        else:
            local_pair_id = slug_index.get((kind, slug))

        if local_pair_id is None:
            decisions.append(
                _ImportDecision(
                    pair_id=imported_pair_id,
                    canonical=doc_copy,
                    last_modified=imported_last_modified,
                    generation=imported_generation,
                    accepted=True,
                    displaces_local_pair_id=None,
                )
            )
            continue

        accept, displaces = _decide_collision(
            imported_pair_id=imported_pair_id,
            imported_last_modified=imported_last_modified,
            imported_generation=imported_generation,
            local_pair_id=local_pair_id,
            local_last_modified=_local_last_modified(state, local_pair_id),
            local_generation=_local_generation(state, local_pair_id),
            strategy=strategy,
        )
        decisions.append(
            _ImportDecision(
                pair_id=imported_pair_id,
                canonical=doc_copy,
                last_modified=imported_last_modified,
                generation=imported_generation,
                accepted=accept,
                displaces_local_pair_id=displaces,
            )
        )
    return decisions


def _archive_displaced_tool_files(
    state_dir: Path,
    state: dict[str, CustomizationArtifactState],
    agentic_tools: dict[str, AgenticToolSpec],
    local_pair_id: str,
    *,
    move: bool,
) -> list[tuple[str, str]]:
    """Archive every tool-side file the local pair currently owns.

    `move=True` ⇒ the original is removed from disk (used when the
    imported identity will reclaim the same slug under a different
    pair_id; the local artifact's bytes are preserved in the archive
    but its directory must be cleared so the import can take over).
    `move=False` ⇒ the original stays in place (used when the same
    pair_id is being re-rendered; atomic_write_text overwrites
    SKILL.md while keeping any auxiliary files).
    """
    archived: list[tuple[str, str]] = []
    ps = state.get(local_pair_id)
    if ps is None:
        return archived
    for tool_name, at in ps.agentic_tools.items():
        path = at.path
        if not path.exists():
            continue
        spec = agentic_tools.get(tool_name)
        io = spec.io.get(ps.kind) if spec is not None else None
        if (
            io is not None
            and isinstance(io.file_layout, SharedKeyedMapLayout)
            and at.slot is not None
        ):
            slots, _ = read_slots(path, io.file_layout)
            slot_text = slots.get(at.slot)
            if slot_text is None:
                continue
            archive.archive_text(
                state_dir,
                local_pair_id,
                tool_name,
                slot_name=at.slot,
                extension=io.file_layout.file_suffix,
                content=slot_text,
            )
            if move:
                apply_slot(path, io.file_layout, at.slot, None)
            archived.append((local_pair_id, tool_name))
            continue
        if move:
            archive.archive_move(state_dir, local_pair_id, tool_name, path)
        else:
            archive.archive_copy(state_dir, local_pair_id, tool_name, path)
        archived.append((local_pair_id, tool_name))
    return archived


def _participating_tools(
    kind: str,
    config: dict[str, Any],
    agentic_tools: dict[str, AgenticToolSpec],
    tool_status: ToolStatusTracker,
) -> list[tuple[str, AgenticToolSpec]]:
    """The tools that import will actually project onto for `kind`.

    Filter mirrors the daemon's per-poll filter: enabled (not disabled
    by config), supporting this `kind`, and currently `available`
    (US-11). Disabled or unavailable tools get no state entry; the
    extend-to-new-tools branch in adoption.py will catch them up later.
    """
    result: list[tuple[str, AgenticToolSpec]] = []
    for tool_name, spec in agentic_tools.items():
        if kind not in spec.io:
            continue
        if not tool_status.is_available(tool_name):
            continue
        result.append((tool_name, spec))
    return result


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

    # Per-artifact secret filter (US-12 AC-15 / AC-16). The receiver's
    # policy ALWAYS overrides whatever the source-host policy was. Under
    # secrets_refused, secret-bearing canonicals are skipped with one
    # structured WARNING each; under secrets_accepted, all are imported
    # verbatim and one summary WARNING is emitted.
    raw_policy = str(
        config.get("secret_policy")
        or config.get("mcp_server_secret_policy")
        or "secrets_refused"
    )
    normalized_policy = normalize_secret_policy(
        raw_policy, source="import_from_zip", warn_deprecated=False,
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
                decision.pair_id, field_paths,
            )
            decision.accepted = False
            skipped_secret_artifacts.append(decision.pair_id)
        else:
            secret_bearing_artifacts.append(decision.pair_id)

    if secret_bearing_artifacts:
        logging.warning(
            "Customization library import under secret_policy=secrets_accepted: "
            "%d artifact(s) carry literal secret material: %s",
            len(secret_bearing_artifacts), secret_bearing_artifacts,
        )

    tool_status = ToolStatusTracker(config, agentic_tools)
    tool_status.refresh()

    accepted_decisions = [d for d in decisions if d.accepted]

    # Phase A — stage every accepted canonical. If anything raises here,
    # the pending dir is removed and the live state is untouched.
    pending_dir = state_dir / f".import_pending_{uuid.uuid4().hex[:8]}"
    pending_dir.mkdir(parents=True, exist_ok=True)
    try:
        staged: list[tuple[Path, Path]] = []  # (pending_path, live_path)
        for decision in accepted_decisions:
            pending_path = pending_dir / f"{decision.pair_id}.json"
            save_canonical_to(pending_path, decision.canonical)
            staged.append(
                (pending_path, canonical_path(state_dir, decision.pair_id))
            )
    except Exception:
        shutil.rmtree(pending_dir, ignore_errors=True)
        raise

    # Phase B — promote canonicals from staging into the live tree. Each
    # os.replace is atomic per inode; we order them so the first failure
    # leaves a strict prefix promoted (no partial-file canonicals).
    try:
        for pending_path, live_path in staged:
            live_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(pending_path, live_path)
    finally:
        # Whether or not the loop succeeded, drop the staging directory.
        # On success: it's empty. On partial failure: it may hold
        # un-promoted files, which we discard (the canonicals they would
        # have produced were never observed by the rest of the system).
        shutil.rmtree(pending_dir, ignore_errors=True)

    # Phase C — handle displacements, tool-side projection, and state
    # updates. This is the only phase that can leak partial tool-side
    # files on failure; state.json is still written last.
    report = ImportReport(skipped_secret_artifacts=skipped_secret_artifacts)
    for decision in decisions:
        if not decision.accepted:
            report.skipped.append(decision.pair_id)
            logging.info(
                "Import skipped (strategy=%s): pair_id=%s", strategy, decision.pair_id
            )
            continue

        if decision.displaces_local_pair_id is not None:
            slug_displacement = (
                decision.displaces_local_pair_id != decision.pair_id
            )
            archived = _archive_displaced_tool_files(
                state_dir,
                state,
                agentic_tools,
                decision.displaces_local_pair_id,
                move=slug_displacement,
            )
            report.archived_local.extend(archived)
            if slug_displacement:
                # Slug collision with a different local pair_id: drop the
                # local entry (its canonical and state entry are about to be
                # replaced by this imported artifact's identity). The
                # ``unlink`` is retried so a transient Windows lock (AV
                # scanner holding the JSON open) does not abort the import
                # mid-loop (audit slice 09 · CQ-07).
                state.pop(decision.displaces_local_pair_id, None)
                local_canonical = canonical_path(
                    state_dir, decision.displaces_local_pair_id
                )
                if local_canonical.exists():
                    retry_fs(
                        lambda p=local_canonical: p.unlink(),
                        operation=f"unlink {local_canonical}",
                    )

        kind = decision.canonical["kind"]

        results: dict[str, RenderResult] = {}
        for tool_name, spec in _participating_tools(
            kind, config, agentic_tools, tool_status
        ):
            existing_path = None
            existing_slot = None
            if (
                decision.pair_id in state
                and tool_name in state[decision.pair_id].agentic_tools
            ):
                existing = state[decision.pair_id].agentic_tools[tool_name]
                existing_path = Path(existing.path)
                existing_slot = existing.slot
            result = render_to_agentic_tool(
                config,
                spec,
                kind,
                decision.canonical,
                existing_path=existing_path,
                prior_text=None,
                source_dir=None,
                existing_slot=existing_slot,
            )
            results[tool_name] = result

        update_state_n_way(state, decision.pair_id, kind, results, agentic_tools)
        # Adoption stamps last_modified = time.time() and bumps generation;
        # we overwrite both with the imported values so cross-host equality
        # and the mtime_wins comparison stay consistent (a re-export from
        # this host carries the source host's original timestamp and
        # generation).
        state[decision.pair_id].last_modified = decision.last_modified
        state[decision.pair_id].generation = decision.generation

        report.accepted.append(decision.pair_id)
        logging.info(
            "Import accepted: pair_id=%s strategy=%s projected_tools=%s",
            decision.pair_id, strategy, sorted(results.keys()),
        )

    save_state(state_dir, state)
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
