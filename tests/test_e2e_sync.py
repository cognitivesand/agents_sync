"""End-to-end edge cases: drive Syncer.sync_once against tmp directories and
assert on resulting files, archive entries, and state.

The bidirectional / N-way algorithm itself is exercised at N=3 in
tests/test_antigravity_three_way.py. This file focuses on edge cases that
are independent of the customization_type (dotfile filter, invalid pair_id
handling, duplicate IDs, foreign-slug collisions, archive bounding).
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from agents_sync.sync import Syncer


def _skill_md(name: str = "foo", description: str = "x", body: str = "body") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}\n"


def _write_claude_skill(syncer: Syncer, name: str = "foo", **kwargs: str) -> Path:
    skill_dir = Path(syncer.claude_skills_dir) / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_skill_md(name, **kwargs))
    return skill_dir


def _set_mtime(path: Path, value: float) -> None:
    os.utime(path, (value, value))


# ---------------- idempotency ----------------

def test_unchanged_inputs_produce_zero_changes(syncer: Syncer):
    _write_claude_skill(syncer)
    syncer.sync_once()

    assert syncer.sync_once() == 0
    assert syncer.sync_once() == 0


# ---------------- archive bounding (NFR-07) ----------------

def test_routine_retranslation_does_not_grow_archive(syncer: Syncer):
    """An edit that's a regular sync (not a conflict / not adoption) must not
    produce a new archive entry."""
    claude_dir = _write_claude_skill(syncer, body="initial")
    syncer.sync_once()  # adoption archives the pre-injection bytes

    archived_files_before = [
        p for p in (syncer.state_dir / "archive").rglob("*") if p.is_file()
    ]

    md = claude_dir / "SKILL.md"
    md.write_text(md.read_text().replace("initial", "second"))
    syncer.sync_once()

    archived_files_after = [
        p for p in (syncer.state_dir / "archive").rglob("*") if p.is_file()
    ]
    assert len(archived_files_after) == len(archived_files_before)


# ---------------- skill folders ----------------

def test_skill_aux_files_propagate_and_are_preserved(syncer: Syncer):
    skill_dir = Path(syncer.claude_skills_dir) / "skill-a"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: skill-a\ndescription: x\n---\nbody\n"
    )
    (skill_dir / "asset.txt").write_text("aux payload\n")

    syncer.sync_once()

    codex_skill = Path(syncer.codex_skills_dir) / "skill-a"
    assert codex_skill.is_dir()
    assert (codex_skill / "SKILL.md").exists()
    assert (codex_skill / "asset.txt").read_text() == "aux payload\n"


# ---------------- dotfile filter ----------------

def test_dotfile_skill_dir_is_ignored_by_discovery(syncer: Syncer):
    """`Path.glob('*/SKILL.md')` matches dotfile dirs; discovery must filter."""
    hidden = Path(syncer.claude_skills_dir) / ".hidden"
    hidden.mkdir()
    (hidden / "SKILL.md").write_text(_skill_md("hidden", body="should be ignored"))

    real = Path(syncer.claude_skills_dir) / "real"
    real.mkdir()
    (real / "SKILL.md").write_text(_skill_md("real"))

    syncer.sync_once()

    assert {p.name for p in Path(syncer.codex_skills_dir).iterdir()} == {"real"}


# ---------------- pair_id validation ----------------

def test_invalid_pair_id_is_skipped_without_blocking_valid_pairs(syncer: Syncer):
    bad = Path(syncer.claude_skills_dir) / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text(
        "---\npair_id: ../escape\nname: bad\n---\nbody\n"
    )
    good = Path(syncer.claude_skills_dir) / "good"
    good.mkdir()
    (good / "SKILL.md").write_text(_skill_md("good"))

    syncer.sync_once()

    assert "pair_id: ../escape" in (bad / "SKILL.md").read_text()
    assert {p.name for p in Path(syncer.codex_skills_dir).iterdir()} == {"good"}
    assert not (syncer.state_dir.parent / "escape.json").exists()


def test_invalid_pair_id_on_managed_file_does_not_propagate_deletion(syncer: Syncer):
    claude_dir = _write_claude_skill(syncer)
    syncer.sync_once()
    codex_dir = Path(syncer.codex_skills_dir) / "foo"
    state_before = (syncer.state_dir / "state.json").read_text()

    md = claude_dir / "SKILL.md"
    md.write_text(md.read_text().replace("pair_id:", "pair_id: ../escape #"))

    changed = syncer.sync_once()

    assert changed == 0
    assert claude_dir.exists()
    assert codex_dir.exists()
    assert (syncer.state_dir / "state.json").read_text() == state_before


def test_duplicate_pair_id_on_same_side_is_left_untouched(syncer: Syncer):
    pair_id = str(uuid.uuid4())
    first = Path(syncer.claude_skills_dir) / "first"
    second = Path(syncer.claude_skills_dir) / "second"
    first.mkdir()
    second.mkdir()
    first_text = f"---\npair_id: {pair_id}\nname: first\n---\nfirst\n"
    second_text = f"---\npair_id: {pair_id}\nname: second\n---\nsecond\n"
    (first / "SKILL.md").write_text(first_text)
    (second / "SKILL.md").write_text(second_text)

    changed = syncer.sync_once()

    assert changed == 0
    assert (first / "SKILL.md").read_text() == first_text
    assert (second / "SKILL.md").read_text() == second_text
    assert list(Path(syncer.codex_skills_dir).iterdir()) == []


# ---------------- target-slug collisions ----------------

def test_two_foreign_artifacts_with_same_slug_are_not_adopted(syncer: Syncer):
    first = Path(syncer.claude_skills_dir) / "first"
    second = Path(syncer.claude_skills_dir) / "second"
    first.mkdir()
    second.mkdir()
    (first / "SKILL.md").write_text(_skill_md("same"))
    (second / "SKILL.md").write_text(_skill_md("same"))

    changed = syncer.sync_once()

    assert changed == 0
    assert "pair_id:" not in (first / "SKILL.md").read_text()
    assert "pair_id:" not in (second / "SKILL.md").read_text()
    assert list(Path(syncer.codex_skills_dir).iterdir()) == []


# ---------------- prior-text read failures (CQ-04) ----------------

def test_unreadable_prior_text_logs_warning_and_continues(
    syncer: Syncer, caplog, monkeypatch
):
    """When the target's prior text can't be read during a sync from another
    tool, the renderer must fall back to prior_text=None and the failure must
    be visible in the logs — not silently swallowed."""
    claude_dir = _write_claude_skill(syncer, body="v1")
    syncer.sync_once()

    codex_dir = Path(syncer.codex_skills_dir) / "foo"
    assert (codex_dir / "SKILL.md").exists()

    # Patch the read_artifact_text name as resolved inside agents_sync.adoption
    # only. agents_sync.discovery imports the same function under its own
    # name binding, so discovery's read of the codex artifact still succeeds;
    # only the prior_text read inside _sync_from_agentic_tool fails.
    import agents_sync.adoption as adoption_mod
    original_read = adoption_mod.read_artifact_text

    def patched_read(io, path: Path) -> str:
        if Path(path) == codex_dir:
            raise OSError("simulated prior-text read failure")
        return original_read(io, path)

    monkeypatch.setattr(adoption_mod, "read_artifact_text", patched_read)

    claude_md = claude_dir / "SKILL.md"
    claude_md.write_text(claude_md.read_text().replace("v1", "v2"))
    _set_mtime(claude_md, 2_000_000_000.0)

    with caplog.at_level("WARNING", logger="root"):
        syncer.sync_once()

    assert any(
        "Could not read prior text" in record.getMessage()
        for record in caplog.records
    ), f"expected warning not logged; got: {[r.getMessage() for r in caplog.records]}"
    assert "v2" in (codex_dir / "SKILL.md").read_text()


def test_foreign_artifact_slug_collision_with_managed_pair_is_not_adopted(syncer: Syncer):
    managed = Path(syncer.claude_skills_dir) / "managed"
    managed.mkdir()
    (managed / "SKILL.md").write_text(_skill_md("same"))
    assert syncer.sync_once() == 1
    state_before = json.loads((syncer.state_dir / "state.json").read_text())

    foreign = Path(syncer.claude_skills_dir) / "foreign"
    foreign.mkdir()
    (foreign / "SKILL.md").write_text(_skill_md("same", body="foreign"))

    changed = syncer.sync_once()

    assert changed == 0
    assert "pair_id:" not in (foreign / "SKILL.md").read_text()
    assert json.loads((syncer.state_dir / "state.json").read_text()) == state_before
