"""Regression tests for text newline normalisation during state digest updates."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from ._helpers import make_syncer, skill_md


def test_crlf_tool_side_skill_edit_converges(tmp_path: Path) -> None:
    syncer = make_syncer(tmp_path)
    skill_dir = syncer.tool_root("claude", "skill") / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(skill_md("demo", body="v1"), encoding="utf-8")
    syncer.sync_once()

    md = skill_dir / "SKILL.md"
    md.write_text(
        md.read_text(encoding="utf-8").replace("v1", "v2").replace("\n", "\r\n"),
        encoding="utf-8",
    )

    assert syncer.sync_once().changed == 1
    assert syncer.sync_once().changed == 0
