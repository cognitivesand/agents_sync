"""FR-14 (P4): the daemon detects a canonical that changed independently of its
tool-side files (e.g. an import) and re-projects it onto every tool, archiving
displaced bytes — making the canonical the behavioural source of truth.

FROZEN test contract for v0.6 P4 — do not edit without user feedback.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agents_sync.canonical import load_canonical, save_canonical
from agents_sync.state import load_state

from ._helpers import make_syncer, skill_md


def _adopt(syncer, name: str = "demo", body: str = "original") -> str:
    d = syncer.tool_root("claude", "skill") / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(skill_md(name, body=body))
    syncer.sync_once()  # adopt + project; canonical_digest recorded
    return next(iter(load_state(syncer.state_dir)))


def test_external_canonical_change_is_reprojected(tmp_path: Path) -> None:
    syncer = make_syncer(tmp_path)
    pair_id = _adopt(syncer, body="original")

    # Simulate an import overwriting the canonical out of band.
    canon = load_canonical(syncer.state_dir, pair_id)
    canon["body"] = "changed by import"
    save_canonical(syncer.state_dir, pair_id, canon)

    syncer.sync_once()  # FR-14: canonical changed, tools didn't -> re-project

    claude = syncer.tool_root("claude", "skill") / "demo" / "SKILL.md"
    codex = syncer.tool_root("codex", "skill") / "demo" / "SKILL.md"
    assert "changed by import" in claude.read_text()
    assert "changed by import" in codex.read_text()

    # Old bytes archived (NFR-01).
    arch = [p for p in (syncer.state_dir / "archive" / pair_id).rglob("*") if p.is_file()]
    assert any("original" in p.read_text() for p in arch)

    # Converges (NFR-05).
    assert syncer.sync_once().changed == 0


def test_tool_change_still_reverse_projects(tmp_path: Path) -> None:
    # Canonical-change detection must not break a normal tool-side edit.
    syncer = make_syncer(tmp_path)
    _adopt(syncer, body="v1")

    md = syncer.tool_root("claude", "skill") / "demo" / "SKILL.md"
    md.write_text(md.read_text().replace("v1", "v2"))
    syncer.sync_once()

    assert "v2" in (syncer.tool_root("codex", "skill") / "demo" / "SKILL.md").read_text()
    assert syncer.sync_once().changed == 0


def test_migration_populates_canonical_digest_without_reprojecting(tmp_path: Path) -> None:
    # An older state file (no canonical_digest) is migrated on load: the digest is
    # computed from the on-disk canonical, so the next poll does NOT see a spurious
    # canonical change.
    syncer = make_syncer(tmp_path)
    pair_id = _adopt(syncer)

    # Strip canonical_digest from the persisted state to mimic an older schema.
    state_path = syncer.state_dir / "state.json"
    raw = json.loads(state_path.read_text())
    arts = raw["customization_artifacts"]
    arts[pair_id].pop("canonical_digest", None)
    raw["schema_version"] = 3
    state_path.write_text(json.dumps(raw))

    fresh = make_syncer(tmp_path)
    result = fresh.sync_once()

    assert result.changed == 0  # migration recorded the digest; no spurious re-project
    assert load_state(fresh.state_dir)[pair_id].canonical_digest is not None
