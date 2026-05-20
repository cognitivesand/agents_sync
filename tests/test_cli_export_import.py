"""CLI smoke tests for the export/import subcommands (US-12 AC-8 + wiring)."""
from __future__ import annotations

import zipfile
from pathlib import Path

from agents_sync.cli import main
from agents_sync.portable_archive import CANONICAL_PREFIX, MANIFEST_NAME
from agents_sync.sync import Syncer


def _skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: x\n---\nbody\n"


def _render_toml(cfg: dict) -> str:
    """Render a config dict as TOML. String values use literal (single-quoted)
    syntax so Windows-style paths with backslashes survive intact — TOML basic
    strings would treat `\\U` and `\\x` as escape sequences and fail to parse.
    """
    lines = ["[agents-sync]"]
    for key, value in cfg.items():
        if isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key} = {value}")
        else:
            text = str(value)
            assert "'" not in text, f"path with apostrophe breaks literal TOML: {text!r}"
            lines.append(f"{key} = '{text}'")
    return "\n".join(lines) + "\n"


def _config_toml(syncer: Syncer) -> str:
    """Render the syncer fixture's runtime config to a TOML file the CLI can read."""
    return _render_toml(syncer.config)


def _write_config(syncer: Syncer, tmp_path: Path) -> Path:
    cfg_path = tmp_path / "agents-sync.toml"
    cfg_path.write_text(_config_toml(syncer))
    return cfg_path


def test_cli_export_writes_zip_with_manifest(syncer: Syncer, tmp_path: Path):
    skill_dir = syncer.tool_root("claude", "skill") / "foo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_skill_md("foo"))
    syncer.sync_once()

    cfg_path = _write_config(syncer, tmp_path)
    out_zip = tmp_path / "snapshot.zip"

    exit_code = main(["--config", str(cfg_path), "export", str(out_zip)])

    assert exit_code == 0
    assert out_zip.exists()
    with zipfile.ZipFile(out_zip) as zf:
        names = set(zf.namelist())
    assert MANIFEST_NAME in names
    assert any(n.startswith(CANONICAL_PREFIX) for n in names)


def _build_target_install(tmp_path: Path, label: str) -> tuple[Path, Path]:
    """Materialise empty roots for a fresh target install and return (root, cfg_path)."""
    root = tmp_path / label
    state_dir = root / "state"
    state_dir.mkdir(parents=True)
    for sub in (
        "ca", "cc", "cs", "cr",
        "xa", "xp", "xs", "xr",
        "as",
        "ga", "gc", "gs", "gr",
        "oa", "oc", "os", "or",
    ):
        (root / sub).mkdir(parents=True)
    cfg = {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(root / "ca"),
        "claude_commands_dir": str(root / "cc"),
        "claude_skills_dir": str(root / "cs"),
        "claude_rules_dir": str(root / "cr"),
        "codex_agents_dir": str(root / "xa"),
        "codex_prompts_dir": str(root / "xp"),
        "codex_skills_dir": str(root / "xs"),
        "codex_rules_dir": str(root / "xr"),
        "antigravity_skills_dir": str(root / "as"),
        "antigravity_enabled": True,
        "gemini_cli_agents_dir": str(root / "ga"),
        "gemini_cli_commands_dir": str(root / "gc"),
        "gemini_cli_skills_dir": str(root / "gs"),
        "gemini_cli_rules_dir": str(root / "gr"),
        "gemini_cli_enabled": False,
        "opencode_agents_dir": str(root / "oa"),
        "opencode_commands_dir": str(root / "oc"),
        "opencode_skills_dir": str(root / "os"),
        "opencode_rules_dir": str(root / "or"),
        "opencode_enabled": True,
        "import_collision_strategy": "mtime_wins",
    }
    cfg_path = tmp_path / f"{label}.toml"
    cfg_path.write_text(_render_toml(cfg))
    return root, cfg_path


def test_cli_export_then_import_roundtrip(syncer: Syncer, tmp_path: Path):
    """Export from one install, import into a fresh install via CLI."""
    skill_dir = syncer.tool_root("claude", "skill") / "foo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_skill_md("foo"))
    syncer.sync_once()

    src_cfg = _write_config(syncer, tmp_path)
    out_zip = tmp_path / "snapshot.zip"
    assert main(["--config", str(src_cfg), "export", str(out_zip)]) == 0

    target_root, target_cfg = _build_target_install(tmp_path, "target")
    exit_code = main(["--config", str(target_cfg), "import", str(out_zip)])

    assert exit_code == 0
    for sub in ("cs", "xs", "as", "os"):
        assert (target_root / sub / "foo" / "SKILL.md").exists()


def test_cli_import_collision_strategy_flag_overrides_config(
    syncer: Syncer, tmp_path: Path
):
    """CLI --collision-strategy must take precedence over config (AC-8)."""
    skill_dir = syncer.tool_root("claude", "skill") / "foo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_skill_md("foo"))
    syncer.sync_once()

    cfg_path = _write_config(syncer, tmp_path)
    out_zip = tmp_path / "snapshot.zip"
    assert main(["--config", str(cfg_path), "export", str(out_zip)]) == 0

    # Make local last_modified ancient so mtime_wins would accept the import.
    # If --collision-strategy=skip works, the import is rejected anyway.
    from agents_sync.state import load_state, save_state

    state = load_state(syncer.state_dir)
    pair_id = next(iter(state.keys()))
    state[pair_id].last_modified = 1.0
    save_state(syncer.state_dir, state)
    canonical_before = (syncer.state_dir / "canonical" / f"{pair_id}.json").read_bytes()

    exit_code = main(
        [
            "--config",
            str(cfg_path),
            "import",
            str(out_zip),
            "--collision-strategy",
            "skip",
        ]
    )

    assert exit_code == 0
    canonical_after = (syncer.state_dir / "canonical" / f"{pair_id}.json").read_bytes()
    assert canonical_after == canonical_before  # skip → local untouched


def test_cli_import_returns_nonzero_on_malformed_archive(
    syncer: Syncer, tmp_path: Path
):
    cfg_path = _write_config(syncer, tmp_path)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("canonical/something.json", "{}")
    # No manifest → import must reject and return non-zero.

    exit_code = main(["--config", str(cfg_path), "import", str(bad)])

    assert exit_code == 1


def test_cli_no_subcommand_still_invokes_daemon(monkeypatch):
    """Back-compat: invoking with no subcommand must still call watch()."""
    from agents_sync import cli as cli_module

    invoked = {"watch": False}

    def fake_watch(syncer, interval):
        invoked["watch"] = True

    # Make watch return immediately so the test doesn't loop forever.
    monkeypatch.setattr(cli_module, "watch", fake_watch)
    # Avoid touching the real filesystem during the bare-default run.
    monkeypatch.setattr(cli_module, "_check_legacy_install", lambda: None)
    monkeypatch.setattr(cli_module, "Syncer", lambda config: object())
    monkeypatch.setattr(cli_module, "validate_config", lambda config: None)
    monkeypatch.setattr(
        cli_module, "merged_config", lambda args: {"poll_interval_seconds": 0.0}
    )

    rc = cli_module.main([])

    assert rc == 0
    assert invoked["watch"] is True
