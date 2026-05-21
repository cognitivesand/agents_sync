from __future__ import annotations

import argparse
import os
import tomllib
from pathlib import Path
from typing import Any


def _home_dir(home: Path | None = None) -> Path:
    return home if home is not None else Path.home()


def _windows_data_dir(
    env_var: str,
    fallback_suffix: tuple[str, ...],
    *,
    env: dict[str, str] | None,
    home: Path | None,
) -> Path:
    env_map = os.environ if env is None else env
    raw = env_map.get(env_var)
    if raw:
        return Path(raw)
    return _home_dir(home).joinpath(*fallback_suffix)


def default_config_path(
    *,
    os_name: str | None = None,
    env: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    platform_name = os.name if os_name is None else os_name
    if platform_name == "nt":
        root = _windows_data_dir(
            "APPDATA",
            ("AppData", "Roaming"),
            env=env,
            home=home,
        )
        return root / "agents-sync" / "config.toml"
    return _home_dir(home) / ".config" / "agents-sync" / "config.toml"


def default_state_path(
    *,
    os_name: str | None = None,
    env: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    platform_name = os.name if os_name is None else os_name
    if platform_name == "nt":
        root = _windows_data_dir(
            "LOCALAPPDATA",
            ("AppData", "Local"),
            env=env,
            home=home,
        )
        return root / "agents-sync" / "state" / "state.json"
    return _home_dir(home) / ".local" / "state" / "agents-sync" / "state.json"


def platform_defaults(
    *,
    os_name: str | None = None,
    env: dict[str, str] | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    platform_name = os.name if os_name is None else os_name
    home_dir = _home_dir(home)
    if platform_name == "nt":
        opencode_root = _windows_data_dir(
            "APPDATA",
            ("AppData", "Roaming"),
            env=env,
            home=home,
        ) / "opencode"
    else:
        opencode_root = home_dir / ".config" / "opencode"
    return {
        "poll_interval_seconds": 2.0,
        "state_path": str(default_state_path(os_name=os_name, env=env, home=home)),
        "claude_agents_dir": str(home_dir / ".claude" / "agents"),
        "claude_commands_dir": str(home_dir / ".claude" / "commands"),
        "claude_skills_dir": str(home_dir / ".claude" / "skills"),
        "claude_rules_dir": str(home_dir / ".claude"),
        "claude_mcp_servers_file": str(home_dir / ".claude.json"),
        "codex_agents_dir": str(home_dir / ".codex" / "agents"),
        "codex_prompts_dir": str(home_dir / ".codex" / "prompts"),
        "codex_skills_dir": str(home_dir / ".codex" / "skills"),
        "codex_rules_dir": str(home_dir / ".codex"),
        "codex_config_file": str(home_dir / ".codex" / "config.toml"),
        # Antigravity uses the open SKILL.md spec under ~/.gemini/antigravity/skills/
        # on every OS (the home_dir / "$USERPROFILE%" join is uniform — Path
        # handles the per-OS separator). Set antigravity_enabled=False to skip
        # registration entirely.
        "antigravity_skills_dir": str(home_dir / ".gemini" / "antigravity" / "skills"),
        "antigravity_enabled": True,
        "opencode_agents_dir": str(opencode_root / "agents"),
        "opencode_commands_dir": str(opencode_root / "commands"),
        "opencode_skills_dir": str(opencode_root / "skills"),
        "opencode_rules_dir": str(opencode_root),
        "opencode_config_file": str(opencode_root / "opencode.json"),
        "opencode_enabled": True,
        "import_collision_strategy": "mtime_wins",
        "mcp_server_secret_policy": "refuse",
    }


DEFAULTS: dict[str, Any] = platform_defaults()


class ConfigError(ValueError):
    """Raised when daemon configuration is unsafe to run."""


def expand_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def load_external_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    # utf-8-sig tolerates a BOM that can appear in Windows-authored TOML files.
    text = path.read_text(encoding="utf-8-sig")
    data = tomllib.loads(text)
    return data.get("agents-sync", data)


def maybe_set(config: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        config[key] = value


# Maps each ``argparse`` attribute name to the merged-config key it writes
# into. Listed in registration order so a new CLI flag is a one-line
# addition (no four-place edit across the parser, this loop,
# ``validate_config``, and the test fixture). When the two names differ
# only by spelling (``interval`` -> ``poll_interval_seconds``,
# ``mcp_server_secret_policy`` -> same), the table makes the divergence
# explicit instead of buried in a ``maybe_set`` line.
_ARG_TO_CONFIG_KEY: tuple[tuple[str, str], ...] = (
    ("interval", "poll_interval_seconds"),
    ("claude_agents_dir", "claude_agents_dir"),
    ("claude_commands_dir", "claude_commands_dir"),
    ("claude_skills_dir", "claude_skills_dir"),
    ("claude_rules_dir", "claude_rules_dir"),
    ("claude_mcp_servers_file", "claude_mcp_servers_file"),
    ("codex_agents_dir", "codex_agents_dir"),
    ("codex_prompts_dir", "codex_prompts_dir"),
    ("codex_skills_dir", "codex_skills_dir"),
    ("codex_rules_dir", "codex_rules_dir"),
    ("codex_config_file", "codex_config_file"),
    ("antigravity_skills_dir", "antigravity_skills_dir"),
    ("antigravity_enabled", "antigravity_enabled"),
    ("opencode_agents_dir", "opencode_agents_dir"),
    ("opencode_commands_dir", "opencode_commands_dir"),
    ("opencode_skills_dir", "opencode_skills_dir"),
    ("opencode_rules_dir", "opencode_rules_dir"),
    ("opencode_config_file", "opencode_config_file"),
    ("opencode_enabled", "opencode_enabled"),
    ("mcp_server_secret_policy", "mcp_server_secret_policy"),
    ("state_path", "state_path"),
)


def merged_config(args: argparse.Namespace) -> dict[str, Any]:
    config = dict(DEFAULTS)
    config_path = args.config if args.config is not None else default_config_path()
    config.update(load_external_config(config_path))
    for arg_attr, config_key in _ARG_TO_CONFIG_KEY:
        maybe_set(config, config_key, getattr(args, arg_attr, None))
    return config


REQUIRED_DIR_KEYS: tuple[str, ...] = (
    "claude_agents_dir",
    "claude_commands_dir",
    "claude_skills_dir",
    "claude_rules_dir",
    "codex_agents_dir",
    "codex_prompts_dir",
    "codex_skills_dir",
    "codex_rules_dir",
    "antigravity_skills_dir",
    "opencode_agents_dir",
    "opencode_commands_dir",
    "opencode_skills_dir",
    "opencode_rules_dir",
)


def validate_config(config: dict[str, Any]) -> None:
    """Structural validation only.

    Per US-11 (graceful agentic_tool absence) and v0.4 plan §3, the
    existence / readability / writability of each agentic_tool's root is a
    *runtime* concern, not a startup concern: a missing root makes the tool
    `unavailable` for that poll (Syncer logs the transition once and continues)
    but does not abort the daemon. This rule is uniform across Claude, Codex,
    and Antigravity.

    This function still fails closed on:
      - missing or non-numeric `poll_interval_seconds`;
      - missing required directory keys (well-formed paths required);
      - inability to create / write the `state_path` parent (state must
        survive crashes).
    """
    try:
        interval = float(config["poll_interval_seconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError("poll_interval_seconds must be a number") from exc
    if interval <= 0:
        raise ConfigError("poll_interval_seconds must be positive")

    for key in REQUIRED_DIR_KEYS:
        if key not in config:
            raise ConfigError(f"missing required config key: {key}")
        if not isinstance(config[key], (str, Path)):
            raise ConfigError(f"{key} must be a path string")

    strategy = config.get("import_collision_strategy", "mtime_wins")
    if strategy not in {"skip", "mtime_wins", "overwrite"}:
        raise ConfigError(
            f"import_collision_strategy must be skip|mtime_wins|overwrite, "
            f"got {strategy!r}"
        )

    mcp_secret_policy = config.get("mcp_server_secret_policy", "refuse")
    if mcp_secret_policy not in {"refuse", "redact", "permissive"}:
        raise ConfigError(
            "mcp_server_secret_policy must be refuse|redact|permissive, "
            f"got {mcp_secret_policy!r}"
        )

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
