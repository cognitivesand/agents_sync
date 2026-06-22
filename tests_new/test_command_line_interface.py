"""``command_line_interface.main``: argparse dispatch + the exit-code matrix (S22c/S23e).

``main`` loads the runtime config (a defect → ``EXIT_CONFIG_FAILURE``), dispatches
``run`` (→ the daemon, whose exit code it returns), ``prune`` (→ the archive GC), or the
S23e library commands ``export`` / ``import`` (→ ``portable_library``), and maps a runtime
I/O or portable-library failure to ``EXIT_RUNTIME_FAILURE`` (NFR-10, US-07). ``home``,
``env``, and ``run_daemon`` are injectable boundary seams so the matrix is tested without
touching the real home directory or running the blocking daemon loop. The library commands
drive a real state directory (set via a ``--config`` TOML) and a real export file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.canonical_store import load_canonical, save_canonical
from agents_sync.command_line_interface import main
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.runtime_config import (
    EXIT_CONFIG_FAILURE,
    EXIT_OK,
    EXIT_RUNTIME_FAILURE,
    RuntimeConfig,
)

_ID = "66666666-6666-4666-8666-666666666666"


def _fail_with_oserror(config: RuntimeConfig) -> int:
    raise OSError("archive volume vanished")


def _config_file(tmp_path: Path, dirname: str) -> tuple[Path, Path]:
    """A ``--config`` TOML pointing the state directory at ``tmp_path/dirname``."""
    state_dir = tmp_path / dirname
    config_path = tmp_path / f"{dirname}.toml"
    config_path.write_text(
        f'[agents-sync]\nstate_path = "{(state_dir / "state.json").as_posix()}"\n'
    )
    return config_path, state_dir


def _agent(artifact_id: str, body: str = "body\n") -> CanonicalDocument:
    return CanonicalDocument(artifact_id=artifact_id, kind="agent", name="reviewer", body=body)


def _exported_via_cli(tmp_path: Path, document: CanonicalDocument, last_modified: float) -> Path:
    """Seed a source state and export it through ``main`` — the export fixture for imports."""
    src_config, src_state = _config_file(tmp_path, "src")
    save_canonical(src_state, document, clock=lambda: last_modified)
    export_file = tmp_path / "lib.zip"
    assert main(
        ["--config", str(src_config), "export", str(export_file)], home=tmp_path, env={}
    ) == EXIT_OK
    return export_file


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


def test_export_subcommand_writes_a_library_file(tmp_path: Path) -> None:
    config_path, state_dir = _config_file(tmp_path, "src")
    save_canonical(state_dir, _agent(_ID), clock=lambda: 1000.0)
    export_file = tmp_path / "lib.zip"

    code = main(["--config", str(config_path), "export", str(export_file)], home=tmp_path, env={})

    assert code == EXIT_OK
    assert export_file.exists()


def test_export_to_an_unwritable_path_returns_runtime_failure(tmp_path: Path) -> None:
    config_path, state_dir = _config_file(tmp_path, "src")
    save_canonical(state_dir, _agent(_ID), clock=lambda: 1000.0)
    missing_parent = tmp_path / "missing" / "lib.zip"  # parent dir absent → not writable (AC-4)

    code = main(
        ["--config", str(config_path), "export", str(missing_parent)], home=tmp_path, env={}
    )

    assert code == EXIT_RUNTIME_FAILURE
    assert not missing_parent.exists()


def test_import_subcommand_adopts_canonicals(tmp_path: Path) -> None:
    export_file = _exported_via_cli(tmp_path, _agent(_ID), 1000.0)
    dst_config, dst_state = _config_file(tmp_path, "dst")

    code = main(["--config", str(dst_config), "import", str(export_file)], home=tmp_path, env={})

    assert code == EXIT_OK
    assert isinstance(load_canonical(dst_state, _ID), CanonicalDocument)  # adopted (AC-5)


def test_import_without_force_refuses_to_displace_a_local(tmp_path: Path) -> None:
    export_file = _exported_via_cli(tmp_path, _agent(_ID, body="imported\n"), 2000.0)
    dst_config, dst_state = _config_file(tmp_path, "dst")
    save_canonical(dst_state, _agent(_ID, body="local\n"), clock=lambda: 1000.0)

    code = main(["--config", str(dst_config), "import", str(export_file)], home=tmp_path, env={})

    assert code == EXIT_RUNTIME_FAILURE  # would displace a local without --force (AC-18)
    preserved = load_canonical(dst_state, _ID)
    assert isinstance(preserved, CanonicalDocument)
    assert preserved.body == "local\n"  # nothing written


def test_import_with_force_displaces_a_local(tmp_path: Path) -> None:
    export_file = _exported_via_cli(tmp_path, _agent(_ID, body="imported\n"), 2000.0)
    dst_config, dst_state = _config_file(tmp_path, "dst")
    save_canonical(dst_state, _agent(_ID, body="local\n"), clock=lambda: 1000.0)

    code = main(
        ["--config", str(dst_config), "import", "--force", str(export_file)], home=tmp_path, env={}
    )

    assert code == EXIT_OK
    displaced = load_canonical(dst_state, _ID)
    assert isinstance(displaced, CanonicalDocument)
    assert displaced.body == "imported\n"  # displaced under --force (AC-18)
