"""Amendment 004 — data-safety fixes from the v0.6 safety audit.

C  — import archives a displaced local canonical before overwriting it, so the
     stub-overwrite case (no tool files to recover from) does not lose the prior
     bytes (NFR-01 archive-before-write; US-12 AC-17 loser archived).
#6 — a corrupt state.json that cannot be moved aside fails closed
     (StateQuarantineError) instead of being silently overwritten (NFR-01/FR-11).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from agents_sync.archive import archive_dir_for
from agents_sync.portable_archive import import_from_zip
from agents_sync.state import StateQuarantineError, load_state, state_path

from ._helpers import make_syncer

pytestmark = pytest.mark.integration


def _canonical(pair_id: str, name: str, body: str, last_modified: float) -> dict:
    return {
        "pair_id": pair_id,
        "kind": "skill",
        "name": name,
        "description": "d",
        "body": body,
        "per_agentic_tool_only": {},
        "per_agentic_tool_extra": {},
        "last_modified": last_modified,
        "generation": 1,
    }


def _build_zip(path: Path, canonicals: list[dict]) -> Path:
    out = path.parent / (path.stem + "_build")
    (out / "canonical").mkdir(parents=True, exist_ok=True)
    for c in canonicals:
        (out / "canonical" / f"{c['pair_id']}.json").write_text(json.dumps(c, sort_keys=True))
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "agents_sync_version": "0.5.6",
                "artifact_count": len(canonicals),
                "contains_secret_literals": False,
                "exported_at": "2026-05-31T00:00:00+00:00",
                "schema_version": 1,
                "source_host": "other",
                "source_platform": "Linux",
            }
        )
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.write(out / "manifest.json", "manifest.json")
        for c in canonicals:
            zf.write(out / "canonical" / f"{c['pair_id']}.json", f"canonical/{c['pair_id']}.json")
    return path


def _import(syncer, zip_path: Path):
    return import_from_zip(
        syncer.state_dir,
        zip_path,
        strategy="mtime_wins",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )


I1 = "11111111-2222-4333-8444-555555555551"
I2 = "11111111-2222-4333-8444-555555555552"


def test_import_archives_displaced_stub_canonical_before_overwrite(tmp_path: Path) -> None:
    """C: a never-projected stub overwritten by a winning import keeps its prior
    bytes under archive/<id>/_canonical/ (no tool files exist to recover from)."""
    syncer = make_syncer(tmp_path)

    # Import 1: a stub canonical (never projected — no sync_once).
    _import(syncer, _build_zip(tmp_path / "lib1.zip", [_canonical(I1, "demo", "old-body", 100.0)]))
    assert (syncer.state_dir / "canonical" / f"{I1}.json").exists()

    # Import 2: same (kind, name), newer — reconciles to the local id I1 and
    # overwrites canonical/I1.json. The displaced "old-body" must be archived.
    _import(syncer, _build_zip(tmp_path / "lib2.zip", [_canonical(I2, "demo", "new-body", 200.0)]))

    archived = list(archive_dir_for(syncer.state_dir, I1, "_canonical").glob("*.json.*"))
    assert archived, "displaced stub canonical was not archived before overwrite"
    assert "old-body" in archived[0].read_text()
    # And the live canonical now holds the winning content.
    assert "new-body" in (syncer.state_dir / "canonical" / f"{I1}.json").read_text()


def test_corrupt_state_that_cannot_be_quarantined_fails_closed(tmp_path: Path) -> None:
    """#6: when the quarantine move cannot happen, load_state raises rather than
    returning {} (which would let the next save_state overwrite the corrupt bytes)."""
    corrupt = "this is not json {"
    state_path(tmp_path).write_text(corrupt)
    # Block the quarantine move: a regular file where the quarantine DIR must go
    # makes mkdir(exist_ok=True) raise OSError at the real filesystem boundary.
    (tmp_path / "quarantine").write_text("occupied")

    with pytest.raises(StateQuarantineError):
        load_state(tmp_path)

    # The corrupt bytes are preserved, not clobbered.
    assert state_path(tmp_path).read_text() == corrupt
