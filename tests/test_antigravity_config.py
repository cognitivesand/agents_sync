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


def test_cli_parser_accepts_opencode_flags():
    parser = build_parser()
    args = parser.parse_args([
        "--opencode-agents-dir",
        "/agents",
        "--opencode-commands-dir",
        "/commands",
        "--opencode-skills-dir",
        "/skills",
        "--opencode-rules-dir",
        "/rules",
        "--no-opencode-enabled",
    ])
    assert args.opencode_agents_dir == "/agents"
    assert args.opencode_commands_dir == "/commands"
    assert args.opencode_skills_dir == "/skills"
    assert args.opencode_rules_dir == "/rules"
    assert args.opencode_enabled is False


def test_cli_parser_accepts_cursor_flags():
    parser = build_parser()
    args = parser.parse_args([
        "--cursor-agents-dir",
        "/cursor-agents",
        "--cursor-commands-dir",
        "/cursor-commands",
        "--cursor-skills-dir",
        "/cursor-skills",
        "--cursor-rules-dir",
        "/cursor-rules",
        "--cursor-mcp-servers-file",
        "/cursor/mcp.json",
        "--no-cursor-enabled",
    ])
    assert args.cursor_agents_dir == "/cursor-agents"
    assert args.cursor_commands_dir == "/cursor-commands"
    assert args.cursor_skills_dir == "/cursor-skills"
    assert args.cursor_rules_dir == "/cursor-rules"
    assert args.cursor_mcp_servers_file == "/cursor/mcp.json"
    assert args.cursor_enabled is False


def test_cli_parser_accepts_slash_command_root_flags():
    parser = build_parser()
    args = parser.parse_args([
        "--claude-commands-dir",
        "/claude-commands",
        "--codex-prompts-dir",
        "/codex-prompts",
    ])
    assert args.claude_commands_dir == "/claude-commands"
    assert args.codex_prompts_dir == "/codex-prompts"


def test_cli_parser_accepts_rules_dir_flags():
    parser = build_parser()
    args = parser.parse_args([
        "--claude-rules-dir",
        "/claude",
        "--codex-rules-dir",
        "/codex",
    ])

    assert args.claude_rules_dir == "/claude"
    assert args.codex_rules_dir == "/codex"


def test_cli_parser_accepts_mcp_server_secret_policy_flag():
    parser = build_parser()
    args = parser.parse_args(["--mcp-server-secret-policy", "redact"])

    assert args.mcp_server_secret_policy == "redact"


# ---------- merged_config ----------

def _minimal_args(**overrides: object) -> argparse.Namespace:
    """Build a minimal argparse Namespace driven by the merged_config table.

    Phase 2.6 of the audit remediation: the previous fixture hand-listed
    every CLI flag and silently fell behind whenever a new flag landed.
    Sourcing the keys from ``config._ARG_TO_CONFIG_KEY`` (plus a couple of
    parser-only attrs the loop does not consume) means a new flag is a
    one-line addition to the table, not a two-place edit.
    """
    from agents_sync.config import _ARG_TO_CONFIG_KEY

    base: dict[str, object] = {arg_attr: None for arg_attr, _ in _ARG_TO_CONFIG_KEY}
    # Attributes the merged_config table doesn't read but every Namespace
    # constructed from the parser still carries.
    base["config"] = None
    base["verbose"] = False
    base.update(overrides)
    return argparse.Namespace(**base)


def _test_config(tmp_path: Path, *, antigravity_enabled: bool = True) -> dict[str, str | float | bool]:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for sub in (
        "ca", "cc", "cs", "cr",
        "xa", "xp", "xs", "xr",
        "cura", "curc", "curs", "curr",
        "ga", "gc", "gs", "gr",
        "oa", "oc", "os", "or",
    ):
        (tmp_path / sub).mkdir()
    ag_root = tmp_path / "as"
    ag_root.mkdir(exist_ok=True)
    return {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "ca"),
        "claude_commands_dir": str(tmp_path / "cc"),
        "claude_skills_dir": str(tmp_path / "cs"),
        "claude_rules_dir": str(tmp_path / "cr"),
        "claude_mcp_servers_file": str(tmp_path / "claude-mcp.json"),
        "codex_agents_dir": str(tmp_path / "xa"),
        "codex_prompts_dir": str(tmp_path / "xp"),
        "codex_skills_dir": str(tmp_path / "xs"),
        "codex_rules_dir": str(tmp_path / "xr"),
        "codex_config_file": str(tmp_path / "codex-config.toml"),
        "cursor_agents_dir": str(tmp_path / "cura"),
        "cursor_commands_dir": str(tmp_path / "curc"),
        "cursor_skills_dir": str(tmp_path / "curs"),
        "cursor_rules_dir": str(tmp_path / "curr"),
        "cursor_mcp_servers_file": str(tmp_path / "cursor-mcp.json"),
        "cursor_enabled": True,
        "antigravity_skills_dir": str(ag_root),
        "antigravity_enabled": antigravity_enabled,
        "gemini_cli_agents_dir": str(tmp_path / "ga"),
        "gemini_cli_commands_dir": str(tmp_path / "gc"),
        "gemini_cli_skills_dir": str(tmp_path / "gs"),
        "gemini_cli_rules_dir": str(tmp_path / "gr"),
        "gemini_cli_enabled": False,
        "opencode_agents_dir": str(tmp_path / "oa"),
        "opencode_commands_dir": str(tmp_path / "oc"),
        "opencode_skills_dir": str(tmp_path / "os"),
        "opencode_rules_dir": str(tmp_path / "or"),
        "opencode_config_file": str(tmp_path / "opencode.json"),
        "opencode_enabled": True,
    }


def test_merged_config_falls_back_to_default_antigravity_dir():
    config = merged_config(_minimal_args())
    assert "antigravity_skills_dir" in config
    assert config["antigravity_enabled"] is True
    assert "gemini_cli_agents_dir" in config
    assert "gemini_cli_commands_dir" in config
    assert "gemini_cli_skills_dir" in config
    assert "gemini_cli_rules_dir" in config
    assert config["gemini_cli_enabled"] is True
    assert "opencode_agents_dir" in config
    assert "opencode_commands_dir" in config
    assert "opencode_skills_dir" in config
    assert "opencode_rules_dir" in config
    assert config["opencode_enabled"] is True
    assert "cursor_agents_dir" in config
    assert "cursor_commands_dir" in config
    assert "cursor_skills_dir" in config
    assert "cursor_rules_dir" in config
    assert config["cursor_enabled"] is True


def test_merged_config_honors_cli_antigravity_override(tmp_path: Path):
    override = str(tmp_path / "custom-antigravity")
    config = merged_config(_minimal_args(antigravity_skills_dir=override))
    assert config["antigravity_skills_dir"] == override


def test_merged_config_honors_cli_disable_flag():
    config = merged_config(_minimal_args(antigravity_enabled=False))
    assert config["antigravity_enabled"] is False


def test_merged_config_honors_secret_policy_override():
    config = merged_config(_minimal_args(secret_policy="secrets_accepted"))
    assert config["secret_policy"] == "secrets_accepted"


def test_merged_config_accepts_legacy_mcp_secret_policy_flag_with_deprecation(
    caplog: pytest.LogCaptureFixture,
):
    """The deprecated --mcp-server-secret-policy flag must keep working for
    one release. Old values map to new ones; old key is consumed and
    replaced by the canonical ``secret_policy`` with a DEPRECATION-WARNING.
    """
    with caplog.at_level("WARNING"):
        config = merged_config(_minimal_args(mcp_server_secret_policy="permissive"))
    assert config["secret_policy"] == "secrets_accepted"
    assert "mcp_server_secret_policy" not in config
    assert any("DEPRECATED" in r.message for r in caplog.records)


# ---------- Syncer status for antigravity ----------

def test_default_when_dir_present_is_available(syncer: Syncer, caplog: pytest.LogCaptureFixture):
    """Plan §3 deliverable: status=available when antigravity_skills_dir exists."""
    with caplog.at_level(logging.INFO):
        syncer.sync_once()
    assert syncer.tool_status.snapshot()["antigravity"] == "available"
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
    assert syncer.tool_status.snapshot()["antigravity"] == "unavailable"
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
    config = _test_config(tmp_path, antigravity_enabled=False)
    syncer = Syncer(config)
    with caplog.at_level(logging.INFO):
        syncer.sync_once()
    assert syncer.tool_status.snapshot()["antigravity"] == "disabled"
    antigravity_logs = [
        r for r in caplog.records if "agentic_tool antigravity" in r.getMessage()
    ]
    assert antigravity_logs == [], (
        f"disabled tool must be silent, got: {[r.getMessage() for r in antigravity_logs]}"
    )


def test_explicit_override_path_is_honored(tmp_path: Path):
    """Plan §3 deliverable: a non-default antigravity_skills_dir is used as-is."""
    config = _test_config(tmp_path)
    custom_root = tmp_path / "custom-antigravity-root"
    custom_root.mkdir()
    config["antigravity_skills_dir"] = str(custom_root)
    syncer = Syncer(config)
    syncer.sync_once()
    assert syncer.tool_status.snapshot()["antigravity"] == "available"


def test_disabled_tool_skips_discovery_even_if_dir_has_artifacts(tmp_path: Path):
    """A disabled tool is silently ignored regardless of on-disk state.

    This is the strong opt-out promised by US-11 / US-10 AC-7 — a fully-stocked
    antigravity_skills_dir does not appear in any sync activity when the
    enable-flag is off.
    """
    config = _test_config(tmp_path, antigravity_enabled=False)
    # Put a skill on the antigravity side that would otherwise adopt.
    ag_skill = tmp_path / "as" / "preexisting"
    ag_skill.mkdir()
    (ag_skill / "SKILL.md").write_text(
        "---\nname: preexisting\ndescription: should-be-ignored\n---\nbody\n"
    )

    syncer = Syncer(config)
    result = syncer.sync_once(); changed = result.changed
    assert changed == 0
    # No projection landed on claude_skills_dir; antigravity bytes intact.
    assert list(syncer.tool_root("claude", "skill").iterdir()) == []
    assert (ag_skill / "SKILL.md").exists()


def test_disabled_then_enabled_picks_up_new_artifacts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """Re-enabling antigravity transitions the status and resumes discovery."""
    base_config = _test_config(tmp_path, antigravity_enabled=False)
    syncer_disabled = Syncer(dict(base_config))
    syncer_disabled.sync_once()
    assert syncer_disabled.tool_status.snapshot()["antigravity"] == "disabled"

    enabled_config = dict(base_config)
    enabled_config["antigravity_enabled"] = True
    syncer_enabled = Syncer(enabled_config)
    with caplog.at_level(logging.INFO):
        syncer_enabled.sync_once()
    assert syncer_enabled.tool_status.snapshot()["antigravity"] == "available"
