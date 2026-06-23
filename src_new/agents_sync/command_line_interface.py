"""The command-line interface (S22c/S23e): ``run`` the daemon, ``prune`` the archive,
or ``export`` / ``import`` the customization library, mapping outcomes to the distinct
exit codes (NFR-10, US-07).

``main`` loads the runtime config — a configuration defect fails closed with
``EXIT_CONFIG_FAILURE`` (US-07 AC-7) — then dispatches: ``run`` drives the poll loop and
returns its exit code; ``prune`` runs one archive GC; ``export``/``import`` drive
``portable_library`` against the configured state directory. A runtime I/O failure or a
``PortableLibraryError`` (a non-writable export AC-4, a malformed import AC-9, or a refused
displacement) maps to ``EXIT_RUNTIME_FAILURE``. ``import`` previews first and refuses to
displace a local artifact unless ``--force`` is given (AC-18).
``home``/``env``/``daemon_runner`` are injectable so the exit-code matrix is testable
without the real home directory or the blocking loop.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from agents_sync.artifact_archive import prune_archive
from agents_sync.poll_daemon import watch
from agents_sync.portable_library import (
    ImportPreview,
    PortableLibraryError,
    export_library,
    import_library,
    preview_import,
)
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
    daemon_runner: Callable[[RuntimeConfig], int] = run_daemon,
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
        return _dispatch(args, config, daemon_runner)
    except (OSError, PortableLibraryError) as error:
        _LOGGER.error("runtime failure: %s", error)
        return EXIT_RUNTIME_FAILURE


def _dispatch(
    args: argparse.Namespace, config: RuntimeConfig, daemon_runner: Callable[[RuntimeConfig], int]
) -> int:
    if args.command == "prune":
        return _prune(config)
    if args.command == "export":
        return _export(config, args.file)
    if args.command == "import":
        return _import(config, args.file, force=args.force)
    return daemon_runner(config)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agents_sync")
    parser.add_argument(
        "--config", type=Path, default=None, help="path to the config TOML (default: per-OS)"
    )
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("run", help="run the sync daemon (the default)")
    subcommands.add_parser("prune", help="run one archive garbage-collection pass")
    export_parser = subcommands.add_parser(
        "export", help="export the customization library to a file"
    )
    export_parser.add_argument("file", type=Path, help="destination export file")
    import_parser = subcommands.add_parser(
        "import", help="import a customization library from a file"
    )
    import_parser.add_argument("file", type=Path, help="source export file")
    import_parser.add_argument(
        "--force", action="store_true", help="allow displacing local artifacts"
    )
    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "run"
    return args


def _prune(config: RuntimeConfig) -> int:
    _gc_once(config.state_path.parent)
    return EXIT_OK


def _export(config: RuntimeConfig, export_path: Path) -> int:
    """Write the customization library export, then report what shipped (US-12 AC-1)."""
    report = export_library(
        config.state_path.parent, export_path, secret_policy=config.secret_policy
    )
    _LOGGER.info(
        "library export: %d artifact(s) -> %s (contains_secret_literals=%s)",
        report.artifact_count,
        report.export_path,
        report.contains_secret_literals,
    )
    return EXIT_OK


def _import(config: RuntimeConfig, import_path: Path, *, force: bool) -> int:
    """Preview the import (AC-18), refuse to displace a local without ``force``, else import
    and report (US-12 AC-5/AC-6/AC-7)."""
    state_dir = config.state_path.parent
    # preview_import and import_library each re-plan from scratch by design: the preview
    # must be honest before any write (AC-18), and import_library re-validates and re-guards
    # the displacement at write time — the double read is defense-in-depth, not an oversight.
    preview = preview_import(state_dir, import_path, secret_policy=config.secret_policy)
    _log_preview(preview)
    if preview.requires_force and not force:
        _LOGGER.error(
            "library import would displace %d local artifact(s): %s -- rerun with --force",
            len(preview.displaced_local_ids),
            list(preview.displaced_local_ids),
        )
        return EXIT_RUNTIME_FAILURE
    report = import_library(state_dir, import_path, secret_policy=config.secret_policy, force=force)
    _LOGGER.info(
        "library import: accepted=%d skipped=%d skipped_secret=%d",
        len(report.accepted),
        len(report.skipped),
        len(report.skipped_secret),
    )
    return EXIT_OK


def _log_preview(preview: ImportPreview) -> None:
    """Enumerate the merges and displacements before any write (AC-18 preview honesty)."""
    for imported_id, local_id in preview.merges:
        _LOGGER.info(
            "library import will merge %s onto local %s (same slug)", imported_id, local_id
        )
    if preview.displaced_local_ids:
        _LOGGER.info(
            "library import will displace local artifact(s): %s", list(preview.displaced_local_ids)
        )


def _gc_once(state_dir: Path) -> None:
    report = prune_archive(state_dir)
    _LOGGER.info(
        "archive GC: scanned %d, deleted %d, reclaimed %d bytes",
        report.scanned,
        report.deleted,
        report.bytes_reclaimed,
    )
