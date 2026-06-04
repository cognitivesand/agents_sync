"""Tiered archive GC (NFR-07 / bug 602c6d RC-5): bounded archive growth.

Drives ``prune_archive`` against a hand-built archive tree with controlled
timestamps, asserting each retention tier and the fail-safe for unparseable
entries.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from agents_sync.archive_gc import (
    DOWNSAMPLE_DAYS,
    KEEP_ALL_WITHIN_DAYS,
    KEEP_PER_DAY_OLD,
    KEEP_PER_DAY_RECENT,
    RETAIN_DAYS,
    prune_archive,
)

_NOW = _dt.datetime(2026, 6, 4, 12, 0, 0, tzinfo=_dt.UTC)
_TS_FORMAT = "%Y-%m-%dT%H-%M-%S-%fZ"
_PAIR = "11111111-1111-4111-8111-111111111111"


def _side_dir(state_dir: Path) -> Path:
    side = state_dir / "archive" / _PAIR / "claude"
    side.mkdir(parents=True, exist_ok=True)
    return side


def _write_entry(side: Path, *, age_days: float, ordinal: int = 0) -> Path:
    """Create an archive file timestamped ``age_days`` before _NOW. ``ordinal``
    spaces entries within the same day so they remain distinct."""
    ts = _NOW - _dt.timedelta(days=age_days, seconds=ordinal)
    entry = side / f"CLAUDE.md.{ts.strftime(_TS_FORMAT)}"
    entry.write_text("snapshot", encoding="utf-8")
    return entry


def test_recent_entries_are_all_kept(tmp_path: Path) -> None:
    side = _side_dir(tmp_path)
    entries = [_write_entry(side, age_days=1, ordinal=i) for i in range(10)]

    report = prune_archive(tmp_path, now=_NOW)

    assert report.deleted == 0
    assert all(e.exists() for e in entries)


def test_midterm_downsamples_to_keep_per_day_recent(tmp_path: Path) -> None:
    side = _side_dir(tmp_path)
    # 10 entries all on the same calendar day, ~15 days old (midterm tier).
    age = (KEEP_ALL_WITHIN_DAYS + DOWNSAMPLE_DAYS) // 2  # 18 -> within [7,30)
    entries = [_write_entry(side, age_days=age, ordinal=i) for i in range(10)]

    report = prune_archive(tmp_path, now=_NOW)

    survivors = [e for e in entries if e.exists()]
    assert len(survivors) == KEEP_PER_DAY_RECENT
    assert report.deleted == 10 - KEEP_PER_DAY_RECENT


def test_longterm_downsamples_to_one_per_day(tmp_path: Path) -> None:
    side = _side_dir(tmp_path)
    age = (DOWNSAMPLE_DAYS + RETAIN_DAYS) // 2  # within [30,365)
    entries = [_write_entry(side, age_days=age, ordinal=i) for i in range(6)]

    prune_archive(tmp_path, now=_NOW)

    survivors = [e for e in entries if e.exists()]
    assert len(survivors) == KEEP_PER_DAY_OLD


def test_entries_beyond_retention_are_deleted(tmp_path: Path) -> None:
    side = _side_dir(tmp_path)
    entries = [_write_entry(side, age_days=RETAIN_DAYS + 10, ordinal=i) for i in range(3)]

    report = prune_archive(tmp_path, now=_NOW)

    assert report.deleted == 3
    assert not any(e.exists() for e in entries)


def test_unparseable_entry_is_never_deleted(tmp_path: Path) -> None:
    side = _side_dir(tmp_path)
    mystery = side / "CLAUDE.md.not-a-timestamp"
    mystery.write_text("keep me", encoding="utf-8")
    # plus a clearly-expired, parseable one to prove GC still runs.
    expired = _write_entry(side, age_days=RETAIN_DAYS + 1)

    report = prune_archive(tmp_path, now=_NOW)

    assert mystery.exists()
    assert report.unparseable == 1
    assert not expired.exists()


def test_dry_run_reports_without_deleting(tmp_path: Path) -> None:
    side = _side_dir(tmp_path)
    entries = [_write_entry(side, age_days=RETAIN_DAYS + 5, ordinal=i) for i in range(3)]

    report = prune_archive(tmp_path, now=_NOW, dry_run=True)

    assert report.deleted == 3
    assert all(e.exists() for e in entries)  # nothing actually removed


def test_missing_archive_dir_is_a_noop(tmp_path: Path) -> None:
    report = prune_archive(tmp_path, now=_NOW)
    assert report.scanned == 0
    assert report.deleted == 0
