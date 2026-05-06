from __future__ import annotations

import argparse
import logging
from pathlib import Path

from agents_sync.config import merged_config
from agents_sync.daemon import watch
from agents_sync.sync import Syncer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync Claude Code agents and skills with Codex."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Run one sync then exit.")
    mode.add_argument("--watch", action="store_true", help="Continuously watch and sync.")
    parser.add_argument("--config", type=Path, help="Optional app config TOML.")
    parser.add_argument("--interval", type=float, help="Polling interval in seconds.")
    parser.add_argument(
        "--prune",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Remove generated outputs for deleted sources.",
    )
    parser.add_argument("--claude-agents-dir", type=str)
    parser.add_argument("--claude-skills-dir", type=str)
    parser.add_argument("--codex-agents-dir", type=str)
    parser.add_argument("--codex-skills-dir", type=str)
    parser.add_argument("--state-path", type=str)
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config = merged_config(args)
    syncer = Syncer(config)
    if args.watch:
        watch(syncer, float(config["poll_interval_seconds"]))
        return 0
    changed = syncer.sync_once()
    logging.info("Sync completed: %d changed item(s)", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
