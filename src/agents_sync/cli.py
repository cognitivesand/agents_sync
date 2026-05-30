from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import default_agentic_tools
from agents_sync.config import ConfigError, expand_path, merged_config, validate_config
from agents_sync.daemon import watch
from agents_sync.portable_archive import (
    PortableArchiveError,
    export_to_zip,
    import_from_zip,
    preview_import,
)
from agents_sync.sync import Syncer

# v0.1 install paths. Phase 4 declines to auto-migrate; if either of these
# exists we emit a clear error and exit so the user can clean up.
_LEGACY_PATHS = [
    Path.home() / ".config/claude-codex-sync",
    Path.home() / ".local/state/claude-codex-sync",
]
if os.name == "nt":
    _LEGACY_PATHS.extend(
        [
            Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
            / "claude-codex-sync",
            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
            / "claude-codex-sync",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    """Top-level parser owns every shared flag. Subparsers add only their
    own positional + flags so argparse does not silently clobber the
    parent's values with subparser defaults during subcommand parsing.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Continuous sync of Claude Code, Codex, Copilot, Cursor, "
            "Gemini CLI, Antigravity, and opencode customizations."
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
    parser.add_argument(
        "--claude-mcp-servers-file",
        type=str,
        help="Claude Code user MCP config file. Defaults to ~/.claude.json.",
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
        "--codex-config-file",
        type=str,
        help="Codex config.toml file containing [mcp_servers.*]. Defaults to ~/.codex/config.toml.",
    )
    parser.add_argument(
        "--cursor-agents-dir",
        type=str,
        help="Cursor user subagents root. Defaults to ~/.cursor/agents.",
    )
    parser.add_argument(
        "--cursor-skills-dir",
        type=str,
        help="Cursor Agent Skills root. Defaults to ~/.cursor/skills.",
    )
    parser.add_argument(
        "--cursor-rules-dir",
        type=str,
        help="Cursor user rules root. Defaults to ~/.cursor/rules.",
    )
    parser.add_argument(
        "--cursor-commands-dir",
        type=str,
        help="Cursor slash-command root. Defaults to ~/.cursor/commands.",
    )
    parser.add_argument(
        "--cursor-mcp-servers-file",
        type=str,
        help="Cursor MCP config file. Defaults to ~/.cursor/mcp.json.",
    )
    parser.add_argument(
        "--cursor-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Toggle Cursor participation in the sync (default: enabled).",
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
        "--gemini-cli-agents-dir",
        type=str,
        help="Gemini CLI agents root. Defaults to ~/.gemini/agents.",
    )
    parser.add_argument(
        "--gemini-cli-commands-dir",
        type=str,
        help="Gemini CLI slash-command root. Defaults to ~/.gemini/commands.",
    )
    parser.add_argument(
        "--gemini-cli-skills-dir",
        type=str,
        help="Gemini CLI skills root. Defaults to ~/.gemini/skills.",
    )
    parser.add_argument(
        "--gemini-cli-rules-dir",
        type=str,
        help="Gemini CLI rules root. Defaults to ~/.gemini, containing GEMINI.md.",
    )
    parser.add_argument(
        "--gemini-cli-settings-file",
        type=str,
        help="Gemini CLI settings.json file containing mcpServers. "
        "Defaults to ~/.gemini/settings.json.",
    )
    parser.add_argument(
        "--gemini-cli-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Toggle Gemini CLI participation in the sync (default: enabled).",
    )
    parser.add_argument(
        "--opencode-agents-dir",
        type=str,
        help="opencode agents root. Defaults to ~/.config/opencode/agents on POSIX "
        "and APPDATA\\opencode\\agents on Windows.",
    )
    parser.add_argument(
        "--opencode-commands-dir",
        type=str,
        help="opencode slash-command root. Defaults to ~/.config/opencode/commands on POSIX "
        "and APPDATA\\opencode\\commands on Windows.",
    )
    parser.add_argument(
        "--opencode-skills-dir",
        type=str,
        help="opencode skills root. Defaults to ~/.config/opencode/skills on POSIX "
        "and APPDATA\\opencode\\skills on Windows.",
    )
    parser.add_argument(
        "--opencode-rules-dir",
        type=str,
        help="opencode rules root. Defaults to ~/.config/opencode on POSIX "
        "and APPDATA\\opencode on Windows, containing AGENTS.md.",
    )
    parser.add_argument(
        "--opencode-config-file",
        type=str,
        help="opencode JSON/JSONC config file containing mcp. "
        "Defaults to opencode.json in the opencode config root.",
    )
    parser.add_argument(
        "--opencode-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Toggle opencode participation in the sync (default: enabled).",
    )
    parser.add_argument(
        "--copilot-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Toggle GitHub Copilot participation in the sync (default: enabled).",
    )
    parser.add_argument(
        "--copilot-cli-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Toggle the Copilot CLI/user-home half (agents and skills).",
    )
    parser.add_argument(
        "--copilot-vscode-user-profile-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Toggle the VS Code user-profile Copilot half (instructions and prompts).",
    )
    parser.add_argument(
        "--copilot-cli-agents-dir",
        type=str,
        help="GitHub Copilot user agents root. Defaults to ~/.copilot/agents.",
    )
    parser.add_argument(
        "--copilot-cli-skills-dir",
        type=str,
        help="GitHub Copilot Agent Skills root. Defaults to ~/.copilot/skills.",
    )
    parser.add_argument(
        "--copilot-cli-mcp-config-file",
        type=str,
        help="GitHub Copilot CLI MCP config file reserved for v0.5 MCP support.",
    )
    parser.add_argument(
        "--copilot-vscode-user-agents-dir",
        type=str,
        help="VS Code user-profile Copilot agents root. Reserved for multi-root agent support.",
    )
    parser.add_argument(
        "--copilot-vscode-user-instructions-dir",
        type=str,
        help="VS Code user-profile Copilot instructions root for *.instructions.md.",
    )
    parser.add_argument(
        "--copilot-vscode-user-prompts-dir",
        type=str,
        help="VS Code user-profile Copilot prompts root for *.prompt.md.",
    )
    parser.add_argument(
        "--copilot-vscode-user-mcp-file",
        type=str,
        help="VS Code user-profile MCP file reserved for v0.5 MCP support.",
    )
    parser.add_argument(
        "--secret-policy",
        choices=["secrets_refused", "secrets_accepted"],
        default=None,
        help=(
            "How to handle customization_artifacts that carry literal "
            "secret material (default: secrets_refused). "
            "Applied at every artifact-egress boundary (parse, customization "
            "library export, customization library import)."
        ),
    )
    # Deprecated alias for the canonical --secret-policy flag. Accepts the
    # old value spellings (refuse / redact / permissive) plus the new ones,
    # so existing scripts keep working while the deprecation warning
    # surfaces in the logs. To be removed in v0.6.
    parser.add_argument(
        "--mcp-server-secret-policy",
        choices=[
            "refuse",
            "redact",
            "permissive",
            "secrets_refused",
            "secrets_accepted",
        ],
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--state-path", type=str)
    parser.add_argument("--verbose", action="store_true")

    subparsers = parser.add_subparsers(dest="command", metavar="{export,import}")

    export_parser = subparsers.add_parser(
        "export",
        help="Write a portable library snapshot zip from the local canonical store.",
    )
    export_parser.add_argument("output", type=Path, help="Destination zip file path.")

    import_parser = subparsers.add_parser(
        "import",
        help="Restore a portable library snapshot zip into the local install.",
    )
    import_parser.add_argument("input", type=Path, help="Source zip file path.")
    import_parser.add_argument(
        "--collision-strategy",
        choices=["skip", "mtime_wins", "overwrite"],
        default=None,
        help=("Override the config's import_collision_strategy for this invocation only."),
    )
    import_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Required for the 'overwrite' strategy (and for 'mtime_wins' "
            "when the snapshot would replace local pairs). Without --force "
            "those strategies abort and print the pairs they would overwrite "
            "so you can confirm before running again with --force."
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


def _run_export(args: argparse.Namespace, config: dict[str, Any]) -> int:

    state_dir = expand_path(config["state_path"]).parent
    secret_policy = str(
        config.get("secret_policy") or config.get("mcp_server_secret_policy") or "secrets_refused"
    )
    try:
        report = export_to_zip(state_dir, args.output, secret_policy=secret_policy)
    except OSError:
        logging.exception("Export failed")
        return 1
    logging.info("Exported %d artifact(s) to %s", report.artifact_count, report.archive_path)
    if report.skipped_secret_artifacts:
        logging.info(
            "Skipped %d secret-bearing artifact(s) under secret_policy=secrets_refused: %s",
            len(report.skipped_secret_artifacts),
            report.skipped_secret_artifacts,
        )
    if report.contains_secret_literals:
        logging.info(
            "Export carries literal secret material (manifest.contains_secret_literals=true)."
        )
    return 0


def _run_import(args: argparse.Namespace, config: dict[str, Any]) -> int:

    state_dir = expand_path(config["state_path"]).parent
    strategy = args.collision_strategy or config["import_collision_strategy"]
    force = bool(getattr(args, "force", False))

    # Audit slice 08 · CQ-07: ``mtime_wins`` and ``overwrite`` can silently
    # replace local user content. Compute a preview of the displacements
    # before committing to disk; require --force if any local pair would
    # be overwritten so the user has a chance to confirm.
    try:
        would_overwrite, _would_skip = preview_import(
            state_dir,
            args.input,
            strategy=strategy,
        )
    except PortableArchiveError:
        logging.exception("Import rejected")
        return 1
    except OSError:
        logging.exception("Import failed")
        return 1
    if would_overwrite and not force:
        logging.error(
            "Import would overwrite %d local pair(s) under strategy=%s. "
            "Re-run with --force to proceed. Affected pair_ids: %s",
            len(would_overwrite),
            strategy,
            ", ".join(sorted(set(would_overwrite))),
        )
        return 2

    agentic_tools = default_agentic_tools(config)
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
        len(report.accepted),
        len(report.skipped),
        len(report.archived_local),
    )
    if report.skipped_secret_artifacts:
        logging.info(
            "Skipped %d secret-bearing artifact(s) under secret_policy=secrets_refused: %s",
            len(report.skipped_secret_artifacts),
            report.skipped_secret_artifacts,
        )
    # Canonical-only import only writes canonicals + state stubs; project them now
    # so the one-shot CLI import takes effect without the daemon running.
    Syncer(config).sync_once()
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
    return watch(syncer, float(config["poll_interval_seconds"]))


if __name__ == "__main__":
    raise SystemExit(main())
