"""NFR-10: distinct process exit codes for normal termination, configuration
failure, and runtime failure.

The three codes are asserted together as one matrix so a future refactor cannot
silently collapse two of them into the same value. Each case drives the real
``cli.main`` entry point with a sandboxed ``--state-path`` under ``tmp_path`` so
nothing touches the developer's real home.

Mapping under test (cli.py): 0 = normal, 2 = configuration failure
(``validate_config`` / legacy-install / unconfirmed-overwrite), 1 = runtime
failure (export/import raised).
"""
from __future__ import annotations

from pathlib import Path

from agents_sync.cli import main


def test_normal_termination_returns_zero(tmp_path: Path) -> None:
    # `export` of an empty store is a complete, successful run that never
    # enters the daemon loop: it reads the (absent) canonical store and writes
    # a zero-artifact library zip.
    state_path = tmp_path / "state" / "state.json"
    out_zip = tmp_path / "library.zip"

    exit_code = main(["--state-path", str(state_path), "export", str(out_zip)])

    assert exit_code == 0
    assert out_zip.exists()


def test_configuration_failure_returns_two() -> None:
    # A non-positive poll interval fails validate_config (config.py: interval
    # must be positive); main() maps ConfigError to exit code 2 before any
    # sync work runs.
    exit_code = main(["--interval", "0"])

    assert exit_code == 2


def test_runtime_failure_returns_one(tmp_path: Path) -> None:
    # A well-formed config (valid state path) but a missing import archive is a
    # runtime failure: preview_import raises PortableArchiveError, which main()
    # maps to exit code 1.
    state_path = tmp_path / "state" / "state.json"
    missing_zip = tmp_path / "does-not-exist.zip"

    exit_code = main(["--state-path", str(state_path), "import", str(missing_zip)])

    assert exit_code == 1


def test_the_three_codes_are_distinct(tmp_path: Path) -> None:
    # Guard the *distinctness* property itself, independent of the concrete
    # values above, so a refactor that aliases two outcomes is caught here too.
    normal = main(
        ["--state-path", str(tmp_path / "s" / "state.json"), "export", str(tmp_path / "a.zip")]
    )
    config_failure = main(["--interval", "-1"])
    state_arg = str(tmp_path / "s" / "state.json")
    runtime_failure = main(
        ["--state-path", state_arg, "import", str(tmp_path / "missing.zip")]
    )

    assert len({normal, config_failure, runtime_failure}) == 3
