"""Store quarantine — move a corrupt store file aside, preserving its bytes (US-09 AC-4).

Shared by the canonical and sync-state stores: a file that fails to load is MOVED
into ``store_dir/quarantine/`` under a collision-proof name so the caller can
safely rebuild, while the corrupt bytes stay recoverable (separate from the
user-content archive). Fail-closed: if the move fails, the corrupt file is still
in place and a rebuild would overwrite it, so the load must raise, not proceed.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from agents_sync.atomic_file_writer import move_file_atomic


class QuarantineError(OSError):
    """A corrupt store file could not be moved to quarantine — fail closed."""


def quarantine_corrupt_file(store_dir: Path, source: Path, reason: str) -> None:
    """Move ``source`` into ``store_dir/quarantine/`` (bytes preserved); raise on failure.

    The destination name carries a monotonic-ns + random suffix: two quarantines of
    the same file never collide (a colliding name would silently overwrite the first
    preserved bytes).
    """
    unique_suffix = f"{time.monotonic_ns()}.{uuid.uuid4().hex[:8]}"
    destination = store_dir / "quarantine" / f"{source.name}.{unique_suffix}.corrupt"
    try:
        move_file_atomic(source, destination)
    except FileNotFoundError:
        # Overlapping-daemon race (US-09 AC-3): another instance already moved the
        # file — nothing is left at the source to protect, so converge, don't raise.
        return
    except OSError as error:
        raise QuarantineError(
            f"could not quarantine corrupt {source} ({reason}): {error}"
        ) from error
