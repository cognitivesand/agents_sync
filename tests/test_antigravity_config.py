"""Phase 3.2 deliverable tests: Antigravity config wiring + per-OS defaults.

Plan §3 deliverables:
  - Updated platform_defaults, merged_config, validate_config.
  - New CLI flag (--antigravity-skills-dir, --antigravity-enabled) and parser wiring.
  - Tests for: enabled-but-missing-dir (status `unavailable`, logged, daemon
    continues), explicit-disable-with-existing-dir (status `disabled`, silent),
    default-when-dir-present (status `available`), explicit-override-path
    (honored).
"""
from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

import pytest

from agents_sync.cli import build_parser
from agents_sync.config import merged_config, platform_defaults
from agents_sync.sync import Syncer


# ---------- per-OS defaults ----------

def test_linux_defaults_include_antigravity_skills_dir():
    home = Path("/home/tester")
    defaults = platform_defaults(os_name="posix", env={}, home=home)
    assert defaults["antigravity_skills_dir"] == str(
        home / ".gemini" / "antigravity" / "skills"
    )
    assert defaults["antigravity_enabled"] is True


def test_windows_defaults_include_antigravity_skills_dir():
    home = Path(r"C:\Users\tester")
    defaults = platform_defaults(os_name="nt", env={}, home=home)
    # Path joins use the runtime OS separator, so we compare via Path equality.
    assert Path(defaults["antigravity_skills_dir"]) == home / ".gemini" / "antigravity" / "skills"
    assert defaults["antigravity_enabled"] is True


# ---------- CLI parser ----------

def test_cli_parser_accepts_antigravity_skills_dir_flag():
    parser = build_parser()
    args = parser.parse_args(["--antigravity-skills-dir", "/some/path"])
    assert args.antigravity_skills_dir == "/some/path"


def test_cli_parser_accepts_no_antigravity_flag():
    parser = build_parser()
    args = parser.parse_args(["--no-antigravity-enabled"])
    assert args.antigravity_enabled is False


def test_cli_parser_default_leaves_antigravity_settings_unset():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.antigravity_skills_dir is None
    assert args.antigravity_enabled is None


# ---------- merged_config ----------

def _minimal_args(**overrides: object) -> argparse.Namespace:
    base = dict(
        config=None,
        interval=None,
        claude_agents_dir=None,
        claude_skills_dir=None,
        codex_skills_dir=None,
        antigravity_skills_dir=None,
        antigravity_enabled=None,
        state_path=None,
        verbose=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_merged_config_falls_back_to_default_antigravity_dir():
    config = merged_config(_minimal_args())
    assert "antigravity_skills_dir" in config
    assert config["antigravity_enabled"] is True


def test_merged_config_honors_cli_antigravity_override(tmp_path: Path):
    override = str(tmp_path / "custom-antigravity")
    config = merged_config(_minimal_args(antigravity_skills_dir=override))
    assert config["antigravity_skills_dir"] == override


def test_merged_config_honors_cli_disable_flag():
    config = merged_config(_minimal_args(antigravity_enabled=False))
    assert config["antigravity_enabled"] is False


# ---------- Syncer status for antigravity ----------

def test_default_when_dir_present_is_available(syncer: Syncer, caplog: pytest.LogCaptureFixture):
    """Plan §3 deliverable: status=available when antigravity_skills_dir exists."""
    with caplog.at_level(logging.INFO):
        syncer.sync_once()
    assert syncer._tool_status["antigravity"] == "available"
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any(
        "agentic_tool antigravity" in r.getMessage() and "-> available" in r.getMessage()
        for r in info_records
    )


def test_enabled_but_missing_dir_is_unavailable_and_logs(
    syncer: Syncer, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """Plan §3 deliverable: status=unavailable when dir missing; daemon continues."""
    shutil.rmtree(tmp_path / "as")
    with caplog.at_level(logging.INFO):
        syncer.sync_once()
    assert syncer._tool_status["antigravity"] == "unavailable"
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any(
        "agentic_tool antigravity" in r.getMessage()
        and "startup -> unavailable" in r.getMessage()
        for r in info_records
    )


def test_explicit_disable_with_existing_dir_is_disabled_and_silent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """Plan §3 deliverable: antigravity_enabled=false ⇒ disabled, no log lines."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for sub in ("ca", "cs", "xs", "as"):
        (tmp_path / sub).mkdir()
    config = {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "ca"),
        "claude_skills_dir": str(tmp_path / "cs"),
        "codex_skills_dir": str(tmp_path / "xs"),
        "antigravity_skills_dir": str(tmp_path / "as"),
        "antigravity_enabled": False,
    }
    syncer = Syncer(config)
    with caplog.at_level(logging.INFO):
        syncer.sync_once()
    assert syncer._tool_status["antigravity"] == "disabled"
    antigravity_logs = [
        r for r in caplog.records if "agentic_tool antigravity" in r.getMessage()
    ]
    assert antigravity_logs == [], (
        f"disabled tool must be silent, got: {[r.getMessage() for r in antigravity_logs]}"
    )


def test_explicit_override_path_is_honored(tmp_path: Path):
    """Plan §3 deliverable: a non-default antigravity_skills_dir is used as-is."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for sub in ("ca", "cs", "xs"):
        (tmp_path / sub).mkdir()
    custom_root = tmp_path / "custom-antigravity-root"
    custom_root.mkdir()

    config = {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "ca"),
        "claude_skills_dir": str(tmp_path / "cs"),
        "codex_skills_dir": str(tmp_path / "xs"),
        "antigravity_skills_dir": str(custom_root),
        "antigravity_enabled": True,
    }
    syncer = Syncer(config)
    syncer.sync_once()
    assert syncer._tool_status["antigravity"] == "available"


def test_disabled_tool_skips_discovery_even_if_dir_has_artifacts(tmp_path: Path):
    """A disabled tool is silently ignored regardless of on-disk state.

    This is the strong opt-out promised by US-11 / US-10 AC-7 — a fully-stocked
    antigravity_skills_dir does not appear in any sync activity when the
    enable-flag is off.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for sub in ("ca", "cs", "xs", "as"):
        (tmp_path / sub).mkdir()
    # Put a skill on the antigravity side that would otherwise adopt.
    ag_skill = tmp_path / "as" / "preexisting"
    ag_skill.mkdir()
    (ag_skill / "SKILL.md").write_text(
        "---\nname: preexisting\ndescription: should-be-ignored\n---\nbody\n"
    )

    config = {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "ca"),
        "claude_skills_dir": str(tmp_path / "cs"),
        "codex_skills_dir": str(tmp_path / "xs"),
        "antigravity_skills_dir": str(tmp_path / "as"),
        "antigravity_enabled": False,
    }
    syncer = Syncer(config)
    changed = syncer.sync_once()
    assert changed == 0
    # No projection landed on claude_skills_dir; antigravity bytes intact.
    assert list(Path(syncer.claude_skills_dir).iterdir()) == []
    assert (ag_skill / "SKILL.md").exists()


def test_disabled_then_enabled_picks_up_new_artifacts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """Re-enabling antigravity transitions the status and resumes discovery."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for sub in ("ca", "cs", "xs", "as"):
        (tmp_path / sub).mkdir()
    base_config = {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "ca"),
        "claude_skills_dir": str(tmp_path / "cs"),
        "codex_skills_dir": str(tmp_path / "xs"),
        "antigravity_skills_dir": str(tmp_path / "as"),
        "antigravity_enabled": False,
    }
    syncer_disabled = Syncer(dict(base_config))
    syncer_disabled.sync_once()
    assert syncer_disabled._tool_status["antigravity"] == "disabled"

    enabled_config = dict(base_config)
    enabled_config["antigravity_enabled"] = True
    syncer_enabled = Syncer(enabled_config)
    with caplog.at_level(logging.INFO):
        syncer_enabled.sync_once()
    assert syncer_enabled._tool_status["antigravity"] == "available"
