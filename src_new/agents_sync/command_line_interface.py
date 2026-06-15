"""The command-line interface (S22c): ``run`` the daemon or ``prune`` the archive,
mapping outcomes to the distinct exit codes (NFR-10, US-07).

``main`` loads the runtime config — a configuration defect fails closed with
``EXIT_CONFIG_FAILURE`` (US-07 AC-7) — then dispatches: ``run`` drives the poll
loop and returns its exit code (``EXIT_OK`` clean, ``EXIT_RUNTIME_FAILURE`` on the
failure budget); ``prune`` runs one archive GC. A runtime I/O failure maps to
``EXIT_RUNTIME_FAILURE``. ``home``/``env``/``run_daemon`` are injectable so the
exit-code matrix is testable without the real home directory or the blocking loop.
Export/import subcommands arrive with ``portable_library`` (S23).
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from agents_sync.artifact_archive import prune_archive
from agents_sync.poll_daemon import watch
from agents_sync.runtime_config import (
    EXIT_CONFIG_FAILURE,
    EXIT_OK,
    EXIT_RUNTIME_FAILURE,
    ConfigurationError,
    RuntimeConfig,
    load_runtime_config,
)
from agents_sync.sync_once import make_periodic_poll

_LOGGER = logging.getLogger(__name__)


def run_daemon(config: RuntimeConfig) -> int:
    """Drive the poll loop for ``config`` until a clean stop or the failure budget."""
    state_dir = config.state_path.parent
    return watch(
        make_periodic_poll(config),
        poll_interval_seconds=config.poll_interval_seconds,
        run_gc=lambda: _gc_once(state_dir),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    run_daemon: Callable[[RuntimeConfig], int] = run_daemon,
) -> int:
    """Parse ``argv``, load the config, dispatch the subcommand, and return an exit code."""
    args = _parse_args(argv)
    resolved_env = dict(os.environ) if env is None else dict(env)
    resolved_home = Path.home() if home is None else home
    try:
        config = load_runtime_config(
            args.config, os_name=os.name, env=resolved_env, home=resolved_home
        )
    except ConfigurationError as error:
        _LOGGER.error("configuration error: %s", error)
        return EXIT_CONFIG_FAILURE
    try:
        if args.command == "prune":
            return _prune(config)
        return run_daemon(config)
    except OSError as error:
        _LOGGER.error("runtime failure: %s", error)
        return EXIT_RUNTIME_FAILURE


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agents_sync")
    parser.add_argument(
        "--config", type=Path, default=None, help="path to the config TOML (default: per-OS)"
    )
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("run", help="run the sync daemon (the default)")
    subcommands.add_parser("prune", help="run one archive garbage-collection pass")
    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "run"
    return args


def _prune(config: RuntimeConfig) -> int:
    _gc_once(config.state_path.parent)
    return EXIT_OK


def _gc_once(state_dir: Path) -> None:
    report = prune_archive(state_dir)
    _LOGGER.info(
        "archive GC: scanned %d, deleted %d, reclaimed %d bytes",
        report.scanned,
        report.deleted,
        report.bytes_reclaimed,
    )
