"""Smoke tests for the v0.4 migration script.

The script lives under ``scripts/`` (not on the package path), so we load it
via importlib. We only test the contracts that the recent cleanup added:
phase-aware error reporting and the dataclass shape of the results.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def migrate_mod():
    path = Path(__file__).resolve().parent.parent / "scripts" / "migrate_v0.4.py"
    spec = importlib.util.spec_from_file_location("migrate_v0_4_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_phase_wraps_failure_with_phase_name(migrate_mod):
    """A phase failure must be raised as MigrationError carrying the phase
    name and chaining the original exception as __cause__."""
    def boom():
        raise RuntimeError("simulated underlying failure")

    with pytest.raises(migrate_mod.MigrationError) as exc_info:
        migrate_mod._run_phase("rewrite config.toml", boom)

    assert exc_info.value.phase == "rewrite config.toml"
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "simulated underlying failure" in str(exc_info.value.__cause__)


def test_run_phase_passes_through_success(migrate_mod):
    """On success, _run_phase returns the callable's value untouched."""
    assert migrate_mod._run_phase("noop", lambda: {"a": 1}) == {"a": 1}


def test_run_migration_reports_failing_phase(migrate_mod, monkeypatch, tmp_path):
    """A failure in any single phase must surface as MigrationError with that
    phase's name — the user must know which step broke."""
    def fail_snapshot(_backup_dir):
        raise OSError("disk full")

    monkeypatch.setattr(migrate_mod, "stop_daemon", lambda: None)
    monkeypatch.setattr(migrate_mod, "_snapshot_tool_roots", fail_snapshot)

    with pytest.raises(migrate_mod.MigrationError) as exc_info:
        migrate_mod.run_migration(tmp_path / "backup")

    assert exc_info.value.phase == "snapshot tool roots"
    assert isinstance(exc_info.value.__cause__, OSError)


def test_detection_aborts_on_transient_state_read_error(
    migrate_mod,
    monkeypatch,
    tmp_path,
):
    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(migrate_mod, "STATE_FILE", state_file)
    monkeypatch.setattr(migrate_mod, "CONFIG_FILE", tmp_path / "config.toml")

    original_read_text = Path.read_text

    def flaky_read_text(self, *args, **kwargs):
        if self == state_file:
            raise OSError("simulated lock contention")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)

    with pytest.raises(migrate_mod.MigrationDetectionError):
        migrate_mod.detect_pre_v04_fix_state()


def test_main_exits_without_detection_when_migration_lock_is_held(
    migrate_mod,
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(migrate_mod, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(sys, "argv", ["migrate_v0.4.py", "--yes"])

    def fail_if_called():
        raise AssertionError("detection should not run while lock is held")

    monkeypatch.setattr(migrate_mod, "detect_pre_v04_fix_state", fail_if_called)

    with migrate_mod.MigrationFileLock(migrate_mod._migration_lock_path()):
        assert migrate_mod.main() == 2

    captured = capsys.readouterr()
    assert "another migration appears to be running" in captured.err
