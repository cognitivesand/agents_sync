"""Artifact archive — archive-before-write + tiered retention GC (NFR-01/07, US-05).

Anything that would overwrite or remove user-authored content first preserves the
prior bytes at ``<state_dir>/archive/<artifact_id>/<side>/<name>.<ISO-timestamp>``:
``archive_copy`` snapshots (original remains — adoption pre-injection),
``archive_move`` relocates (original gone — conflict-loser overwrite, delete
propagation), ``archive_text`` snapshots an in-memory payload (a keyed-map slot's
prior serialization). The archive is append-only, so ``prune_archive`` bounds its
growth on a tiered, age-based schedule (dense recent history, thinned older
history); an entry whose timestamp it cannot parse is NEVER deleted — GC must not
destroy data it does not understand. The GC summary is returned as a ``GcReport``;
logging it is the daemon's concern (S22). Archiving a dropped artifact's stored
canonical lands with its consumer, the executor (S19).
"""

from __future__ import annotations

import datetime as dt
import shutil
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from agents_sync.atomic_file_writer import (
    move_file_atomic,
    retry_transient_io,
    write_text_atomic,
)
from agents_sync.domain_model.artifact_identity import validate_artifact_id
from agents_sync.domain_model.artifact_naming import slugify_name

_TIMESTAMP_FORMAT = "%Y-%m-%dT%H-%M-%S-%fZ"  # ISO 8601 UTC, ':' -> '-' for filesystems
_MAX_SLOT_COMPONENT_LENGTH = 128

# Tiered retention (NFR-07): a boundary age falls in the OLDER tier.
KEEP_ALL_WITHIN_DAYS = 7
DOWNSAMPLE_DAYS = 30
RETAIN_DAYS = 365
KEEP_PER_DAY_RECENT = 4
KEEP_PER_DAY_OLD = 1


# --- archive-before-write primitives (NFR-01) ---------------------------------------


def archive_copy(state_dir: Path, artifact_id: str, side: str, source: Path) -> Path:
    """Snapshot ``source`` into the per-artifact archive; the original remains."""
    target = _archive_target(state_dir, artifact_id, side, source.name)
    if source.is_dir():
        retry_transient_io(lambda: shutil.copytree(source, target))
    else:
        retry_transient_io(lambda: shutil.copy2(source, target))
    return target


def archive_move(state_dir: Path, artifact_id: str, side: str, source: Path) -> Path:
    """Relocate ``source`` into the per-artifact archive; the original is gone."""
    if source.is_dir():
        side_dir = _side_directory(state_dir, artifact_id, side)

        def _move_to_fresh_target() -> Path:
            # A fresh unique target per attempt: shutil.move into an EXISTING dir
            # nests instead of replacing, so retrying onto a partial prior attempt
            # (cross-device fallback) would silently malform the entry. A failed
            # attempt's partial leftover is junk the tiers age out, never a target.
            attempt_target = _unique_entry_path(side_dir, source.name)
            shutil.move(str(source), str(attempt_target))
            return attempt_target

        return retry_transient_io(_move_to_fresh_target)
    target = _archive_target(state_dir, artifact_id, side, source.name)
    move_file_atomic(source, target)
    return target


def archive_text(
    state_dir: Path,
    artifact_id: str,
    side: str,
    slot_name: str,
    extension: str,
    content: str,
) -> Path:
    """Snapshot a literal text payload (a keyed-map slot's prior serialization).

    Slot names are raw user-supplied map keys: a traversal-shaped key is slugified
    so the entry cannot escape the per-artifact directory, and the resolved target
    is verified to stay inside it before any write.
    """
    safe_slot = slugify_name(slot_name)[:_MAX_SLOT_COMPONENT_LENGTH]
    side_dir = _side_directory(state_dir, artifact_id, side)
    target = _unique_entry_path(side_dir, f"{safe_slot}{extension}")
    # Containment is anchored to the independently computed side directory — an
    # anchor derived from the target itself would move with a traversal and never
    # fail. The extension is the unslugified ingredient this guards against.
    if not target.resolve().is_relative_to(side_dir.resolve()):
        raise ValueError(
            f"archive target {target} escapes {side_dir} "
            f"(slot_name={slot_name!r}, extension={extension!r}); refusing to write"
        )
    write_text_atomic(target, content)
    return target


def _archive_target(state_dir: Path, artifact_id: str, side: str, entry_name: str) -> Path:
    """The unique target path for one archive entry (parent created)."""
    return _unique_entry_path(_side_directory(state_dir, artifact_id, side), entry_name)


def _side_directory(state_dir: Path, artifact_id: str, side: str) -> Path:
    side_dir = state_dir / "archive" / validate_artifact_id(artifact_id) / side
    retry_transient_io(lambda: side_dir.mkdir(parents=True, exist_ok=True))
    return side_dir


def _unique_entry_path(side_dir: Path, entry_name: str) -> Path:
    """``<entry_name>.<random>.<timestamp>`` — the random token rules out the
    same-microsecond collision that would silently overwrite a preserved entry;
    the timestamp stays the final dot-segment, where the GC parser reads it."""
    unique_token = uuid.uuid4().hex[:6]
    timestamp = dt.datetime.now(tz=dt.UTC).strftime(_TIMESTAMP_FORMAT)
    return side_dir / f"{entry_name}.{unique_token}.{timestamp}"


# --- tiered retention GC (NFR-07) ----------------------------------------------------


@dataclass
class GcReport:
    """Outcome of one prune pass (the daemon logs it — S22)."""

    scanned: int = 0
    kept: int = 0
    deleted: int = 0
    unparseable: int = 0
    bytes_reclaimed: int = 0
    deleted_paths: list[Path] = field(default_factory=list)


def prune_archive(state_dir: Path, *, now: dt.datetime | None = None) -> GcReport:
    """Prune the archive per the tiered policy; ``now`` is injectable for tests."""
    moment = now or dt.datetime.now(tz=dt.UTC)
    report = GcReport()
    archive_root = state_dir / "archive"
    if not archive_root.is_dir():
        return report
    for artifact_dir in sorted(archive_root.iterdir()):
        if not artifact_dir.is_dir():
            continue
        for side_dir in sorted(artifact_dir.iterdir()):
            if side_dir.is_dir():
                _prune_side_dir(side_dir, moment, report)
    return report


def _prune_side_dir(side_dir: Path, moment: dt.datetime, report: GcReport) -> None:
    dated_entries: list[tuple[dt.datetime, Path]] = []
    for entry in side_dir.iterdir():
        report.scanned += 1
        timestamp = _parse_entry_timestamp(entry.name)
        if timestamp is None:
            # Fail-safe: never delete what GC does not understand, however old.
            report.unparseable += 1
            report.kept += 1
            continue
        dated_entries.append((timestamp, entry))

    kept_count, doomed_entries = _apply_tiered_policy(dated_entries, moment)
    report.kept += kept_count
    for entry in doomed_entries:
        entry_size = _entry_size(entry)
        _remove_entry(entry)
        report.deleted += 1
        report.bytes_reclaimed += entry_size
        report.deleted_paths.append(entry)


def _apply_tiered_policy(
    dated_entries: list[tuple[dt.datetime, Path]],
    moment: dt.datetime,
) -> tuple[int, list[Path]]:
    """One (artifact_id, side) directory's tier outcome: ``(kept_count, to_delete)``."""
    recent_by_day: dict[dt.date, list[tuple[dt.datetime, Path]]] = defaultdict(list)
    old_by_day: dict[dt.date, list[tuple[dt.datetime, Path]]] = defaultdict(list)
    kept_count = 0
    to_delete: list[Path] = []

    for timestamp, entry in dated_entries:
        age_days = (moment - timestamp).days
        if age_days < KEEP_ALL_WITHIN_DAYS:
            kept_count += 1
        elif age_days < DOWNSAMPLE_DAYS:
            recent_by_day[timestamp.date()].append((timestamp, entry))
        elif age_days < RETAIN_DAYS:
            old_by_day[timestamp.date()].append((timestamp, entry))
        else:
            to_delete.append(entry)

    tiers = ((recent_by_day, KEEP_PER_DAY_RECENT), (old_by_day, KEEP_PER_DAY_OLD))
    for day_buckets, keep_per_day in tiers:
        for day_entries in day_buckets.values():
            day_entries.sort(key=lambda pair: pair[0], reverse=True)  # newest first
            kept_count += min(keep_per_day, len(day_entries))
            to_delete.extend(entry for _, entry in day_entries[keep_per_day:])
    return kept_count, to_delete


def _parse_entry_timestamp(entry_name: str) -> dt.datetime | None:
    """The UTC datetime encoded in an entry name's final dot-segment, or ``None``."""
    _, _, suffix = entry_name.rpartition(".")
    if not suffix:
        return None
    try:
        return dt.datetime.strptime(suffix, _TIMESTAMP_FORMAT).replace(tzinfo=dt.UTC)
    except ValueError:
        return None


def _entry_size(path: Path) -> int:
    if path.is_dir():
        return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _remove_entry(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
