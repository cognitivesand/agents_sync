"""Shared test fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.sync import Syncer


@pytest.fixture
def syncer(tmp_path: Path) -> Syncer:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for sub in ("ca", "cc", "cs", "xa", "xp", "xs", "as", "oa", "oc", "os"):
        (tmp_path / sub).mkdir()

    config = {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "ca"),
        "claude_commands_dir": str(tmp_path / "cc"),
        "claude_skills_dir": str(tmp_path / "cs"),
        "codex_agents_dir": str(tmp_path / "xa"),
        "codex_prompts_dir": str(tmp_path / "xp"),
        "codex_skills_dir": str(tmp_path / "xs"),
        "antigravity_skills_dir": str(tmp_path / "as"),
        "antigravity_enabled": True,
        "opencode_agents_dir": str(tmp_path / "oa"),
        "opencode_commands_dir": str(tmp_path / "oc"),
        "opencode_skills_dir": str(tmp_path / "os"),
        "opencode_enabled": True,
    }
    return Syncer(config)
