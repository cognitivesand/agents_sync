from __future__ import annotations

import argparse
import logging
import os
import tomllib
from pathlib import Path
from typing import Any, Literal, TypedDict

from agents_sync.mcp_secret_policy import (
    ALLOWED_SECRET_POLICIES,
    normalize_secret_policy,
)


class AgentsSyncConfig(TypedDict, total=False):
    """Shape of the merged config dict after ``merged_config``.

    Documents the keys ``Syncer`` and its collaborators consume. Used as a
    hint at function boundaries (``dict[str, Any]`` stays in place for
    interior code that constructs / mutates the dict, since TypedDicts do
    not compose well with ``dict.update`` and our config-loading is union-
    based by design).
    """

    poll_interval_seconds: float
    state_path: str
    # Claude
    claude_agents_dir: str
    claude_commands_dir: str
    claude_skills_dir: str
    claude_rules_dir: str
    claude_mcp_servers_file: str
    # Codex
    codex_agents_dir: str
    codex_prompts_dir: str
    codex_skills_dir: str
    codex_rules_dir: str
    codex_config_file: str
    # Cursor
    cursor_agents_dir: str
    cursor_commands_dir: str
    cursor_skills_dir: str
    cursor_rules_dir: str
    cursor_mcp_servers_file: str
    cursor_enabled: bool
    # Antigravity
    antigravity_skills_dir: str
    antigravity_enabled: bool
    # Gemini CLI
    gemini_cli_agents_dir: str
    gemini_cli_commands_dir: str
    gemini_cli_skills_dir: str
    gemini_cli_rules_dir: str
    gemini_cli_settings_file: str
    gemini_cli_enabled: bool
    # Copilot
    copilot_enabled: bool
    copilot_cli_enabled: bool
    copilot_vscode_user_profile_enabled: bool
    copilot_cli_agents_dir: str
    copilot_cli_skills_dir: str
    copilot_cli_mcp_config_file: str
    copilot_vscode_user_agents_dir: str | None
    copilot_vscode_user_instructions_dir: str | None
    copilot_vscode_user_prompts_dir: str | None
    copilot_vscode_user_mcp_file: str | None
    # opencode
    opencode_agents_dir: str
    opencode_commands_dir: str
    opencode_skills_dir: str
    opencode_rules_dir: str
    opencode_config_file: str
    opencode_enabled: bool
    # Cross-cutting
    secret_policy: Literal["secrets_refused", "secrets_accepted"]
    import_collision_strategy: Literal["skip", "mtime_wins", "overwrite"]


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
    cursor_root = home_dir / ".cursor"
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
        "cursor_agents_dir": str(cursor_root / "agents"),
        "cursor_skills_dir": str(cursor_root / "skills"),
        "cursor_rules_dir": str(cursor_root / "rules"),
        "cursor_commands_dir": str(cursor_root / "commands"),
        "cursor_mcp_servers_file": str(cursor_root / "mcp.json"),
        "cursor_enabled": True,
        # Antigravity uses the open SKILL.md spec under ~/.gemini/antigravity/skills/
        # on every OS (the home_dir / "$USERPROFILE%" join is uniform — Path
        # handles the per-OS separator). Set antigravity_enabled=False to skip
        # registration entirely.
        "antigravity_skills_dir": str(home_dir / ".gemini" / "antigravity" / "skills"),
        "antigravity_enabled": True,
        "gemini_cli_agents_dir": str(home_dir / ".gemini" / "agents"),
        "gemini_cli_commands_dir": str(home_dir / ".gemini" / "commands"),
        "gemini_cli_skills_dir": str(home_dir / ".gemini" / "skills"),
        "gemini_cli_rules_dir": str(home_dir / ".gemini"),
        "gemini_cli_settings_file": str(home_dir / ".gemini" / "settings.json"),
        "gemini_cli_enabled": True,
        "opencode_agents_dir": str(opencode_root / "agents"),
        "opencode_commands_dir": str(opencode_root / "commands"),
        "opencode_skills_dir": str(opencode_root / "skills"),
        "opencode_rules_dir": str(opencode_root),
        "opencode_config_file": str(opencode_root / "opencode.json"),
        "opencode_enabled": True,
        "copilot_enabled": True,
        "copilot_cli_enabled": True,
        "copilot_vscode_user_profile_enabled": True,
        "copilot_cli_agents_dir": str(home_dir / ".copilot" / "agents"),
        "copilot_cli_skills_dir": str(home_dir / ".copilot" / "skills"),
        "copilot_cli_mcp_config_file": str(home_dir / ".copilot" / "mcp-config.json"),
        "copilot_vscode_user_agents_dir": None,
        "copilot_vscode_user_instructions_dir": None,
        "copilot_vscode_user_prompts_dir": None,
        "copilot_vscode_user_mcp_file": None,
        "import_collision_strategy": "mtime_wins",
        "secret_policy": "secrets_refused",
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
    ("cursor_agents_dir", "cursor_agents_dir"),
    ("cursor_skills_dir", "cursor_skills_dir"),
    ("cursor_rules_dir", "cursor_rules_dir"),
    ("cursor_commands_dir", "cursor_commands_dir"),
    ("cursor_mcp_servers_file", "cursor_mcp_servers_file"),
    ("cursor_enabled", "cursor_enabled"),
    ("antigravity_skills_dir", "antigravity_skills_dir"),
    ("antigravity_enabled", "antigravity_enabled"),
    ("gemini_cli_agents_dir", "gemini_cli_agents_dir"),
    ("gemini_cli_commands_dir", "gemini_cli_commands_dir"),
    ("gemini_cli_skills_dir", "gemini_cli_skills_dir"),
    ("gemini_cli_rules_dir", "gemini_cli_rules_dir"),
    ("gemini_cli_settings_file", "gemini_cli_settings_file"),
    ("gemini_cli_enabled", "gemini_cli_enabled"),
    ("opencode_agents_dir", "opencode_agents_dir"),
    ("opencode_commands_dir", "opencode_commands_dir"),
    ("opencode_skills_dir", "opencode_skills_dir"),
    ("opencode_rules_dir", "opencode_rules_dir"),
    ("opencode_config_file", "opencode_config_file"),
    ("opencode_enabled", "opencode_enabled"),
    ("copilot_enabled", "copilot_enabled"),
    ("copilot_cli_enabled", "copilot_cli_enabled"),
    ("copilot_vscode_user_profile_enabled", "copilot_vscode_user_profile_enabled"),
    ("copilot_cli_agents_dir", "copilot_cli_agents_dir"),
    ("copilot_cli_skills_dir", "copilot_cli_skills_dir"),
    ("copilot_cli_mcp_config_file", "copilot_cli_mcp_config_file"),
    ("copilot_vscode_user_agents_dir", "copilot_vscode_user_agents_dir"),
    ("copilot_vscode_user_instructions_dir", "copilot_vscode_user_instructions_dir"),
    ("copilot_vscode_user_prompts_dir", "copilot_vscode_user_prompts_dir"),
    ("copilot_vscode_user_mcp_file", "copilot_vscode_user_mcp_file"),
    # Two argparse attributes map to the same merged-config key — the
    # canonical ``secret_policy`` and the deprecated alias
    # ``mcp_server_secret_policy``. ``merged_config`` resolves the
    # collision by preferring the canonical attribute when both are set
    # and logging a DEPRECATION-WARNING for the alias.
    ("secret_policy", "secret_policy"),
    ("mcp_server_secret_policy", "secret_policy"),
    ("state_path", "state_path"),
)


def merged_config(args: argparse.Namespace) -> dict[str, Any]:
    config = dict(DEFAULTS)
    config_path = args.config if args.config is not None else default_config_path()
    config.update(load_external_config(config_path))
    for arg_attr, config_key in _ARG_TO_CONFIG_KEY:
        maybe_set(config, config_key, getattr(args, arg_attr, None))

    # Compat shim (1/2): if an external config file or CLI flag used the
    # deprecated key ``mcp_server_secret_policy``, copy its value into the
    # canonical ``secret_policy`` slot (only when no explicit canonical
    # value was provided), and emit one DEPRECATION-WARNING at startup.
    # The deprecated key is then discarded so downstream code never sees
    # it. To be removed in v0.6.
    legacy_value = config.pop("mcp_server_secret_policy", None)
    if legacy_value is not None:
        if config.get("secret_policy") == DEFAULTS["secret_policy"]:
            config["secret_policy"] = legacy_value
        logging.warning(
            "DEPRECATED config key 'mcp_server_secret_policy' — use 'secret_policy' instead",
        )

    # Compat shim (2/2): normalize the policy value through
    # ``normalize_secret_policy`` so the old spellings (refuse/redact/permissive)
    # become the new ones (secrets_refused/secrets_accepted). The shim logs
    # the deprecation once at startup; downstream code sees only the new
    # spelling.
    raw_policy = config.get("secret_policy", DEFAULTS["secret_policy"])
    config["secret_policy"] = normalize_secret_policy(
        str(raw_policy), source="config", warn_deprecated=True,
    )
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

OPTIONAL_PATH_KEYS: tuple[str, ...] = (
    "claude_mcp_servers_file",
    "codex_config_file",
    "cursor_agents_dir",
    "cursor_skills_dir",
    "cursor_rules_dir",
    "cursor_commands_dir",
    "cursor_mcp_servers_file",
    "gemini_cli_settings_file",
    "opencode_config_file",
    "copilot_cli_agents_dir",
    "copilot_cli_skills_dir",
    "copilot_cli_mcp_config_file",
    "copilot_vscode_user_agents_dir",
    "copilot_vscode_user_instructions_dir",
    "copilot_vscode_user_prompts_dir",
    "copilot_vscode_user_mcp_file",
)

OPTIONAL_BOOL_KEYS: tuple[str, ...] = (
    "antigravity_enabled",
    "cursor_enabled",
    "gemini_cli_enabled",
    "opencode_enabled",
    "copilot_enabled",
    "copilot_cli_enabled",
    "copilot_vscode_user_profile_enabled",
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

    for key in OPTIONAL_PATH_KEYS:
        if key not in config or config[key] is None:
            continue
        if not isinstance(config[key], (str, Path)):
            raise ConfigError(f"{key} must be a path string when set")

    for key in OPTIONAL_BOOL_KEYS:
        if key in config and not isinstance(config[key], bool):
            raise ConfigError(f"{key} must be a boolean")

    strategy = config.get("import_collision_strategy", "mtime_wins")
    if strategy not in {"skip", "mtime_wins", "overwrite"}:
        raise ConfigError(
            f"import_collision_strategy must be skip|mtime_wins|overwrite, "
            f"got {strategy!r}"
        )

    # secret_policy validation: accept either the canonical key or the
    # deprecated alias, accept either new or old value spellings, normalize
    # silently here (the per-startup deprecation was already logged by
    # merged_config). Reject anything outside the union.
    raw_policy = config.get("secret_policy")
    if raw_policy is None:
        raw_policy = config.get("mcp_server_secret_policy", "secrets_refused")
    try:
        normalized = normalize_secret_policy(
            str(raw_policy), source="validate_config", warn_deprecated=False,
        )
    except ValueError as exc:
        raise ConfigError(
            "secret_policy must be "
            f"{'|'.join(sorted(ALLOWED_SECRET_POLICIES))}, got {raw_policy!r}"
        ) from exc
    config["secret_policy"] = normalized

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
