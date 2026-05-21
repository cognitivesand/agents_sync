"""Portable library snapshot — export and import for US-12 / FR-07 / FR-08.

A portable library snapshot is a single zip file capturing every
managed customization_artifact's canonical document plus a small
manifest. It is portable across hosts: `state.json` and the on-disk
`archive/` directory are deliberately excluded because they hold
host-specific bytes.

Two operations:

  - `export_to_zip`: writes the snapshot. Read-only against the source
    state directory; the zip is materialised atomically (write to a
    sibling temp file, then `os.replace`).
  - `import_from_zip`: reads a snapshot and synchronously projects every
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
import socket
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from agents_sync import archive
from agents_sync.agentic_tool_spec import AgenticToolSpec
from agents_sync.canonical import canonical_path, load_canonical, save_canonical
from agents_sync.identity import InvalidPairId, validate_pair_id
from agents_sync.rendering import render_to_agentic_tool, update_state_n_way
from agents_sync.state import (
    CustomizationArtifactState,
    load_state,
    save_state,
    target_slug,
)
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


@dataclass
class ImportReport:
    accepted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    archived_local: list[tuple[str, str]] = field(default_factory=list)


# ---------------- export ----------------


def _agents_sync_version() -> str:
    from agents_sync import __version__

    return __version__


def _build_manifest(artifact_count: int) -> dict[str, Any]:
    return {
        "schema_version": PORTABLE_ARCHIVE_SCHEMA_VERSION,
        "exported_at": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(),
        "source_host": socket.gethostname(),
        "source_platform": platform.system(),
        "agents_sync_version": _agents_sync_version(),
        "artifact_count": artifact_count,
    }


def export_to_zip(state_dir: Path, zip_path: Path) -> ExportReport:
    """Write a portable library snapshot to `zip_path` (atomic replace)."""
    state = load_state(state_dir)
    canonicals: dict[str, dict[str, Any]] = {}
    for pair_id, ps in state.items():
        canonical = load_canonical(state_dir, pair_id)
        if canonical is None:
            logging.warning(
                "Skipping pair with missing canonical during export: pair_id=%s",
                pair_id,
            )
            continue
        entry = dict(canonical)
        entry["last_modified"] = (
            ps.last_modified if ps.last_modified is not None else 0.0
        )
        canonicals[pair_id] = entry

    manifest = _build_manifest(len(canonicals))
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
    return ExportReport(archive_path=zip_path, artifact_count=len(canonicals))


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


@dataclass
class _ImportDecision:
    """One per accepted-or-skipped artifact, fully resolved before disk writes."""

    pair_id: str
    canonical: dict[str, Any]
    last_modified: float
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
    local_pair_id: str,
    local_last_modified: float,
    strategy: CollisionStrategy,
) -> tuple[bool, str | None]:
    """Return (accept_import, displaces_local_pair_id_or_None) per strategy.

    AC-6 tie rule: ties on `mtime_wins` favour the local artifact
    (default-deny on rewrite — protects against clock skew).
    """
    if strategy == "skip":
        return False, None
    if strategy == "overwrite":
        return True, local_pair_id
    # mtime_wins
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
                    accepted=True,
                    displaces_local_pair_id=None,
                )
            )
            continue

        accept, displaces = _decide_collision(
            imported_pair_id=imported_pair_id,
            imported_last_modified=imported_last_modified,
            local_pair_id=local_pair_id,
            local_last_modified=_local_last_modified(state, local_pair_id),
            strategy=strategy,
        )
        decisions.append(
            _ImportDecision(
                pair_id=imported_pair_id,
                canonical=doc_copy,
                last_modified=imported_last_modified,
                accepted=accept,
                displaces_local_pair_id=displaces,
            )
        )
    return decisions


def _archive_displaced_tool_files(
    state_dir: Path,
    state: dict[str, CustomizationArtifactState],
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
        path = Path(at.path)
        if not path.exists():
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
        if not tool_status.is_kind_available(tool_name, kind):
            continue
        result.append((tool_name, spec))
    return result


def import_from_zip(
    state_dir: Path,
    zip_path: Path,
    *,
    strategy: CollisionStrategy,
    config: dict[str, Any],
    agentic_tools: dict[str, AgenticToolSpec],
) -> ImportReport:
    """Restore artifacts from a portable library snapshot.

    Projection is synchronous: every accepted artifact is rendered to
    disk before the function returns, and `state.json` is the last
    thing written (AC-10 transactional guarantee).
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

    tool_status = ToolStatusTracker(config, agentic_tools)
    tool_status.refresh()

    report = ImportReport()
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
                decision.displaces_local_pair_id,
                move=slug_displacement,
            )
            report.archived_local.extend(archived)
            if slug_displacement:
                # Slug collision with a different local pair_id: drop the
                # local entry (its canonical and state entry are about to be
                # replaced by this imported artifact's identity).
                state.pop(decision.displaces_local_pair_id, None)
                local_canonical = canonical_path(
                    state_dir, decision.displaces_local_pair_id
                )
                if local_canonical.exists():
                    local_canonical.unlink()

        kind = decision.canonical["kind"]
        save_canonical(state_dir, decision.pair_id, decision.canonical)

        paths: dict[str, Path] = {}
        for tool_name, spec in _participating_tools(
            kind, config, agentic_tools, tool_status
        ):
            existing_path = None
            if (
                decision.pair_id in state
                and tool_name in state[decision.pair_id].agentic_tools
            ):
                existing_path = Path(state[decision.pair_id].agentic_tools[tool_name].path)
            target = render_to_agentic_tool(
                config,
                spec,
                kind,
                decision.canonical,
                existing_path=existing_path,
                prior_text=None,
                source_dir=None,
            )
            paths[tool_name] = target

        update_state_n_way(state, decision.pair_id, kind, paths, agentic_tools)
        # Adoption stamps last_modified = time.time(); we overwrite with
        # the imported value so cross-host equality and the mtime_wins
        # comparison stay consistent (a re-export from this host carries
        # the source host's original timestamp).
        state[decision.pair_id].last_modified = decision.last_modified

        report.accepted.append(decision.pair_id)
        logging.info(
            "Import accepted: pair_id=%s strategy=%s projected_tools=%s",
            decision.pair_id, strategy, sorted(paths.keys()),
        )

    save_state(state_dir, state)
    return report
