"""Archive utilities backing the data-preservation invariant (NFR-01).

Anything that would overwrite or remove user-authored content first
preserves the prior bytes at:
  <state_dir>/archive/<pair_id>/<side>/<filename>.<ISO-timestamp>

Two flavours:
  - `archive_copy`: snapshots the source; original remains in place.
    Used during adoption ("preserve a copy before we inject pair_id").
  - `archive_move`: moves the source into the archive; original is gone.
    Used during conflict-loser overwrite and symmetric delete.
"""
from __future__ import annotations

import datetime as _dt
import shutil
from pathlib import Path

from agents_sync.filesystem_windows_retry import retry_fs
from agents_sync.identity import validate_pair_id
from agents_sync.state import ignored_tree_names


def iso_timestamp(now: _dt.datetime | None = None) -> str:
    """ISO 8601 UTC timestamp with `:` replaced by `-` for filesystem use.

    Microsecond precision prevents collisions when several archive entries
    are written back-to-back for the same (pair_id, side) — e.g. an
    adoption that archives pre-injection bytes followed immediately by a
    conflict-loser archive in the same second.
    """
    moment = now or _dt.datetime.now(tz=_dt.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H-%M-%S-%fZ")


def archive_dir_for(state_dir: Path, pair_id: str, side: str) -> Path:
    validate_pair_id(pair_id)
    return state_dir / "archive" / pair_id / side


def _archive_target(state_dir: Path, pair_id: str, side: str, source: Path) -> Path:
    target_dir = archive_dir_for(state_dir, pair_id, side)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{source.name}.{iso_timestamp()}"


def archive_copy(state_dir: Path, pair_id: str, side: str, source: Path) -> Path:
    """Copy `source` into the per-pair archive; original remains in place."""
    target = _archive_target(state_dir, pair_id, side, source)
    if source.is_dir():
        shutil.copytree(source, target, ignore=lambda _dir, names: ignored_tree_names(names))
    else:
        shutil.copy2(source, target)
    return target


def archive_move(state_dir: Path, pair_id: str, side: str, source: Path) -> Path:
    """Move `source` into the per-pair archive; original is gone afterwards.

    Used when the data-preservation rule mandates moving instead of deleting:
    conflict losers being overwritten, and symmetric delete propagation.
    """
    target = _archive_target(state_dir, pair_id, side, source)
    retry_fs(
        lambda: shutil.move(str(source), str(target)),
        operation=f"archive_move {source} -> {target}",
    )
    return target


# Back-compat alias used by callers written for Phase 2.
archive_file = archive_copy
