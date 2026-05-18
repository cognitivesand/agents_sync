from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from agents_sync.agentic_tool_spec import default_agentic_tools
from agents_sync.config import ConfigError, merged_config, validate_config
from agents_sync.daemon import watch
from agents_sync.portable_archive import (
    PortableArchiveError,
    export_to_zip,
    import_from_zip,
)
from agents_sync.sync import Syncer


# v0.1 install paths. Phase 4 declines to auto-migrate; if either of these
# exists we emit a clear error and exit so the user can clean up.
_LEGACY_PATHS = [
    Path.home() / ".config/claude-codex-sync",
    Path.home() / ".local/state/claude-codex-sync",
]
if os.name == "nt":
    _LEGACY_PATHS.extend([
        Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        / "claude-codex-sync",
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        / "claude-codex-sync",
    ])


def build_parser() -> argparse.ArgumentParser:
    """Top-level parser owns every shared flag. Subparsers add only their
    own positional + flags so argparse does not silently clobber the
    parent's values with subparser defaults during subcommand parsing.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Continuous sync of Claude Code, Codex, Antigravity, "
            "and opencode customizations."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Optional config TOML (default: platform-specific user config path).",
    )
    parser.add_argument("--interval", type=float, help="Polling interval in seconds.")
    parser.add_argument("--claude-agents-dir", type=str)
    parser.add_argument(
        "--claude-commands-dir",
        type=str,
        help="Claude Code user slash-command root. Defaults to ~/.claude/commands.",
    )
    parser.add_argument("--claude-skills-dir", type=str)
    parser.add_argument(
        "--claude-rules-dir",
        type=str,
        help="Claude Code rules root. Defaults to ~/.claude, containing CLAUDE.md.",
    )
    parser.add_argument("--codex-agents-dir", type=str)
    parser.add_argument(
        "--codex-prompts-dir",
        type=str,
        help="Codex CLI custom prompts root. Defaults to ~/.codex/prompts.",
    )
    parser.add_argument("--codex-skills-dir", type=str)
    parser.add_argument(
        "--codex-rules-dir",
        type=str,
        help="Codex rules root. Defaults to ~/.codex, containing AGENTS.md.",
    )
    parser.add_argument(
        "--antigravity-skills-dir",
        type=str,
        help="Antigravity (Google) skills root. Defaults to ~/.gemini/antigravity/skills/.",
    )
    parser.add_argument(
        "--antigravity-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Toggle Antigravity participation in the sync (default: enabled).",
    )
    parser.add_argument(
        "--opencode-agents-dir",
        type=str,
        help="opencode agents root. Defaults to ~/.config/opencode/agents on POSIX and APPDATA\\opencode\\agents on Windows.",
    )
    parser.add_argument(
        "--opencode-commands-dir",
        type=str,
        help="opencode slash-command root. Defaults to ~/.config/opencode/commands on POSIX and APPDATA\\opencode\\commands on Windows.",
    )
    parser.add_argument(
        "--opencode-skills-dir",
        type=str,
        help="opencode skills root. Defaults to ~/.config/opencode/skills on POSIX and APPDATA\\opencode\\skills on Windows.",
    )
    parser.add_argument(
        "--opencode-rules-dir",
        type=str,
        help="opencode rules root. Defaults to ~/.config/opencode on POSIX and APPDATA\\opencode on Windows, containing AGENTS.md.",
    )
    parser.add_argument(
        "--opencode-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Toggle opencode participation in the sync (default: enabled).",
    )
    parser.add_argument("--state-path", type=str)
    parser.add_argument("--verbose", action="store_true")

    subparsers = parser.add_subparsers(dest="command", metavar="{export,import}")

    export_parser = subparsers.add_parser(
        "export",
        help="Write a portable library snapshot zip from the local canonical store.",
    )
    export_parser.add_argument(
        "output", type=Path, help="Destination zip file path."
    )

    import_parser = subparsers.add_parser(
        "import",
        help="Restore a portable library snapshot zip into the local install.",
    )
    import_parser.add_argument(
        "input", type=Path, help="Source zip file path."
    )
    import_parser.add_argument(
        "--collision-strategy",
        choices=["skip", "mtime_wins", "overwrite"],
        default=None,
        help=(
            "Override the config's import_collision_strategy for this "
            "invocation only."
        ),
    )

    return parser


def _check_legacy_install() -> int | None:
    """Return a non-zero exit code if a v0.1 install must be removed first."""
    found = [p for p in _LEGACY_PATHS if p.exists()]
    if not found:
        return None
    logging.error(
        "Legacy claude-codex-sync v0.1 install detected at:\n  %s\n"
        "agents-sync v0.2 does not migrate v0.1 state. Remove or move these paths,"
        " then run agents-sync again.",
        "\n  ".join(str(p) for p in found),
    )
    return 2


def _run_export(args: argparse.Namespace, config: dict) -> int:
    from agents_sync.config import expand_path

    state_dir = expand_path(config["state_path"]).parent
    try:
        report = export_to_zip(state_dir, args.output)
    except OSError:
        logging.exception("Export failed")
        return 1
    logging.info(
        "Exported %d artifact(s) to %s", report.artifact_count, report.archive_path
    )
    return 0


def _run_import(args: argparse.Namespace, config: dict) -> int:
    from agents_sync.config import expand_path

    state_dir = expand_path(config["state_path"]).parent
    strategy = args.collision_strategy or config["import_collision_strategy"]
    agentic_tools = default_agentic_tools()
    try:
        report = import_from_zip(
            state_dir,
            args.input,
            strategy=strategy,
            config=config,
            agentic_tools=agentic_tools,
        )
    except PortableArchiveError:
        logging.exception("Import rejected")
        return 1
    except OSError:
        logging.exception("Import failed")
        return 1
    logging.info(
        "Import complete: accepted=%d skipped=%d archived_local=%d",
        len(report.accepted), len(report.skipped), len(report.archived_local),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    legacy_exit = _check_legacy_install()
    if legacy_exit is not None:
        return legacy_exit

    config = merged_config(args)
    try:
        validate_config(config)
    except ConfigError:
        logging.exception("Invalid agents-sync configuration")
        return 2

    if args.command == "export":
        return _run_export(args, config)
    if args.command == "import":
        return _run_import(args, config)

    syncer = Syncer(config)
    watch(syncer, float(config["poll_interval_seconds"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
