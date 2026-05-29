"""Cross-process file locking primitive.

Exposes one context manager:

    with lock_file(path):
        ...  # critical section

``path`` is the file being protected. A lock file is created next to it
(``<path>.lock``) and held exclusively for the duration of the ``with``
block. On POSIX this uses ``fcntl.flock`` (kernel-enforced advisory lock,
respected by every process that goes through this helper). On Windows it
uses ``msvcrt.locking`` in non-blocking mode with a bounded retry loop
(``msvcrt`` has no blocking mode; we sleep + retry until either the lock
is acquired or ``timeout_seconds`` elapses).

The lock is released by closing the file descriptor / handle on context
exit, which both kernels guarantee even on a crash of the holder.

This is the primitive that makes ``shared_keyed_map_io.apply_slot`` safe
against a concurrent writer in another process — the read-modify-write
sequence runs inside the lock, so two processes touching the same shared
file serialize instead of racing the ``os.replace`` after a re-read.
"""
from __future__ import annotations

import contextlib
import logging
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path

DEFAULT_LOCK_TIMEOUT_SECONDS = 5.0
_RETRY_INTERVAL_SECONDS = 0.05


class LockTimeoutError(RuntimeError):
    """Raised when a lock could not be acquired within the configured budget."""


@contextlib.contextmanager
def lock_file(
    path: Path,
    *,
    timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Hold an exclusive cross-process lock on ``path`` for the duration of
    the ``with`` block.

    The lock is taken on a sidecar file ``<path>.lock`` rather than on
    ``path`` itself so that the protected file's inode is free to be
    replaced via ``os.replace`` inside the critical section (the lock
    fd survives the swap; a lock held directly on ``path`` would not).
    """
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        with _windows_lock(lock_path, timeout_seconds=timeout_seconds):
            yield
    else:
        with _posix_lock(lock_path, timeout_seconds=timeout_seconds):
            yield


@contextlib.contextmanager
def _posix_lock(lock_path: Path, *, timeout_seconds: float) -> Iterator[None]:
    import fcntl

    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(
                        f"Could not acquire lock on {lock_path} within "
                        f"{timeout_seconds:.1f}s"
                    )
                time.sleep(_RETRY_INTERVAL_SECONDS)
        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                logging.exception("flock(LOCK_UN) failed for %s", lock_path)
    finally:
        os.close(fd)


@contextlib.contextmanager
def _windows_lock(lock_path: Path, *, timeout_seconds: float) -> Iterator[None]:
    import msvcrt

    # ``msvcrt.locking`` locks a region; we lock byte 0 of a 1-byte file.
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    # Make sure there is at least one byte to lock.
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
    except OSError:
        os.close(fd)
        raise

    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(
                        f"Could not acquire lock on {lock_path} within "
                        f"{timeout_seconds:.1f}s"
                    )
                time.sleep(_RETRY_INTERVAL_SECONDS)
        try:
            yield
        finally:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                logging.exception("msvcrt unlock failed for %s", lock_path)
    finally:
        os.close(fd)
