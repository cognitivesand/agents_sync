"""Integration matrix for Codex, Cursor, and opencode adapters."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration  # audit slice 10 · TQ-01

import json
from pathlib import Path

from agents_sync.sync import Syncer


def _read_state(syncer: Syncer) -> dict:
    state_file = syncer.state_dir / "state.json"
    if not state_file.exists():
        return {}
    return json.loads(state_file.read_text())


def _the_only_pair(syncer: Syncer) -> tuple[str, dict]:
    state = _read_state(syncer)
    pairs = state["customization_artifacts"]
    assert len(pairs) == 1
    pair_id = next(iter(pairs))
    return pair_id, pairs[pair_id]


def _write_opencode_agent(root: Path, name: str, description: str = "from opencode") -> Path:
    path = root / f"{name}.md"
    path.write_text(f"---\ndescription: {description}\nmode: subagent\n---\nbody\n")
    return path


def _write_codex_agent(root: Path, name: str, description: str = "from codex") -> Path:
    path = root / f"{name}.toml"
    path.write_text(
        f'name = "{name}"\n'
        f'description = "{description}"\n'
        'sandbox_mode = "read-only"\n'
        'nickname_candidates = ["Atlas", "Delta"]\n'
        'developer_instructions = "body"\n'
        '\n[mcp_servers.docs]\n'
        'url = "https://developers.openai.com/mcp"\n'
    )
    return path


def _write_opencode_skill(root: Path, name: str, description: str = "from opencode") -> Path:
    skill_dir = root / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\nlicense: MIT\n---\nbody\n"
    )
    return skill_dir


def test_opencode_agent_adopts_to_claude_and_codex(syncer: Syncer):
    opencode_agent = _write_opencode_agent(syncer.tool_root("opencode", "agent"), "reviewer")

    syncer.sync_once()

    pair_id, entry = _the_only_pair(syncer)
    assert entry["customization_type"] == "agent"
    assert set(entry["agentic_tools"].keys()) == {
        "claude",
        "codex",
        "cursor",
        "opencode",
    }
    assert f"pair_id: {pair_id}" in opencode_agent.read_text()
    assert "name: reviewer" in (syncer.tool_root("claude", "agent") / "reviewer.md").read_text()
    assert 'name = "reviewer"' in (syncer.tool_root("codex", "agent") / "reviewer.toml").read_text()
    assert "name: reviewer" in (syncer.tool_root("cursor", "agent") / "reviewer.md").read_text()


def test_codex_agent_adopts_to_claude_and_opencode(syncer: Syncer):
    codex_agent = _write_codex_agent(syncer.tool_root("codex", "agent"), "pr_reviewer")

    syncer.sync_once()

    pair_id, entry = _the_only_pair(syncer)
    assert entry["customization_type"] == "agent"
    assert set(entry["agentic_tools"].keys()) == {
        "claude",
        "codex",
        "cursor",
        "opencode",
    }
    codex_text = codex_agent.read_text()
    assert f'pair_id = "{pair_id}"' in codex_text
    assert "nickname_candidates" in codex_text
    assert "[mcp_servers.docs]" in codex_text
    assert "name: pr_reviewer" in (
        syncer.tool_root("claude", "agent") / "pr_reviewer.md"
    ).read_text()
    assert "name: pr_reviewer" in (
        syncer.tool_root("cursor", "agent") / "pr_reviewer.md"
    ).read_text()
    opencode_text = (syncer.tool_root("opencode", "agent") / "pr_reviewer.md").read_text()
    assert "description: from codex" in opencode_text
    assert "sandbox_mode" not in opencode_text
    assert "nickname_candidates" not in opencode_text
    assert "mcp_servers" not in opencode_text


def test_opencode_skill_adopts_to_all_skill_tools(syncer: Syncer):
    opencode_skill = _write_opencode_skill(syncer.tool_root("opencode", "skill"), "fmt")

    syncer.sync_once()

    pair_id, entry = _the_only_pair(syncer)
    assert entry["customization_type"] == "skill"
    assert set(entry["agentic_tools"].keys()) == {
        "claude",
        "codex",
        "cursor",
        "antigravity",
        "opencode",
    }
    assert f"pair_id: {pair_id}" in (opencode_skill / "SKILL.md").read_text()
    for tool in ("claude", "codex", "cursor", "antigravity"):
        assert "from opencode" in (
            Path(entry["agentic_tools"][tool]["path"]) / "SKILL.md"
        ).read_text()
