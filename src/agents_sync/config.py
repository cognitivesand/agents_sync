from __future__ import annotations

import argparse
import tomllib
from pathlib import Path
from typing import Any


DEFAULTS: dict[str, Any] = {
    "poll_interval_seconds": 2.0,
    "state_path": "~/.local/state/agents-sync/state.json",
    "claude_agents_dir": "~/.claude/agents",
    "claude_skills_dir": "~/.claude/skills",
    "codex_agents_dir": "~/.codex/agents",
    "codex_skills_dir": "~/.agents/skills",
}


def expand_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def load_external_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    with path.open("rb") as file:
        data = tomllib.load(file)
    return data.get("agents-sync", data)


def maybe_set(config: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        config[key] = value


def merged_config(args: argparse.Namespace) -> dict[str, Any]:
    config = dict(DEFAULTS)
    config.update(load_external_config(args.config))
    maybe_set(config, "poll_interval_seconds", args.interval)
    maybe_set(config, "claude_agents_dir", args.claude_agents_dir)
    maybe_set(config, "claude_skills_dir", args.claude_skills_dir)
    maybe_set(config, "codex_agents_dir", args.codex_agents_dir)
    maybe_set(config, "codex_skills_dir", args.codex_skills_dir)
    maybe_set(config, "state_path", args.state_path)
    return config
