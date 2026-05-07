from __future__ import annotations

import argparse
import os
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


class ConfigError(ValueError):
    """Raised when daemon configuration is unsafe to run."""


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


def validate_config(config: dict[str, Any]) -> None:
    """Fail closed before the daemon can interpret missing roots as deletions."""
    try:
        interval = float(config["poll_interval_seconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError("poll_interval_seconds must be a number") from exc
    if interval <= 0:
        raise ConfigError("poll_interval_seconds must be positive")

    for key in (
        "claude_agents_dir",
        "claude_skills_dir",
        "codex_agents_dir",
        "codex_skills_dir",
    ):
        root = expand_path(config[key])
        if not root.exists():
            raise ConfigError(f"{key} does not exist: {root}")
        if not root.is_dir():
            raise ConfigError(f"{key} is not a directory: {root}")
        try:
            next(root.iterdir(), None)
        except OSError as exc:
            raise ConfigError(f"{key} is not readable: {root}") from exc
        if not os.access(root, os.W_OK):
            raise ConfigError(f"{key} is not writable: {root}")

    state_path = expand_path(config["state_path"])
    state_parent = state_path.parent
    try:
        state_parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"state_path parent cannot be created: {state_parent}") from exc
    if not state_parent.is_dir():
        raise ConfigError(f"state_path parent is not a directory: {state_parent}")
    if not os.access(state_parent, os.W_OK):
        raise ConfigError(f"state_path parent is not writable: {state_parent}")
