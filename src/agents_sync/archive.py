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
from agents_sync.state import ignored_tree_names, slugify

_MAX_SLOT_COMPONENT_LEN = 128


def _safe_slot_component(slot_name: str) -> str:
    """Return a filesystem-safe form of ``slot_name`` for use as an archive
    filename component.

    Slot names are derived from raw user-supplied keys in MCP server maps
    (``mcpServers`` in ``.claude.json``, ``mcp_servers`` in
    ``~/.codex/config.toml``, ``mcp`` in ``opencode.json``). A malicious
    or accidental key like ``"../../../tmp/pwned"`` would otherwise
    escape ``<state_dir>/archive/<pair_id>/<side>/``. We slugify with the
    same rules as artifact names and cap the length; the original key
    remains untouched in ``canonical['name']``.
    """
    if not isinstance(slot_name, str):
        slot_name = str(slot_name)
    return slugify(slot_name)[:_MAX_SLOT_COMPONENT_LEN]


def iso_timestamp(now: _dt.datetime | None = None) -> str:
    """ISO 8601 UTC timestamp with `:` replaced by `-` for filesystem use.

    Microsecond precision prevents collisions when several archive entries
    are written back-to-back for the same (pair_id, side) — e.g. an
    adoption that archives pre-injection bytes followed immediately by a
    conflict-loser archive in the same second.
    """
    moment = now or _dt.datetime.now(tz=_dt.UTC)
    return moment.strftime("%Y-%m-%dT%H-%M-%S-%fZ")


def archive_dir_for(state_dir: Path, pair_id: str, side: str) -> Path:
    validate_pair_id(pair_id)
    return state_dir / "archive" / pair_id / side


def _archive_target(state_dir: Path, pair_id: str, side: str, source: Path) -> Path:
    """Compute the per-pair archive target path and ensure its parent exists.

    The ``mkdir(parents=True, exist_ok=True)`` is wrapped in ``retry_fs`` so a
    transient Windows ``ERROR_SHARING_VIOLATION`` from an antivirus scanner
    indexing the parent directory does not abort a data-preservation archive
    operation (audit slice 09 · CQ-08).
    """
    target_dir = archive_dir_for(state_dir, pair_id, side)
    retry_fs(
        lambda: target_dir.mkdir(parents=True, exist_ok=True),
        operation=f"mkdir {target_dir}",
    )
    return target_dir / f"{source.name}.{iso_timestamp()}"


def archive_copy(state_dir: Path, pair_id: str, side: str, source: Path) -> Path:
    """Copy `source` into the per-pair archive; original remains in place."""
    target = _archive_target(state_dir, pair_id, side, source)
    if source.is_dir():
        shutil.copytree(source, target, ignore=lambda _dir, names: ignored_tree_names(names))
    else:
        shutil.copy2(source, target)
    return target


def archive_text(
    state_dir: Path,
    pair_id: str,
    side: str,
    slot_name: str,
    extension: str,
    content: str,
) -> Path:
    """Archive a literal text payload (used for SharedKeyedMapLayout slots,
    where the prior bytes are an in-memory serialisation of one map entry,
    not a file on disk).

    Stored at ``archive/<pair_id>/<side>/<slot_name><extension>.<ts>`` so
    per-slot granularity matches the existing per-file convention.
    """
    validate_pair_id(pair_id)
    target_dir = archive_dir_for(state_dir, pair_id, side)
    retry_fs(
        lambda: target_dir.mkdir(parents=True, exist_ok=True),
        operation=f"mkdir {target_dir}",
    )
    safe_slot = _safe_slot_component(slot_name)
    target = target_dir / f"{safe_slot}{extension}.{iso_timestamp()}"
    resolved_target = target.resolve()
    resolved_dir = target_dir.resolve()
    if not resolved_target.is_relative_to(resolved_dir):
        raise ValueError(
            f"archive target {resolved_target} escapes per-pair directory "
            f"{resolved_dir} (slot_name={slot_name!r}); refusing to write."
        )
    target.write_text(content, encoding="utf-8")
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
