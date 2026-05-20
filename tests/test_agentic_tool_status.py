"""US-11 acceptance tests: graceful handling of unavailable agentic_tools.

Exercised over skills (the customization_type all three tools participate
in). The status invariants are tool-agnostic.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import pytest

from agents_sync.sync import Syncer


def _skill_md(name: str = "foo", description: str = "x", body: str = "body") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}\n"


def _write_claude_skill(syncer: Syncer, name: str = "foo") -> Path:
    skill_dir = syncer.tool_root("claude", "skill") / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_skill_md(name))
    return skill_dir


def _read_state(syncer: Syncer) -> dict:
    state_file = syncer.state_dir / "state.json"
    if not state_file.exists():
        return {}
    return json.loads(state_file.read_text())


# ---------- AC-1: missing root at startup ----------

def test_missing_root_at_startup_does_not_raise(syncer: Syncer):
    """US-11 AC-1: a missing root marks the tool unavailable; daemon continues."""
    shutil.rmtree(syncer.tool_root("codex", "skill"))
    syncer.sync_once()  # must not raise
    assert syncer.tool_status.snapshot()["codex"] == "unavailable"
    assert syncer.tool_status.snapshot()["claude"] == "available"


def test_missing_root_at_startup_logs_info_line(syncer: Syncer, caplog: pytest.LogCaptureFixture):
    """US-11 AC-1: log line names the tool, missing root, and underlying reason."""
    shutil.rmtree(syncer.tool_root("codex", "skill"))
    with caplog.at_level(logging.INFO):
        syncer.sync_once()
    transition_log = [r for r in caplog.records if "agentic_tool codex" in r.getMessage()]
    assert transition_log, "expected a status transition log line for codex"
    msg = transition_log[0].getMessage()
    assert "startup -> unavailable" in msg
    assert "path does not exist" in msg


# ---------- AC-2: going unavailable mid-life ----------

def test_mid_life_unavailable_transition_logs_warning(
    syncer: Syncer, caplog: pytest.LogCaptureFixture
):
    """US-11 AC-2: WARN on the transition; state preserved."""
    _write_claude_skill(syncer)
    syncer.sync_once()
    state_before = _read_state(syncer)

    shutil.rmtree(syncer.tool_root("codex", "skill"))

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        syncer.sync_once()

    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "agentic_tool codex" in r.getMessage() and "-> unavailable" in r.getMessage()
        for r in warn_records
    )
    # State entries are preserved verbatim.
    assert _read_state(syncer) == state_before


def test_unavailable_tool_does_not_propagate_removal(syncer: Syncer):
    """US-11 AC-4: removal-propagation never fires from an unavailable tool."""
    claude_dir = _write_claude_skill(syncer)
    syncer.sync_once()
    codex_artifact = syncer.tool_root("codex", "skill") / "foo"
    assert codex_artifact.exists()

    shutil.rmtree(syncer.tool_root("codex", "skill"))
    syncer.sync_once()

    # Claude side intact; state preserves codex's pre-removal entry.
    assert claude_dir.exists()
    state = _read_state(syncer)
    pair_id = next(iter(state["customization_artifacts"]))
    assert "codex" in state["customization_artifacts"][pair_id]["agentic_tools"]


# ---------- AC-3: returning to available ----------

def test_returning_to_available_logs_info_and_extends(syncer: Syncer, caplog: pytest.LogCaptureFixture):
    """US-11 AC-3: tool returns to available ⇒ extension flow re-projects."""
    _write_claude_skill(syncer)
    syncer.sync_once()

    shutil.rmtree(syncer.tool_root("codex", "skill"))
    syncer.sync_once()  # codex now unavailable
    assert syncer.tool_status.snapshot()["codex"] == "unavailable"

    syncer.tool_root("codex", "skill").mkdir(parents=True)
    caplog.clear()
    with caplog.at_level(logging.INFO):
        syncer.sync_once()

    assert syncer.tool_status.snapshot()["codex"] == "available"
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any(
        "agentic_tool codex" in r.getMessage() and "-> available" in r.getMessage()
        for r in info_records
    )


# ---------- AC-5: log only on transition ----------

def test_steady_state_polls_emit_no_status_logs(
    syncer: Syncer, caplog: pytest.LogCaptureFixture
):
    """US-11 AC-5: no per-poll log line when status hasn't changed."""
    _write_claude_skill(syncer)
    syncer.sync_once()  # startup transitions emitted here

    caplog.clear()
    with caplog.at_level(logging.INFO):
        syncer.sync_once()
        syncer.sync_once()

    status_records = [
        r for r in caplog.records
        if r.getMessage().startswith("agentic_tool ")
    ]
    assert status_records == [], f"unexpected status logs: {[r.getMessage() for r in status_records]}"


# ---------- AC-7: all tools unavailable ----------

def test_all_tools_unavailable_is_a_no_op_poll(syncer: Syncer, tmp_path: Path):
    """US-11 AC-7: even with every tool unavailable, sync_once continues."""
    shutil.rmtree(syncer.tool_root("claude", "agent"))
    shutil.rmtree(syncer.tool_root("claude", "skill"))
    shutil.rmtree(syncer.tool_root("codex", "agent"))
    shutil.rmtree(syncer.tool_root("codex", "skill"))
    shutil.rmtree(syncer.tool_root("opencode", "agent"))
    shutil.rmtree(syncer.tool_root("opencode", "skill"))
    shutil.rmtree(tmp_path / "as")

    # No raise, zero changes.
    changed = syncer.sync_once()
    assert changed == 0
    assert syncer.tool_status.snapshot() == {
        "antigravity": "unavailable",
        "claude": "unavailable",
        "codex": "unavailable",
        "gemini_cli": "disabled",
        "opencode": "unavailable",
    }


# ---------- Removal propagation only from available tools ----------

def test_removal_propagation_from_available_tool_still_works(syncer: Syncer):
    """Removing a skill on a tool whose status is `available` propagates normally."""
    claude_dir = _write_claude_skill(syncer)
    syncer.sync_once()
    codex_artifact = syncer.tool_root("codex", "skill") / "foo"
    assert codex_artifact.exists()

    shutil.rmtree(claude_dir)
    syncer.sync_once()

    # Codex side archived + removed; state cleaned up.
    assert not codex_artifact.exists()
    archive_root = syncer.state_dir / "archive"
    assert any(archive_root.rglob("foo*"))
