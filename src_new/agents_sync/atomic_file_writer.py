"""Atomic file writer — the gateway for crash-consistent filesystem writes (NFR-03).

External readers see either the prior or the new artifact, never an intermediate
state. Single files commit via temp + fsync + ``os.replace`` (+ parent-directory
fsync so the rename survives a crash) — fully atomic. Folders commit via a staged
copy renamed onto the target with the prior directory moved aside and restored on
failure: directories have no portable exchange primitive, so the swap has a bounded
transient window in which the target is absent; the rollback guarantees the gap is
never permanent, and recompute-from-disk heals a crash inside it.
Transient OS errors (Windows sharing/lock violations, PermissionError) are retried
with exponential backoff — there is no on-disk lock: concurrency is handled by
atomic writes + recompute-from-disk, not locking (proposal §13).
"""

from __future__ import annotations

import os
import random
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path

_RETRY_ATTEMPTS = 6
_RETRY_BASE_DELAY_SECONDS = 0.02
_RETRY_MAX_DELAY_SECONDS = 0.30
# Windows errnos that signal a transient hold by another process (antivirus,
# indexer, a reader mid-open) rather than a real failure.
_WINDOWS_TRANSIENT_WINERRORS = frozenset({5, 32, 33})  # access-denied, sharing, lock


def write_text_atomic(target_file: Path, content: str) -> None:
    """Write ``content`` to ``target_file`` atomically and crash-consistently.

    The unique temp suffix (pid + random) keeps two concurrent writers from
    clobbering each other's staging file; the rename is the commit point, so a
    failure anywhere leaves the prior content in place.
    """
    target_file.parent.mkdir(parents=True, exist_ok=True)
    staging_file = target_file.with_name(
        f".{target_file.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    )
    payload = content.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(staging_file, flags, 0o644)
        try:
            written_count = os.write(descriptor, payload)
            if written_count != len(payload):
                # write(2) may accept a partial payload without raising (ENOSPC
                # mid-write); committing it would expose a truncated artifact.
                raise OSError(
                    f"short write: {written_count} of {len(payload)} bytes to {staging_file}"
                )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _retry_transient(lambda: os.replace(staging_file, target_file))
    except Exception:
        # The commit never landed — the prior content is intact; drop the staging
        # file (each attempt mints a unique suffix, so nothing else reclaims it).
        staging_file.unlink(missing_ok=True)
        raise
    _fsync_directory(target_file.parent)


def move_file_atomic(source_file: Path, target_file: Path) -> None:
    """Move ``source_file`` onto ``target_file`` in one atomic rename (parents created).

    Used to put a file aside (e.g. quarantine a corrupt store file) without a copy
    window; a transient OS hold is retried, any other failure propagates loudly.
    Both parent directories are fsynced — otherwise a crash could durably persist
    the source entry's removal while losing the target entry.
    """
    target_file.parent.mkdir(parents=True, exist_ok=True)
    _retry_transient(lambda: os.replace(source_file, target_file))
    _fsync_directory(target_file.parent)
    _fsync_directory(source_file.parent)


def replace_directory_atomic(target_dir: Path, populate: Callable[[Path], None]) -> None:
    """Replace ``target_dir`` wholesale with a directory built by ``populate``.

    ``populate`` receives a fresh staging directory next to the target; once it
    returns, the staging dir is renamed onto the target with the prior directory
    moved aside and restored if the swap fails. Stale ``.tmp``/``.old`` siblings
    from a crashed earlier run are cleared first.
    """
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = target_dir.with_name(f".{target_dir.name}.tmp")
    backup_dir = target_dir.with_name(f".{target_dir.name}.old")
    _clear_stale_directories(staging_dir, backup_dir)
    staging_dir.mkdir()
    try:
        populate(staging_dir)
    except Exception:
        # The target was never touched; drop the half-built staging dir.
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    _rename_with_rollback(staging_dir, target_dir, backup_dir)


def _clear_stale_directories(*directories: Path) -> None:
    for directory in directories:
        if directory.exists():
            _retry_transient(
                lambda d=directory: shutil.rmtree(d),  # type: ignore[misc]
            )


def _rename_with_rollback(staging_dir: Path, target_dir: Path, backup_dir: Path) -> None:
    """Rename ``staging_dir`` onto ``target_dir``; a prior target is moved aside to
    ``backup_dir`` first and restored if the swap fails.

    The two renames leave a bounded transient window with no target (directories
    have no exchange primitive); the rollback guarantees the gap is never permanent."""
    target_existed = target_dir.exists()
    if target_existed:
        _retry_transient(lambda: os.rename(target_dir, backup_dir))
    try:
        _retry_transient(lambda: os.rename(staging_dir, target_dir))
    except Exception:
        if target_existed:
            _retry_transient(lambda: os.rename(backup_dir, target_dir))
        raise
    if target_existed:
        _retry_transient(lambda: shutil.rmtree(backup_dir))


def _retry_transient[ResultT](operation_call: Callable[[], ResultT]) -> ResultT:
    """Run ``operation_call``, retrying transient OS errors with jittered backoff.

    A non-transient error re-raises immediately; the final attempt's error
    propagates as-is (it carries the offending path) — the caller's failure path
    owns the cleanup."""
    for attempt in range(1, _RETRY_ATTEMPTS):
        try:
            return operation_call()
        except Exception as error:
            if not _is_transient_error(error):
                raise
            delay = min(_RETRY_MAX_DELAY_SECONDS, _RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1))
            time.sleep(delay * random.uniform(0.7, 1.3))
    return operation_call()


def _is_transient_error(error: BaseException) -> bool:
    if not isinstance(error, OSError):
        return False
    if isinstance(error, PermissionError):
        return True
    return getattr(error, "winerror", None) in _WINDOWS_TRANSIENT_WINERRORS


def _fsync_directory(directory: Path) -> None:
    """Make a rename in ``directory`` durable; platforms without directory fds skip."""
    descriptor = None
    try:
        descriptor = os.open(directory, os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        # Windows cannot open directories; the rename is still atomic, just not
        # guaranteed durable past a power loss — the documented platform limit.
        pass
    finally:
        if descriptor is not None:
            os.close(descriptor)
