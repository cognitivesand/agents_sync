"""Regression: an unconfigured root for one kind must never crash sync.

Root cause of the daemon crash loop (status=1 every poll): a tool that is
*tool-available* via one customization_type but whose root for another kind is
unconfigured (value None) was still treated as a participant for that kind, so
projection/extension called render on a None root -> Path(None) -> TypeError ->
5 consecutive failed polls -> daemon exit -> systemd restart loop.

Real-world trigger: copilot is available via its CLI agents/skills surfaces but
its VS Code `rules` root (copilot_vscode_user_instructions_dir) is None; the
global `rules` pair tried to extend onto it.

Fix: participation is gated on kind-level availability (is_kind_available), and
render_to_agentic_tool raises a loud UnconfiguredRootError as a backstop.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import AgenticToolSpec
from agents_sync.rendering import UnconfiguredRootError, render_to_agentic_tool
from agents_sync.sync import Syncer
from agents_sync.tool_specs._rules_factory import build_global_rules_io

# Default-tool dir keys Syncer.validate requires even when only custom tools
# are registered.
_REQUIRED_DEFAULT_KEYS = (
    "claude_agents_dir", "claude_commands_dir", "claude_skills_dir", "claude_rules_dir",
    "codex_agents_dir", "codex_prompts_dir", "codex_skills_dir", "codex_rules_dir",
    "antigravity_skills_dir",
    "opencode_agents_dir", "opencode_commands_dir", "opencode_skills_dir", "opencode_rules_dir",
)


def _spec(name: str, kinds: dict[str, tuple[str, ...]]) -> AgenticToolSpec:
    return AgenticToolSpec(
        name=name,
        config_dir_keys={k: f"{name}_{k}_dir" for k in kinds},
        io={k: build_global_rules_io(name, cands) for k, cands in kinds.items()},
        partial_availability=True,
    )


def _syncer(tmp_path: Path) -> Syncer:
    config: dict[str, Any] = {
        "poll_interval_seconds": 1.0,
        "state_path": str(tmp_path / "state" / "state.json"),
        # alphalike: a normal global-rules tool with a configured rules root.
        "alphalike_rules_dir": str(tmp_path / "alpha"),
        # betalike: tool-available via its `agents` kind (root exists) but its
        # `rules` root is unconfigured (None) — the copilot situation.
        "betalike_agents_dir": str(tmp_path / "beta-agents"),
        "betalike_rules_dir": None,
    }
    for key in _REQUIRED_DEFAULT_KEYS:
        config[key] = str(tmp_path / f"unused-{key}")
    return Syncer(
        config,
        agentic_tools={
            "alphalike": _spec("alphalike", {"rules": ("AGENTS.md",)}),
            "betalike": _spec("betalike", {"rules": ("AGENTS.md",), "agents": ("AGENTS.md",)}),
        },
    )


def test_unconfigured_kind_root_does_not_crash_sync(tmp_path: Path):
    syncer = _syncer(tmp_path)
    alpha_root = syncer.tool_root("alphalike", "rules")
    (alpha_root / "AGENTS.md").write_text("---\nname: global\n---\nShared rules.\n")

    # Before the fix this raised TypeError (Path(None)) projecting onto
    # betalike's None rules root; the per-pair handler would record failed=1.
    result = syncer.sync_once()

    assert result.failed == ()
    # betalike is tool-available (via agents) but excluded from rules.
    assert syncer.tool_status.is_available("betalike") is True
    assert syncer.tool_status.is_kind_available("betalike", "rules") is False
    assert syncer.adoption._available_participating_tools("rules") == ["alphalike"]
    # No rules file was written under betalike's (unconfigured) rules surface.
    assert not (tmp_path / "beta-agents" / "AGENTS.md").exists()


def test_render_to_agentic_tool_raises_on_unconfigured_root():
    spec = _spec("x", {"rules": ("AGENTS.md",)})
    with pytest.raises(UnconfiguredRootError):
        render_to_agentic_tool(
            {},  # config_dir_keys["rules"] absent -> .get() is None
            spec,
            "rules",
            {"name": "global", "pair_id": "p", "body": "x"},
            existing_path=None,
            prior_text=None,
            source_dir=None,
        )
