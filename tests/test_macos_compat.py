from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.archive import archive_copy
from agents_sync.state import sha256_tree
from agents_sync.sync import Syncer, stage_skill_dir


def test_darwin_path_collision_key_is_case_insensitive(
    syncer: Syncer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agents_sync.sync.sys.platform", "darwin")

    upper = Path(syncer.codex_skills_dir) / "Alpha"
    lower = Path(syncer.codex_skills_dir) / "alpha"

    assert syncer._path_collision_key(upper) == syncer._path_collision_key(lower)


def test_linux_path_collision_key_is_case_sensitive(
    syncer: Syncer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agents_sync.sync.sys.platform", "linux")

    upper = Path(syncer.codex_skills_dir) / "Alpha"
    lower = Path(syncer.codex_skills_dir) / "alpha"

    assert syncer._path_collision_key(upper) != syncer._path_collision_key(lower)


def test_path_collision_key_normalizes_nfd_and_nfc(syncer: Syncer) -> None:
    nfc = Path(syncer.codex_skills_dir) / "café"
    nfd = Path(syncer.codex_skills_dir) / "café"

    assert str(nfc) != str(nfd)
    assert syncer._path_collision_key(nfc) == syncer._path_collision_key(nfd)


def test_skill_tree_hash_ignores_macos_metadata(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: demo\n---\nbody\n", encoding="utf-8")

    before = sha256_tree(skill)
    (skill / ".DS_Store").write_text("finder metadata", encoding="utf-8")
    (skill / "._SKILL.md").write_text("appledouble metadata", encoding="utf-8")

    assert sha256_tree(skill) == before


def test_skill_staging_skips_macos_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: demo\n---\nold\n", encoding="utf-8")
    (source / ".DS_Store").write_text("finder metadata", encoding="utf-8")
    (source / "._asset.png").write_text("appledouble metadata", encoding="utf-8")

    stage_skill_dir(source, target, "---\nname: demo\n---\nnew\n")

    assert (target / "SKILL.md").read_text(encoding="utf-8").endswith("new\n")
    assert not (target / ".DS_Store").exists()
    assert not (target / "._asset.png").exists()


def test_skill_archive_copy_skips_macos_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source"
    state_dir = tmp_path / "state"
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: demo\n---\nbody\n", encoding="utf-8")
    (source / ".DS_Store").write_text("finder metadata", encoding="utf-8")
    (source / "._asset.png").write_text("appledouble metadata", encoding="utf-8")

    archived = archive_copy(
        state_dir,
        "11111111-2222-4333-8444-555555555555",
        "claude",
        source,
    )

    assert (archived / "SKILL.md").exists()
    assert not (archived / ".DS_Store").exists()
    assert not (archived / "._asset.png").exists()
