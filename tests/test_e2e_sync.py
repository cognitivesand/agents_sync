"""End-to-end tests: drive Syncer.sync_once against tmp directories and assert
on resulting files, archive entries, and state."""
from __future__ import annotations

import os
from pathlib import Path

from agents_sync.sync import Syncer


def _claude_md(name: str = "foo", description: str = "x", body: str = "body") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}\n"


def _set_mtime(path: Path, value: float) -> None:
    os.utime(path, (value, value))


# ---------------- adoption ----------------

def test_adopt_from_claude_creates_codex_counterpart_and_archives_original(syncer: Syncer):
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text(_claude_md("foo", "the agent", "body"))

    changed = syncer.sync_once()

    assert changed == 1
    codex_files = list(Path(syncer.codex_agents_dir).iterdir())
    assert [p.name for p in codex_files] == ["foo.toml"]

    # pair_id was injected into the Claude file.
    assert "pair_id:" in claude_md.read_text()

    # Original (pre-injection) bytes archived.
    archive_root = syncer.state_dir / "archive"
    archived = list(archive_root.rglob("foo.md*"))
    assert len(archived) == 1


def test_adopt_from_codex_creates_claude_counterpart(syncer: Syncer):
    codex_toml = Path(syncer.codex_agents_dir) / "bar.toml"
    codex_toml.write_text(
        'name = "bar"\n'
        'description = "from codex"\n'
        'developer_instructions = "the body"\n'
    )

    changed = syncer.sync_once()

    assert changed == 1
    claude_files = list(Path(syncer.claude_agents_dir).iterdir())
    assert [p.name for p in claude_files] == ["bar.md"]
    assert "the body" in (Path(syncer.claude_agents_dir) / "bar.md").read_text()


# ---------------- edit propagation ----------------

def test_edit_claude_propagates_to_codex(syncer: Syncer):
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text(_claude_md(description="original"))
    syncer.sync_once()

    text = claude_md.read_text()
    claude_md.write_text(text.replace("original", "EDITED"))

    changed = syncer.sync_once()
    assert changed == 1

    codex_text = (Path(syncer.codex_agents_dir) / "foo.toml").read_text()
    assert "EDITED" in codex_text


def test_edit_codex_propagates_to_claude(syncer: Syncer):
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text(_claude_md(description="original"))
    syncer.sync_once()

    codex_toml = Path(syncer.codex_agents_dir) / "foo.toml"
    text = codex_toml.read_text()
    codex_toml.write_text(text.replace("original", "EDITED"))

    changed = syncer.sync_once()
    assert changed == 1

    assert "EDITED" in claude_md.read_text()


# ---------------- idempotency ----------------

def test_unchanged_inputs_produce_zero_changes(syncer: Syncer):
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text(_claude_md())
    syncer.sync_once()

    assert syncer.sync_once() == 0
    assert syncer.sync_once() == 0


# ---------------- archive bounding (NFR-07) ----------------

def test_routine_retranslation_does_not_grow_archive(syncer: Syncer):
    """An edit to Claude side that's a regular sync (not a conflict / not adoption)
    must not produce a new archive entry."""
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text(_claude_md(body="initial"))
    syncer.sync_once()  # adoption: 1 archive entry

    archived_before = list((syncer.state_dir / "archive").rglob("*"))
    archived_files_before = [p for p in archived_before if p.is_file()]

    # Routine edit on Claude side
    text = claude_md.read_text()
    claude_md.write_text(text.replace("initial", "second"))
    syncer.sync_once()

    archived_after_files = [
        p for p in (syncer.state_dir / "archive").rglob("*") if p.is_file()
    ]
    assert len(archived_after_files) == len(archived_files_before)


# ---------------- removal propagation ----------------

def test_remove_claude_archives_codex(syncer: Syncer):
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text(_claude_md())
    syncer.sync_once()

    claude_md.unlink()
    changed = syncer.sync_once()
    assert changed == 1

    assert list(Path(syncer.codex_agents_dir).iterdir()) == []
    archived = list((syncer.state_dir / "archive").rglob("foo.toml*"))
    assert len(archived) >= 1


def test_remove_codex_archives_claude(syncer: Syncer):
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text(_claude_md())
    syncer.sync_once()

    (Path(syncer.codex_agents_dir) / "foo.toml").unlink()
    changed = syncer.sync_once()
    assert changed == 1

    assert list(Path(syncer.claude_agents_dir).iterdir()) == []


# ---------------- conflict resolution ----------------

def test_conflict_is_resolved_by_mtime_with_loser_archived(syncer: Syncer):
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text(_claude_md(description="original"))
    syncer.sync_once()

    codex_toml = Path(syncer.codex_agents_dir) / "foo.toml"

    # Edit both sides; explicitly set mtimes so Claude wins.
    text_codex = codex_toml.read_text()
    codex_toml.write_text(text_codex.replace("original", "CODEX-LOSES"))
    _set_mtime(codex_toml, 1000.0)

    text_claude = claude_md.read_text()
    claude_md.write_text(text_claude.replace("original", "CLAUDE-WINS"))
    _set_mtime(claude_md, 2000.0)

    changed = syncer.sync_once()
    assert changed == 1

    assert "CLAUDE-WINS" in codex_toml.read_text()

    # Codex loser body must be in some archive entry.
    archived = [p for p in (syncer.state_dir / "archive").rglob("*.toml*") if p.is_file()]
    assert any("CODEX-LOSES" in p.read_text() for p in archived)


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

def test_dotfile_md_is_ignored_by_discovery(syncer: Syncer):
    """Path.glob('*.md') matches dotfiles; discovery must filter them explicitly."""
    (Path(syncer.claude_agents_dir) / ".hidden.md").write_text(
        "---\nname: hidden\n---\nshould be ignored\n"
    )
    (Path(syncer.claude_agents_dir) / "real.md").write_text(_claude_md("real"))

    changed = syncer.sync_once()

    assert changed == 1
    assert [p.name for p in Path(syncer.codex_agents_dir).iterdir()] == ["real.toml"]
