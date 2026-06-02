from __future__ import annotations

from pathlib import Path

from agents_sync.agentic_tool_spec import (
    CustomizationTypeIO,
    DirectorySkillLayout,
    SingleFileLayout,
)
from agents_sync.discovery import enumerator as enumerator_module
from agents_sync.discovery.enumerator import EnumeratorMixin
from agents_sync.markdown_yaml_metadata_block import extract_pair_id_from_md
from agents_sync.state import sha256_text, sha256_tree
from agents_sync.sync_types import CustomizationArtifactInfo

PAIR_ID = "00000000-0000-4000-8000-000000000201"


class _Host(EnumeratorMixin):
    def state_owner_for_path(self, path, state, slot=None):  # noqa: ANN001
        return None


def _unused_parse(text, prior_canonical, *, artifact_path=None, artifact_root=None):  # noqa: ANN001
    return {}


def _unused_render(canonical, prior_text=None):  # noqa: ANN001
    return ""


def test_single_file_discovery_digest_matches_text_snapshot(
    tmp_path: Path,
    monkeypatch,
):
    path = tmp_path / "agent.md"
    original = f"---\npair_id: {PAIR_ID}\nname: demo\n---\nold\n"
    changed = f"---\npair_id: {PAIR_ID}\nname: demo\n---\nnew\n"
    path.write_text(original, encoding="utf-8")

    def read_then_mutate(io, read_path, slot=None):  # noqa: ANN001
        assert read_path == path
        path.write_text(changed, encoding="utf-8")
        return original

    monkeypatch.setattr(enumerator_module, "read_artifact_text", read_then_mutate)
    io = CustomizationTypeIO(
        parse=_unused_parse,
        render=_unused_render,
        extract_pair_id=extract_pair_id_from_md,
        file_layout=SingleFileLayout(extension=".md"),
    )
    pairs: dict[str, CustomizationArtifactInfo] = {}

    _Host()._add_agentic_tool_artifact(
        "claude",
        "agent",
        path,
        io,
        pairs,
        set(),
        {},
    )

    assert pairs[PAIR_ID].agentic_tools["claude"].digest == sha256_text(original)
    assert pairs[PAIR_ID].agentic_tools["claude"].digest != sha256_text(changed)


def test_directory_skill_digest_uses_skill_md_text_snapshot(
    tmp_path: Path,
    monkeypatch,
):
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    original = f"---\npair_id: {PAIR_ID}\nname: demo\n---\nold\n"
    changed = f"---\npair_id: {PAIR_ID}\nname: demo\n---\nnew\n"
    (skill_dir / "SKILL.md").write_text(original, encoding="utf-8")
    (skill_dir / "notes.md").write_text("notes\n", encoding="utf-8")

    def read_then_mutate(io, read_path, slot=None):  # noqa: ANN001
        assert read_path == skill_dir
        (skill_dir / "SKILL.md").write_text(changed, encoding="utf-8")
        return original

    monkeypatch.setattr(enumerator_module, "read_artifact_text", read_then_mutate)
    io = CustomizationTypeIO(
        parse=_unused_parse,
        render=_unused_render,
        extract_pair_id=extract_pair_id_from_md,
        file_layout=DirectorySkillLayout(),
    )
    pairs: dict[str, CustomizationArtifactInfo] = {}

    _Host()._add_agentic_tool_artifact(
        "claude",
        "skill",
        skill_dir,
        io,
        pairs,
        set(),
        {},
    )

    assert pairs[PAIR_ID].agentic_tools["claude"].digest != sha256_tree(skill_dir)
