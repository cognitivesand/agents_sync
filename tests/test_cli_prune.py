"""`agents-sync prune` CLI: tiered archive GC from the command line (NFR-07)."""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from agents_sync.cli import main

_TS_FORMAT = "%Y-%m-%dT%H-%M-%S-%fZ"
_PAIR = "11111111-1111-4111-8111-111111111111"


def _expired_entry(state_dir: Path) -> Path:
    side = state_dir / "archive" / _PAIR / "claude"
    side.mkdir(parents=True, exist_ok=True)
    old = _dt.datetime.now(tz=_dt.UTC) - _dt.timedelta(days=500)
    entry = side / f"CLAUDE.md.{old.strftime(_TS_FORMAT)}"
    entry.write_text("old snapshot", encoding="utf-8")
    return entry


def test_prune_deletes_expired_entries(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "state.json"
    (tmp_path / "state").mkdir(parents=True)
    entry = _expired_entry(tmp_path / "state")

    code = main(["--state-path", str(state_path), "prune"])

    assert code == 0
    assert not entry.exists()


def test_prune_dry_run_keeps_entries(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "state.json"
    (tmp_path / "state").mkdir(parents=True)
    entry = _expired_entry(tmp_path / "state")

    code = main(["--state-path", str(state_path), "prune", "--dry-run"])

    assert code == 0
    assert entry.exists()
