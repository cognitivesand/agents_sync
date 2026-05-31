"""US-12 AC-5/17/19 (P5): canonical-only import + cross-machine merge.

- import writes canonicals ONLY — neither state nor tool roots; the next sync_once
  adopts each orphan canonical (FR-16) and projects it (AC-5, revised by
  amendment 008 — single-writer state).
- two same-(kind,slug) canonicals with different ids reconcile to ONE managed
  pair, the newest winning (AC-17).
- importing onto a populated host where the import wins reuses the local id and
  the next sync_once re-projects the winning content (AC-17 tweak / AC-19).

FROZEN test contract for v0.6 P5 (revised by amendment 008) — do not edit without
user feedback.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agents_sync.portable_archive import import_from_zip
from agents_sync.state import load_state

from ._helpers import make_syncer, skill_md


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
                "agents_sync_version": "0.5.5",
                "artifact_count": len(canonicals),
                "contains_secret_literals": False,
                "exported_at": "2026-05-30T00:00:00+00:00",
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


I1 = "11111111-2222-4333-8444-555555555551"
I2 = "11111111-2222-4333-8444-555555555552"


def _import(syncer, zip_path: Path):
    return import_from_zip(
        syncer.state_dir,
        zip_path,
        strategy="mtime_wins",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )


def test_import_is_canonical_only_then_sync_once_projects(tmp_path: Path) -> None:
    syncer = make_syncer(tmp_path)
    zip_path = _build_zip(tmp_path / "lib.zip", [_canonical(I1, "demo", "body-A", 100.0)])

    _import(syncer, zip_path)

    # Canonical written; import writes NEITHER state nor tool files (AC-5,
    # amendment 008 — single-writer state). The daemon adopts the orphan canonical.
    assert (syncer.state_dir / "canonical" / f"{I1}.json").exists()
    assert I1 not in load_state(syncer.state_dir)
    assert not (syncer.tool_root("claude", "skill") / "demo" / "SKILL.md").exists()

    syncer.sync_once()  # the daemon adopts the orphan canonical (FR-16) and projects
    assert I1 in load_state(syncer.state_dir)
    assert (syncer.tool_root("claude", "skill") / "demo" / "SKILL.md").exists()
    assert (syncer.tool_root("codex", "skill") / "demo" / "SKILL.md").exists()
    assert syncer.sync_once().changed == 0  # NFR-05


def test_cross_identity_merge_keeps_one_pair_newest_wins(tmp_path: Path) -> None:
    syncer = make_syncer(tmp_path)
    # Same skill made on two machines: same name, different ids, I2 newer.
    zip_path = _build_zip(
        tmp_path / "lib.zip",
        [_canonical(I1, "demo", "older", 100.0), _canonical(I2, "demo", "newer", 200.0)],
    )

    _import(syncer, zip_path)
    syncer.sync_once()

    state = load_state(syncer.state_dir)
    assert len(state) == 1  # merged to one managed pair
    md = syncer.tool_root("claude", "skill") / "demo" / "SKILL.md"
    assert "newer" in md.read_text()
    assert syncer.sync_once().changed == 0  # idempotent


def test_import_onto_populated_host_reuses_local_id(tmp_path: Path) -> None:
    syncer = make_syncer(tmp_path)
    # Local "demo" already managed.
    d = syncer.tool_root("claude", "skill") / "demo"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(skill_md("demo", body="local-old"))
    syncer.sync_once()
    local_id = next(iter(load_state(syncer.state_dir)))
    # Make the local entry older so the import wins.
    from agents_sync.state import load_state as _ls
    from agents_sync.state import save_state

    st = _ls(syncer.state_dir)
    st[local_id].last_modified = 1.0
    save_state(syncer.state_dir, st)

    zip_path = _build_zip(tmp_path / "lib.zip", [_canonical(I1, "demo", "imported-new", 999.0)])
    _import(syncer, zip_path)
    syncer.sync_once()

    state = load_state(syncer.state_dir)
    assert local_id in state  # surviving id is the LOCAL id
    assert I1 not in state  # imported id retired
    assert "imported-new" in (syncer.tool_root("claude", "skill") / "demo" / "SKILL.md").read_text()
