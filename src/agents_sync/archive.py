"""Archive utilities backing the data-preservation invariant (NFR-01).

Anything that would overwrite or remove user-authored content first
copies the prior bytes to:
  <state_dir>/archive/<pair_id>/<side>/<filename>.<ISO-timestamp>

Routine retranslations whose prior content equals a render of the
current canonical are exempt — see NFR-07 (bounded archive growth).
"""
from __future__ import annotations

import datetime as _dt
import shutil
from pathlib import Path


def iso_timestamp(now: _dt.datetime | None = None) -> str:
    """ISO 8601 UTC timestamp with `:` replaced by `-` for filesystem use."""
    moment = now or _dt.datetime.now(tz=_dt.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H-%M-%SZ")


def archive_dir_for(state_dir: Path, pair_id: str, side: str) -> Path:
    return state_dir / "archive" / pair_id / side


def archive_file(state_dir: Path, pair_id: str, side: str, source: Path) -> Path:
    """Copy `source` (file or directory) into the per-pair archive.

    Returns the archive path. Raises if the archive write fails; callers
    MUST then abort the destructive operation that triggered the archive.
    """
    target_dir = archive_dir_for(state_dir, pair_id, side)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{source.name}.{iso_timestamp()}"
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)
    return target
