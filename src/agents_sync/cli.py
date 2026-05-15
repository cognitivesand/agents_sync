from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from agents_sync.config import ConfigError, merged_config, validate_config
from agents_sync.daemon import watch
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
    parser.add_argument("--claude-skills-dir", type=str)
    parser.add_argument("--codex-agents-dir", type=str)
    parser.add_argument("--codex-skills-dir", type=str)
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
        "--opencode-skills-dir",
        type=str,
        help="opencode skills root. Defaults to ~/.config/opencode/skills on POSIX and APPDATA\\opencode\\skills on Windows.",
    )
    parser.add_argument(
        "--opencode-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Toggle opencode participation in the sync (default: enabled).",
    )
    parser.add_argument("--state-path", type=str)
    parser.add_argument("--verbose", action="store_true")
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
    syncer = Syncer(config)
    watch(syncer, float(config["poll_interval_seconds"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
