"""Unit tests for the artifact archive gateway (rebuild S16, NFR-01/NFR-07, US-05).

Archive-before-write primitives (copy / move / text snapshot under
``archive/<artifact_id>/<side>/<name>.<ISO-timestamp>``) and the tiered, age-based
GC that bounds archive growth: keep-all within 7 days, newest 4 per UTC day to
30 days, newest 1 per day to 365, delete beyond — and never delete an entry whose
timestamp it cannot parse (fail-safe). Real filesystem via tmp_path; time is
injected (``now=``), never read from the clock in tests.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from agents_sync.artifact_archive import (
    GcReport,
    archive_copy,
    archive_move,
    archive_text,
    prune_archive,
)
from agents_sync.domain_model.artifact_identity import InvalidArtifactId

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
_NOW = dt.datetime(2026, 6, 12, 12, 0, 0, tzinfo=dt.UTC)


def _archive_side_dir(state_dir: Path, side: str = "claude") -> Path:
    return state_dir / "archive" / _ARTIFACT_ID / side


def _entry_at(state_dir: Path, age_days: int, *, index: int = 0, side: str = "claude") -> Path:
    # An archive entry whose name encodes a timestamp `age_days` before _NOW;
    # `index` spreads same-day entries across distinct minutes (newest = index 0).
    moment = _NOW - dt.timedelta(days=age_days, minutes=index)
    stamp = moment.strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    side_dir = _archive_side_dir(state_dir, side)
    side_dir.mkdir(parents=True, exist_ok=True)
    entry = side_dir / f"agent.md.{stamp}"
    entry.write_text(f"aged {age_days}d #{index}")
    return entry


# --- archive-before-write primitives (NFR-01) ---------------------------------------


def test_archive_copy_preserves_bytes_and_leaves_the_original(tmp_path: Path) -> None:
    source = tmp_path / "agent.md"
    source.write_text("user-authored")

    target = archive_copy(tmp_path, _ARTIFACT_ID, "claude", source)

    assert target.read_text() == "user-authored"
    assert source.read_text() == "user-authored"
    assert target.parent == _archive_side_dir(tmp_path)


def test_archive_copy_snapshots_a_directory_tree(tmp_path: Path) -> None:
    source = tmp_path / "skill"
    (source / "sub").mkdir(parents=True)
    (source / "SKILL.md").write_text("body")
    (source / "sub" / "helper.py").write_text("x = 1")

    target = archive_copy(tmp_path, _ARTIFACT_ID, "claude", source)

    assert (target / "SKILL.md").read_text() == "body"
    assert (target / "sub" / "helper.py").read_text() == "x = 1"
    assert source.is_dir()  # original remains


def test_archive_move_preserves_bytes_and_removes_the_original(tmp_path: Path) -> None:
    source = tmp_path / "agent.md"
    source.write_text("conflict loser")

    target = archive_move(tmp_path, _ARTIFACT_ID, "claude", source)

    assert target.read_text() == "conflict loser"
    assert not source.exists()


def test_a_retried_directory_move_uses_a_fresh_target_per_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # shutil.move into an existing directory NESTS instead of replacing, so a retry
    # aimed at a partial prior attempt would silently malform the entry — each
    # attempt must target a fresh unique path.
    import shutil as shutil_module

    from agents_sync import atomic_file_writer

    monkeypatch.setattr(atomic_file_writer.time, "sleep", lambda _s: None)
    source = tmp_path / "skill"
    source.mkdir()
    (source / "SKILL.md").write_text("body")
    real_move = shutil_module.move
    attempted_targets: list[str] = []
    failures = {"remaining": 1}

    def flaky_move(src: str, dst: str) -> object:
        attempted_targets.append(dst)
        if failures["remaining"] > 0:
            failures["remaining"] -= 1
            raise PermissionError("transient hold")
        return real_move(src, dst)

    monkeypatch.setattr(shutil_module, "move", flaky_move)
    target = archive_move(tmp_path, _ARTIFACT_ID, "claude", source)

    assert (target / "SKILL.md").read_text() == "body"
    assert len(attempted_targets) == 2
    assert attempted_targets[0] != attempted_targets[1]  # fresh target per attempt


def test_archive_text_snapshots_a_slot_payload(tmp_path: Path) -> None:
    target = archive_text(tmp_path, _ARTIFACT_ID, "cursor", "github", ".json", '{"a": 1}')

    assert target.read_text() == '{"a": 1}'
    assert target.name.startswith("github.json.")
    assert target.parent == _archive_side_dir(tmp_path, "cursor")


def test_a_hostile_slot_name_cannot_escape_the_archive_directory(tmp_path: Path) -> None:
    # Slot names come from raw user-supplied map keys; a traversal-shaped key must
    # land inside the per-artifact directory, slugified.
    target = archive_text(tmp_path, _ARTIFACT_ID, "cursor", "../../../tmp/pwned", ".json", "{}")

    assert target.resolve().is_relative_to(_archive_side_dir(tmp_path, "cursor").resolve())


def test_a_hostile_extension_cannot_escape_the_archive_directory(tmp_path: Path) -> None:
    # The extension parameter bypasses slugification; a traversal-shaped extension
    # must be refused by the containment check, anchored to the side directory.
    with pytest.raises(ValueError):
        archive_text(tmp_path, _ARTIFACT_ID, "cursor", "github", "/../../pwned", "{}")


def test_an_invalid_artifact_id_is_a_recipe_error(tmp_path: Path) -> None:
    source = tmp_path / "agent.md"
    source.write_text("x")

    with pytest.raises(InvalidArtifactId):
        archive_copy(tmp_path, "not-a-uuid", "claude", source)


def test_two_archives_of_the_same_source_produce_two_entries(tmp_path: Path) -> None:
    source = tmp_path / "agent.md"
    source.write_text("v1")
    first = archive_copy(tmp_path, _ARTIFACT_ID, "claude", source)
    source.write_text("v2")

    second = archive_copy(tmp_path, _ARTIFACT_ID, "claude", source)

    assert first != second
    assert {first.read_text(), second.read_text()} == {"v1", "v2"}


# --- tiered GC (NFR-07): tier boundaries and fail-safety ---------------------------


def test_entries_younger_than_the_keep_all_tier_are_all_kept(tmp_path: Path) -> None:
    for index in range(6):
        _entry_at(tmp_path, age_days=3, index=index)

    report = prune_archive(tmp_path, now=_NOW)

    assert report.deleted == 0
    assert report.kept == 6


def test_the_downsample_tier_keeps_the_newest_four_per_day(tmp_path: Path) -> None:
    entries = [_entry_at(tmp_path, age_days=10, index=index) for index in range(6)]

    report = prune_archive(tmp_path, now=_NOW)

    assert report.deleted == 2
    survivors = sorted(p.name for p in _archive_side_dir(tmp_path).iterdir())
    assert sorted(e.name for e in entries[:4]) == survivors  # newest four (index 0..3)
    # the report's arithmetic is part of the contract, not decoration:
    assert report.scanned == 6
    assert report.kept == 4
    assert sorted(report.deleted_paths) == sorted(entries[4:])


def test_the_caps_apply_per_side_not_pooled(tmp_path: Path) -> None:
    # Three same-day downsample-tier entries on EACH of two sides: per-side the
    # 4-per-day cap keeps all of them; a pooled pass would see six and delete two.
    for index in range(3):
        _entry_at(tmp_path, age_days=10, index=index, side="claude")
        _entry_at(tmp_path, age_days=10, index=index, side="cursor")

    report = prune_archive(tmp_path, now=_NOW)

    assert report.deleted == 0
    assert report.kept == 6


def test_the_old_tier_keeps_the_newest_one_per_day(tmp_path: Path) -> None:
    entries = [_entry_at(tmp_path, age_days=100, index=index) for index in range(3)]

    report = prune_archive(tmp_path, now=_NOW)

    assert report.deleted == 2
    [survivor] = _archive_side_dir(tmp_path).iterdir()
    assert survivor.name == entries[0].name  # the newest


def test_entries_beyond_retention_are_deleted(tmp_path: Path) -> None:
    _entry_at(tmp_path, age_days=400)

    report = prune_archive(tmp_path, now=_NOW)

    assert report.deleted == 1
    assert list(_archive_side_dir(tmp_path).iterdir()) == []


def test_an_entry_exactly_at_the_keep_all_boundary_is_downsampled(tmp_path: Path) -> None:
    # Five entries exactly 7 days old: keep-all would keep all five, the downsample
    # tier keeps only the newest four — the boundary entry lands in the OLDER tier.
    [_entry_at(tmp_path, age_days=7, index=index) for index in range(5)]

    report = prune_archive(tmp_path, now=_NOW)

    assert report.deleted == 1
    assert report.kept == 4


def test_an_entry_exactly_at_the_downsample_boundary_is_in_the_old_tier(tmp_path: Path) -> None:
    # Two entries exactly 30 days old: the downsample tier would keep both (4/day),
    # the old tier keeps only the newest one.
    [_entry_at(tmp_path, age_days=30, index=index) for index in range(2)]

    report = prune_archive(tmp_path, now=_NOW)

    assert report.deleted == 1
    assert report.kept == 1


def test_an_entry_exactly_at_the_retention_boundary_is_deleted(tmp_path: Path) -> None:
    boundary_365 = _entry_at(tmp_path, age_days=365)

    report = prune_archive(tmp_path, now=_NOW)

    assert report.deleted == 1
    assert not boundary_365.exists()


def test_an_unparseable_entry_name_is_never_deleted(tmp_path: Path) -> None:
    # Fail-safe: GC must never destroy data it does not understand, however old.
    side_dir = _archive_side_dir(tmp_path)
    side_dir.mkdir(parents=True)
    mystery = side_dir / "agent.md.not-a-timestamp"
    mystery.write_text("precious")

    report = prune_archive(tmp_path, now=_NOW)

    assert mystery.read_text() == "precious"
    assert report.unparseable == 1
    assert report.deleted == 0


def test_a_deleted_directory_entry_is_removed_recursively_and_sized(tmp_path: Path) -> None:
    stamp = (_NOW - dt.timedelta(days=400)).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    side_dir = _archive_side_dir(tmp_path)
    entry = side_dir / f"skill.{stamp}"
    (entry / "sub").mkdir(parents=True)
    (entry / "sub" / "data.bin").write_bytes(b"x" * 64)

    report = prune_archive(tmp_path, now=_NOW)

    assert not entry.exists()
    assert report.deleted == 1
    assert report.bytes_reclaimed == 64


def test_pruning_a_missing_archive_root_reports_nothing(tmp_path: Path) -> None:
    assert prune_archive(tmp_path, now=_NOW) == GcReport()


def test_a_real_archive_entry_is_parseable_by_the_gc(tmp_path: Path) -> None:
    # Writer-to-parser round-trip: a drift in the writer's timestamp format alone
    # would make every real entry unparseable — GC silently neutered forever.
    source = tmp_path / "agent.md"
    source.write_text("x")
    archive_copy(tmp_path, _ARTIFACT_ID, "claude", source)

    report = prune_archive(tmp_path)  # real clock: the fresh entry is in keep-all

    assert report.scanned == 1
    assert report.unparseable == 0
    assert report.kept == 1
