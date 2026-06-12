"""Unit tests for the atomic file writer gateway (rebuild S14, NFR-03).

The gateway owns crash-consistent filesystem writes: external readers see either
the prior or the new artifact, never an intermediate state — for single files
(temp + fsync + replace) and folders (staged copy + rename-with-rollback). The
real filesystem (tmp_path) is the boundary under test; fault injection patches
the os layer only.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from agents_sync import atomic_file_writer
from agents_sync.atomic_file_writer import (
    move_file_atomic,
    replace_directory_atomic,
    write_text_atomic,
)


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    # The transient-retry backoff is real time at the boundary; tests must not wait it out.
    monkeypatch.setattr(atomic_file_writer.time, "sleep", lambda _seconds: None)


# --- write_text_atomic ----------------------------------------------------------


def test_written_content_reads_back_verbatim(tmp_path: Path) -> None:
    target = tmp_path / "artifact.md"

    write_text_atomic(target, "naïve — ünïcode\n")

    assert target.read_text(encoding="utf-8") == "naïve — ünïcode\n"


def test_missing_parent_directories_are_created(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "artifact.md"

    write_text_atomic(target, "x")

    assert target.read_text(encoding="utf-8") == "x"


def test_prior_content_is_overwritten(tmp_path: Path) -> None:
    target = tmp_path / "artifact.md"
    target.write_text("old")

    write_text_atomic(target, "new")

    assert target.read_text(encoding="utf-8") == "new"


def test_no_staging_file_is_left_after_success(tmp_path: Path) -> None:
    write_text_atomic(tmp_path / "artifact.md", "x")

    assert [p.name for p in tmp_path.iterdir()] == ["artifact.md"]


def test_a_failed_replace_keeps_the_prior_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # NFR-03: the rename is the commit point — if it never lands, the reader still
    # sees the prior artifact, and the staging file is cleaned up.
    target = tmp_path / "artifact.md"
    target.write_text("prior")

    def failing_replace(src: Any, dst: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError):
        write_text_atomic(target, "new")

    assert target.read_text(encoding="utf-8") == "prior"
    assert [p.name for p in tmp_path.iterdir()] == ["artifact.md"]


def test_transient_errors_are_retried_until_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "artifact.md"
    real_replace = os.replace
    failures = {"remaining": 2}

    def flaky_replace(src: Any, dst: Any) -> None:
        if failures["remaining"] > 0:
            failures["remaining"] -= 1
            raise PermissionError("transient sharing violation")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    write_text_atomic(target, "x")

    assert target.read_text(encoding="utf-8") == "x"
    assert failures["remaining"] == 0


def test_a_persistent_transient_error_is_raised_after_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = {"count": 0}

    def always_locked(src: Any, dst: Any) -> None:
        attempts["count"] += 1
        raise PermissionError("still locked")

    monkeypatch.setattr(os, "replace", always_locked)
    with pytest.raises(PermissionError):
        write_text_atomic(tmp_path / "artifact.md", "x")

    # the full contracted retry budget is spent before giving up
    assert attempts["count"] == atomic_file_writer._RETRY_ATTEMPTS


def test_a_windows_transient_winerror_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The Windows sharing-violation classification must hold on any platform: a
    # synthetic OSError carrying winerror 32 is transient and retried to success.
    target = tmp_path / "artifact.md"
    real_replace = os.replace
    failures = {"remaining": 1}

    def sharing_violation(src: Any, dst: Any) -> None:
        if failures["remaining"] > 0:
            failures["remaining"] -= 1
            error = OSError("sharing violation")
            error.winerror = 32  # type: ignore[attr-defined]
            raise error
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", sharing_violation)
    write_text_atomic(target, "x")

    assert target.read_text(encoding="utf-8") == "x"
    assert failures["remaining"] == 0


def test_a_failed_write_cleans_up_the_staging_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ENOSPC-style failure before the commit point: prior content intact AND no
    # unreclaimable .tmp litter left behind (each attempt mints a unique suffix,
    # so nothing else would ever clean it).
    target = tmp_path / "artifact.md"
    target.write_text("prior")

    def disk_full(descriptor: int, payload: bytes) -> int:
        raise OSError("no space left on device")

    monkeypatch.setattr(os, "write", disk_full)
    with pytest.raises(OSError):
        write_text_atomic(target, "new")

    assert target.read_text(encoding="utf-8") == "prior"
    assert [p.name for p in tmp_path.iterdir()] == ["artifact.md"]


def test_a_partial_write_never_commits_a_truncated_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ENOSPC's non-raising mode: os.write accepts only part of the payload and
    # returns a short count. Committing the truncated staging file would expose
    # exactly the intermediate state NFR-03 forbids — it must fail loud instead.
    target = tmp_path / "artifact.md"
    target.write_text("prior")
    real_write = os.write

    def short_write(descriptor: int, payload: bytes) -> int:
        real_write(descriptor, payload[:1])
        return 1

    monkeypatch.setattr(os, "write", short_write)
    with pytest.raises(OSError):
        write_text_atomic(target, "new")

    assert target.read_text(encoding="utf-8") == "prior"
    assert [p.name for p in tmp_path.iterdir()] == ["artifact.md"]


def test_the_file_and_its_directory_are_fsynced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Durability is the unobservable half of NFR-03: the staging fd is fsynced
    # before the rename and the parent directory after it, or a crash could lose
    # the committed artifact. A boundary spy is the only way to pin it.
    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(descriptor: int) -> None:
        fsync_calls.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    write_text_atomic(tmp_path / "artifact.md", "x")

    assert len(fsync_calls) == 2  # the staging file, then the parent directory


def test_a_non_transient_error_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = {"count": 0}

    def broken_replace(src: Any, dst: Any) -> None:
        attempts["count"] += 1
        raise OSError("not a transient class")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError):
        write_text_atomic(tmp_path / "artifact.md", "x")

    assert attempts["count"] == 1


# --- move_file_atomic -----------------------------------------------------------


def test_move_file_atomic_moves_and_creates_parents(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.json"
    source.write_text("bytes to preserve")
    destination = tmp_path / "quarantine" / "corrupt.json.1.corrupt"

    move_file_atomic(source, destination)

    assert destination.read_text() == "bytes to preserve"
    assert not source.exists()


def test_move_file_atomic_retries_transient_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "a.txt"
    source.write_text("x")
    destination = tmp_path / "b.txt"
    real_replace = os.replace
    failures = {"remaining": 1}

    def flaky_replace(src: Any, dst: Any) -> None:
        if failures["remaining"] > 0:
            failures["remaining"] -= 1
            raise PermissionError("transient")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    move_file_atomic(source, destination)

    assert destination.read_text() == "x"
    assert failures["remaining"] == 0


# --- replace_directory_atomic ---------------------------------------------------


def _populate_with(files: dict[str, str]) -> Any:
    def populate(staging: Path) -> None:
        for name, content in files.items():
            (staging / name).write_text(content)

    return populate


def test_a_fresh_directory_is_created_from_the_populate_callback(tmp_path: Path) -> None:
    target = tmp_path / "skill"

    replace_directory_atomic(target, _populate_with({"SKILL.md": "body"}))

    assert (target / "SKILL.md").read_text() == "body"


def test_a_prior_directory_is_replaced_wholesale(tmp_path: Path) -> None:
    # The swap is all-or-nothing: stale members of the prior directory do not survive.
    target = tmp_path / "skill"
    target.mkdir()
    (target / "stale.md").write_text("stale")

    replace_directory_atomic(target, _populate_with({"SKILL.md": "new"}))

    assert (target / "SKILL.md").read_text() == "new"
    assert not (target / "stale.md").exists()
    assert [p.name for p in tmp_path.iterdir()] == ["skill"]  # no .tmp/.old litter


def test_a_failing_populate_leaves_the_prior_directory_untouched(tmp_path: Path) -> None:
    target = tmp_path / "skill"
    target.mkdir()
    (target / "SKILL.md").write_text("prior")

    def failing_populate(staging: Path) -> None:
        raise OSError("populate exploded")

    with pytest.raises(OSError):
        replace_directory_atomic(target, failing_populate)

    assert (target / "SKILL.md").read_text() == "prior"
    assert [p.name for p in tmp_path.iterdir()] == ["skill"]


def test_a_failed_swap_rolls_the_prior_directory_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the staging dir cannot land on the target, the prior directory (already moved
    # aside) is restored — the reader never observes a missing artifact.
    target = tmp_path / "skill"
    target.mkdir()
    (target / "SKILL.md").write_text("prior")
    real_rename = os.rename

    def failing_final_rename(src: Any, dst: Any) -> None:
        if Path(str(dst)) == target and Path(str(src)).name.endswith(".tmp"):
            raise OSError("target dir busy")
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", failing_final_rename)
    with pytest.raises(OSError):
        replace_directory_atomic(target, _populate_with({"SKILL.md": "new"}))

    assert (target / "SKILL.md").read_text() == "prior"


def test_stale_staging_siblings_from_a_crashed_run_are_cleared(tmp_path: Path) -> None:
    target = tmp_path / "skill"
    stale_tmp = tmp_path / ".skill.tmp"
    stale_old = tmp_path / ".skill.old"
    stale_tmp.mkdir()
    (stale_tmp / "leftover").write_text("x")
    stale_old.mkdir()

    replace_directory_atomic(target, _populate_with({"SKILL.md": "new"}))

    assert (target / "SKILL.md").read_text() == "new"
    assert not stale_tmp.exists()
    assert not stale_old.exists()
