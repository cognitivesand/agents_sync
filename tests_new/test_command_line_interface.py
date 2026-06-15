"""S22c — ``command_line_interface.main``: argparse dispatch + the exit-code matrix.

``main`` loads the runtime config (a defect → ``EXIT_CONFIG_FAILURE``), dispatches
``run`` (→ the daemon, whose exit code it returns) or ``prune`` (→ the archive GC),
and maps a runtime I/O failure to ``EXIT_RUNTIME_FAILURE`` (NFR-10, US-07). ``home``,
``env``, and ``run_daemon`` are injectable boundary seams so the matrix is tested
without touching the real home directory or running the blocking daemon loop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.command_line_interface import main
from agents_sync.runtime_config import (
    EXIT_CONFIG_FAILURE,
    EXIT_OK,
    EXIT_RUNTIME_FAILURE,
    RuntimeConfig,
)


def _fail_with_oserror(config: RuntimeConfig) -> int:
    raise OSError("archive volume vanished")


def test_config_error_returns_exit_config_failure(tmp_path: Path) -> None:
    bad_config = tmp_path / "bad.toml"
    bad_config.write_text("[agents-sync]\npoll_interval_seconds = 0\n")

    code = main(["--config", str(bad_config)], home=tmp_path, env={})

    assert code == EXIT_CONFIG_FAILURE


def test_prune_returns_exit_ok(tmp_path: Path) -> None:
    code = main(["prune"], home=tmp_path, env={})

    assert code == EXIT_OK


@pytest.mark.parametrize("daemon_code", [EXIT_OK, EXIT_RUNTIME_FAILURE])
def test_run_returns_the_daemon_exit_code(tmp_path: Path, daemon_code: int) -> None:
    code = main(["run"], home=tmp_path, env={}, run_daemon=lambda config: daemon_code)

    assert code == daemon_code


def test_runtime_oserror_returns_exit_runtime_failure(tmp_path: Path) -> None:
    code = main(["run"], home=tmp_path, env={}, run_daemon=_fail_with_oserror)

    assert code == EXIT_RUNTIME_FAILURE


def test_the_three_outcomes_map_to_distinct_codes(tmp_path: Path) -> None:
    bad_config = tmp_path / "bad.toml"
    bad_config.write_text("[agents-sync]\npoll_interval_seconds = 0\n")

    config_failure = main(["--config", str(bad_config)], home=tmp_path, env={})
    normal = main(["prune"], home=tmp_path, env={})
    runtime_failure = main(["run"], home=tmp_path, env={}, run_daemon=_fail_with_oserror)

    assert (config_failure, normal, runtime_failure) == (
        EXIT_CONFIG_FAILURE,
        EXIT_OK,
        EXIT_RUNTIME_FAILURE,
    )
    assert len({config_failure, normal, runtime_failure}) == 3
