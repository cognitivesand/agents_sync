"""Shared test fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.sync import Syncer


@pytest.fixture
def syncer(tmp_path: Path) -> Syncer:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for sub in (
        "ca", "cc", "cs", "cr",
        "xa", "xp", "xs", "xr",
        "as",
        "ga", "gc", "gs", "gr",
        "oa", "oc", "os", "or",
    ):
        (tmp_path / sub).mkdir()

    config = {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "ca"),
        "claude_commands_dir": str(tmp_path / "cc"),
        "claude_skills_dir": str(tmp_path / "cs"),
        "claude_rules_dir": str(tmp_path / "cr"),
        "codex_agents_dir": str(tmp_path / "xa"),
        "codex_prompts_dir": str(tmp_path / "xp"),
        "codex_skills_dir": str(tmp_path / "xs"),
        "codex_rules_dir": str(tmp_path / "xr"),
        "antigravity_skills_dir": str(tmp_path / "as"),
        "antigravity_enabled": True,
        "gemini_cli_agents_dir": str(tmp_path / "ga"),
        "gemini_cli_commands_dir": str(tmp_path / "gc"),
        "gemini_cli_skills_dir": str(tmp_path / "gs"),
        "gemini_cli_rules_dir": str(tmp_path / "gr"),
        "gemini_cli_enabled": False,
        "opencode_agents_dir": str(tmp_path / "oa"),
        "opencode_commands_dir": str(tmp_path / "oc"),
        "opencode_skills_dir": str(tmp_path / "os"),
        "opencode_rules_dir": str(tmp_path / "or"),
        "opencode_enabled": True,
    }
    return Syncer(config)
