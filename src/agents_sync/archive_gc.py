"""Tiered, age-based garbage collection for the data-preservation archive.

The archive (``archive/<pair_id>/<side>/<name>.<ISO-timestamp>``, see
``archive.py``) is append-only: every overwrite or delete snapshots the prior
bytes there (NFR-01). Without a bound it grows without limit (bug 602c6d, RC-5),
so NFR-07 requires bounded growth. This module prunes old entries on a
tiered, age-based schedule that keeps recent history dense and thins older
history, run from the ``agents-sync prune`` command and a low-frequency daemon
tick.

Policy (bug 602c6d §5.4):
  - younger than ``KEEP_ALL_WITHIN_DAYS``           : keep every entry.
  - ``KEEP_ALL_WITHIN_DAYS`` .. ``DOWNSAMPLE_DAYS`` : keep the newest
    ``KEEP_PER_DAY_RECENT`` entries per calendar day (UTC), per (pair_id, side).
  - ``DOWNSAMPLE_DAYS`` .. ``RETAIN_DAYS``          : keep the newest
    ``KEEP_PER_DAY_OLD`` per calendar day.
  - older than ``RETAIN_DAYS``                      : delete.

An entry whose timestamp suffix cannot be parsed is never deleted (fail-safe):
GC must never destroy data it does not understand.
"""

from __future__ import annotations

import datetime as _dt
import logging
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Must match archive.iso_timestamp's format (archive.py).
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H-%M-%S-%fZ"

KEEP_ALL_WITHIN_DAYS = 7
DOWNSAMPLE_DAYS = 30
RETAIN_DAYS = 365
KEEP_PER_DAY_RECENT = 4
KEEP_PER_DAY_OLD = 1


@dataclass
class GcReport:
    """Outcome of one prune pass."""

    scanned: int = 0
    kept: int = 0
    deleted: int = 0
    unparseable: int = 0
    bytes_reclaimed: int = 0
    deleted_paths: list[Path] = field(default_factory=list)


def _parse_timestamp(entry_name: str) -> _dt.datetime | None:
    """Return the UTC datetime encoded in an archive entry name, or None.

    The timestamp is the final ``.``-separated segment (it contains no ``.``);
    the preceding segments are the original filename, which may contain dots.
    """
    _, _, suffix = entry_name.rpartition(".")
    if not suffix:
        return None
    try:
        return _dt.datetime.strptime(suffix, _TIMESTAMP_FORMAT).replace(tzinfo=_dt.UTC)
    except ValueError:
        return None


def _entry_size(path: Path) -> int:
    if path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _entries_to_delete(
    dated: list[tuple[_dt.datetime, Path]],
    moment: _dt.datetime,
    report: GcReport,
) -> list[Path]:
    """Apply the tiered policy to one (pair_id, side) directory's dated entries."""
    recent_by_day: dict[_dt.date, list[tuple[_dt.datetime, Path]]] = defaultdict(list)
    old_by_day: dict[_dt.date, list[tuple[_dt.datetime, Path]]] = defaultdict(list)
    to_delete: list[Path] = []

    for timestamp, entry in dated:
        age_days = (moment - timestamp).days
        if age_days < KEEP_ALL_WITHIN_DAYS:
            report.kept += 1
        elif age_days < DOWNSAMPLE_DAYS:
            recent_by_day[timestamp.date()].append((timestamp, entry))
        elif age_days < RETAIN_DAYS:
            old_by_day[timestamp.date()].append((timestamp, entry))
        else:
            to_delete.append(entry)

    tiered = ((recent_by_day, KEEP_PER_DAY_RECENT), (old_by_day, KEEP_PER_DAY_OLD))
    for buckets, keep_per_day in tiered:
        for day_entries in buckets.values():
            day_entries.sort(key=lambda pair: pair[0], reverse=True)  # newest first
            report.kept += min(keep_per_day, len(day_entries))
            to_delete.extend(entry for _, entry in day_entries[keep_per_day:])

    return to_delete


def _prune_side_dir(side_dir: Path, moment: _dt.datetime, dry_run: bool, report: GcReport) -> None:
    dated: list[tuple[_dt.datetime, Path]] = []
    for entry in side_dir.iterdir():
        report.scanned += 1
        timestamp = _parse_timestamp(entry.name)
        if timestamp is None:
            report.unparseable += 1
            report.kept += 1
            continue
        dated.append((timestamp, entry))

    for entry in _entries_to_delete(dated, moment, report):
        size = _entry_size(entry)
        if not dry_run:
            _remove(entry)
        report.deleted += 1
        report.bytes_reclaimed += size
        report.deleted_paths.append(entry)


def prune_archive(
    state_dir: Path,
    *,
    now: _dt.datetime | None = None,
    dry_run: bool = False,
) -> GcReport:
    """Prune the archive under ``state_dir`` per the tiered policy. Returns a
    :class:`GcReport`. ``now`` is injectable for testing; ``dry_run`` reports
    what would be deleted without removing anything."""
    moment = now or _dt.datetime.now(tz=_dt.UTC)
    report = GcReport()
    archive_root = state_dir / "archive"
    if not archive_root.is_dir():
        return report

    for pair_dir in sorted(archive_root.iterdir()):
        if not pair_dir.is_dir():
            continue
        for side_dir in sorted(pair_dir.iterdir()):
            if side_dir.is_dir():
                _prune_side_dir(side_dir, moment, dry_run, report)

    if report.deleted or report.unparseable:
        logging.info(
            "Archive GC: scanned=%d kept=%d deleted=%d unparseable=%d "
            "bytes_reclaimed=%d%s",
            report.scanned,
            report.kept,
            report.deleted,
            report.unparseable,
            report.bytes_reclaimed,
            " (dry-run)" if dry_run else "",
        )
    return report
