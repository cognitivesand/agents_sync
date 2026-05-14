"""US-11 acceptance tests: graceful handling of unavailable agentic_tools.

Exercised at N=2 (claude, codex). Antigravity wiring lands in Phase 3.2; the
status invariants here are uniform across all three tools.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import pytest

from agents_sync.sync import Syncer


def _claude_md(name: str = "foo", description: str = "x", body: str = "body") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}\n"


def _read_state(syncer: Syncer) -> dict:
    state_file = syncer.state_dir / "state.json"
    if not state_file.exists():
        return {}
    return json.loads(state_file.read_text())


# ---------- AC-1: missing root at startup ----------

def test_missing_root_at_startup_does_not_raise(syncer: Syncer):
    """US-11 AC-1: a missing root marks the tool unavailable; daemon continues."""
    shutil.rmtree(syncer.codex_skills_dir)
    syncer.sync_once()  # must not raise
    assert syncer._tool_status["codex"] == "unavailable"
    assert syncer._tool_status["claude"] == "available"


def test_missing_root_at_startup_logs_info_line(syncer: Syncer, caplog: pytest.LogCaptureFixture):
    """US-11 AC-1: log line names the tool, missing root, and underlying reason."""
    shutil.rmtree(syncer.codex_agents_dir)
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
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text(_claude_md())
    syncer.sync_once()
    state_before = _read_state(syncer)

    shutil.rmtree(syncer.codex_agents_dir)

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
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text(_claude_md())
    syncer.sync_once()
    codex_artifact = Path(syncer.codex_agents_dir) / "foo-agent.toml"
    assert codex_artifact.exists()

    shutil.rmtree(syncer.codex_agents_dir)
    syncer.sync_once()

    # Claude side intact; state preserves codex's pre-removal entry.
    assert claude_md.exists()
    state = _read_state(syncer)
    pair_id = next(iter(state["customization_artifacts"]))
    assert set(state["customization_artifacts"][pair_id]["agentic_tools"].keys()) == {
        "claude",
        "codex",
    }


# ---------- AC-3: returning to available ----------

def test_returning_to_available_logs_info_and_extends(syncer: Syncer, caplog: pytest.LogCaptureFixture):
    """US-11 AC-3: tool returns to available ⇒ extension flow re-projects."""
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text(_claude_md())
    syncer.sync_once()

    shutil.rmtree(syncer.codex_agents_dir)
    syncer.sync_once()  # codex now unavailable
    assert syncer._tool_status["codex"] == "unavailable"

    syncer.codex_agents_dir.mkdir(parents=True)
    caplog.clear()
    with caplog.at_level(logging.INFO):
        syncer.sync_once()

    assert syncer._tool_status["codex"] == "available"
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
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text(_claude_md())
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

def test_all_tools_unavailable_is_a_no_op_poll(syncer: Syncer):
    """US-11 AC-7: even with every tool unavailable, sync_once continues."""
    shutil.rmtree(syncer.claude_agents_dir)
    shutil.rmtree(syncer.claude_skills_dir)
    shutil.rmtree(syncer.codex_agents_dir)
    shutil.rmtree(syncer.codex_skills_dir)

    # No raise, zero changes.
    changed = syncer.sync_once()
    assert changed == 0
    assert syncer._tool_status == {"claude": "unavailable", "codex": "unavailable"}


# ---------- Removal propagation only from available tools ----------

def test_removal_propagation_from_available_tool_still_works(syncer: Syncer):
    """Removing a file on a tool whose status is `available` propagates normally."""
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text(_claude_md())
    syncer.sync_once()
    codex_artifact = Path(syncer.codex_agents_dir) / "foo-agent.toml"
    assert codex_artifact.exists()

    claude_md.unlink()
    syncer.sync_once()

    # Codex side archived + removed; state cleaned up.
    assert not codex_artifact.exists()
    archive_root = syncer.state_dir / "archive"
    assert any(archive_root.rglob("foo-agent.toml*"))
