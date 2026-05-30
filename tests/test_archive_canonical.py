"""US-05 AC-5 (P1): a dropped canonical record is archived (never rm'd) under the
reserved ``_canonical`` segment before it leaves the canonical store.

FROZEN test contract for v0.6 P1 — do not edit without user feedback.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agents_sync.archive import archive_canonical
from agents_sync.canonical import canonical_path, save_canonical
from agents_sync.state import load_state

from ._helpers import make_syncer, skill_md

PAIR_ID = "9923b30f-6250-4303-8647-4fe8ba75b487"


def _write_canonical(state_dir: Path, pair_id: str = PAIR_ID) -> Path:
    save_canonical(state_dir, pair_id, {"pair_id": pair_id, "kind": "skill", "name": "demo"})
    return canonical_path(state_dir, pair_id)


# ---- unit: the archive_canonical primitive ----


def test_archive_canonical_moves_to_reserved_segment(tmp_path: Path) -> None:
    src = _write_canonical(tmp_path)
    assert src.exists()

    archived = archive_canonical(tmp_path, PAIR_ID)

    assert archived is not None
    assert not src.exists()  # removed from the canonical store
    assert archived.parent == tmp_path / "archive" / PAIR_ID / "_canonical"
    assert json.loads(archived.read_text())["name"] == "demo"  # bytes preserved


def test_archive_canonical_segment_is_reserved_not_a_tool_name(tmp_path: Path) -> None:
    _write_canonical(tmp_path)
    archived = archive_canonical(tmp_path, PAIR_ID)
    assert archived is not None
    # The reserved `_canonical` segment (leading underscore) can never collide
    # with an agentic_tool name.
    assert archived.parent.name == "_canonical"


def test_archive_canonical_absent_is_noop(tmp_path: Path) -> None:
    assert archive_canonical(tmp_path, PAIR_ID) is None


# ---- integration: a full-pair removal archives the canonical ----

pytestmark = pytest.mark.integration


def test_full_pair_removal_archives_the_canonical(tmp_path: Path) -> None:
    syncer = make_syncer(tmp_path)
    skill_dir = syncer.tool_root("claude", "skill") / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(skill_md("demo"))
    syncer.sync_once()  # adopt + project to all tools

    pair_id = next(iter(load_state(syncer.state_dir)))
    canon = canonical_path(syncer.state_dir, pair_id)
    assert canon.exists()

    # Delete the only on-disk source (a single deliberate removal); the removal
    # propagates to every tool, the pair is fully dropped, and its canonical is
    # archived first.
    shutil.rmtree(skill_dir)
    syncer.sync_once()

    assert pair_id not in load_state(syncer.state_dir)
    assert not canon.exists()  # canonical no longer in the live store
    archived = list((syncer.state_dir / "archive" / pair_id / "_canonical").glob("*.json.*"))
    assert archived, "dropped canonical was not archived under _canonical"
