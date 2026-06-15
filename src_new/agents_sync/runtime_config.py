"""Runtime configuration: per-OS default paths, TOML load/merge, fail-closed
validation, and the distinct process exit codes (NFR-10, US-07 AC-7).

``load_runtime_config`` resolves each tool recipe's ``DefaultLocation`` into the
``config_key -> Path`` map the read phase consumes, overlays the user's TOML
config over those defaults, and validates the result. Any configuration defect
raises ``ConfigurationError``; the daemon and CLI map that to
``EXIT_CONFIG_FAILURE`` at the process boundary. Platform-path resolution is pure
(no I/O) so it is testable per OS without a real filesystem; the only side effect
is creating the state directory.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents_sync.secret_policy import ALLOWED_SECRET_POLICIES, SECRET_POLICY_REFUSED
from agents_sync.tools.agentic_tools_registry import ALL_TOOL_DEFINITIONS
from agents_sync.tools.tool_definition import PathAnchor, ToolDefinition
from agents_sync.translation import KNOWN_DIALECTS

# Distinct process exit codes (NFR-10): a service manager applies the right
# restart policy per outcome. A configuration failure is a bug in the config file
# (do not restart blindly); a runtime failure is transient (restart is sensible).
EXIT_OK = 0
EXIT_RUNTIME_FAILURE = 1
EXIT_CONFIG_FAILURE = 2

DEFAULT_POLL_INTERVAL_SECONDS = 2.0
_APP_DIR_NAME = "agents-sync"
_CONFIG_TABLE_KEY = "agents-sync"


class ConfigurationError(ValueError):
    """A configuration defect that makes the daemon unsafe to start (US-07 AC-7)."""


@dataclass(frozen=True)
class RuntimeConfig:
    """The validated configuration the daemon and CLI run from."""

    poll_interval_seconds: float
    state_path: Path
    secret_policy: str
    resolved_paths: Mapping[str, Path]


# --- platform anchors (pure) ----------------------------------------------------------

def _windows_root(
    env_var: str, profile_parts: tuple[str, ...], env: Mapping[str, str], home: Path
) -> Path:
    raw = env.get(env_var)
    return Path(raw) if raw else home.joinpath(*profile_parts)


def _config_root(*, os_name: str, env: Mapping[str, str], home: Path) -> Path:
    if os_name == "nt":
        return _windows_root("APPDATA", ("AppData", "Roaming"), env, home)
    return home / ".config"


def _resolve_anchor(
    anchor: PathAnchor, *, os_name: str, env: Mapping[str, str], home: Path
) -> Path:
    if anchor is PathAnchor.HOME:
        return home
    return _config_root(os_name=os_name, env=env, home=home)


def default_config_path(*, os_name: str, env: Mapping[str, str], home: Path) -> Path:
    return _config_root(os_name=os_name, env=env, home=home) / _APP_DIR_NAME / "config.toml"


def default_state_path(*, os_name: str, env: Mapping[str, str], home: Path) -> Path:
    if os_name == "nt":
        root = _windows_root("LOCALAPPDATA", ("AppData", "Local"), env, home)
        return root / _APP_DIR_NAME / "state" / "state.json"
    return home / ".local" / "state" / _APP_DIR_NAME / "state.json"


def resolve_default_paths(
    tool_definitions: Iterable[ToolDefinition],
    *,
    os_name: str,
    env: Mapping[str, str],
    home: Path,
) -> dict[str, Path]:
    """The ``config_key -> default Path`` map. A recipe with no built-in default
    (``default_location is None``) is omitted — that surface is absent unless the
    config file names a path for it."""
    paths: dict[str, Path] = {}
    for definition in tool_definitions:
        for recipe in definition.surface_recipes:
            location = recipe.default_location
            if location is None:
                continue
            anchor = _resolve_anchor(location.anchor, os_name=os_name, env=env, home=home)
            paths[recipe.config_key] = anchor.joinpath(*location.relative_parts)
    return paths


# --- load + validate ------------------------------------------------------------------

def load_runtime_config(
    config_path: Path | None,
    *,
    os_name: str,
    env: Mapping[str, str],
    home: Path,
    tool_definitions: Iterable[ToolDefinition] = ALL_TOOL_DEFINITIONS,
) -> RuntimeConfig:
    """Load, merge, and validate the runtime configuration, or fail closed.

    ``config_path=None`` discovers the per-OS default config file. A missing file
    means defaults only. Every defect raises ``ConfigurationError`` naming it."""
    definitions = tuple(tool_definitions)
    _reject_invalid_registry(definitions)

    file_path = config_path or default_config_path(os_name=os_name, env=env, home=home)
    overrides = _load_config_file(file_path)

    resolved = resolve_default_paths(definitions, os_name=os_name, env=env, home=home)
    _apply_path_overrides(resolved, overrides, definitions)

    return RuntimeConfig(
        poll_interval_seconds=_validated_poll_interval(overrides),
        state_path=_prepared_state_path(overrides, os_name=os_name, env=env, home=home),
        secret_policy=_validated_secret_policy(overrides),
        resolved_paths=resolved,
    )


def _reject_invalid_registry(definitions: tuple[ToolDefinition, ...]) -> None:
    seen: set[str] = set()
    for definition in definitions:
        if definition.name in seen:
            raise ConfigurationError(f"duplicate tool name: {definition.name!r}")
        seen.add(definition.name)
        for recipe in definition.surface_recipes:
            dialect = recipe.surface_format.dialect
            if dialect not in KNOWN_DIALECTS:
                raise ConfigurationError(
                    f"tool {definition.name!r} names unregistered dialect {dialect!r} "
                    f"(known: {sorted(KNOWN_DIALECTS)})"
                )


def _load_config_file(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    try:
        # utf-8-sig tolerates a BOM that Windows-authored TOML can carry.
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise ConfigurationError(f"malformed TOML in config file {path}: {exc}") from exc
    table = data.get(_CONFIG_TABLE_KEY, data)
    if not isinstance(table, Mapping):
        raise ConfigurationError(f"config table [{_CONFIG_TABLE_KEY}] must be a table in {path}")
    return table


def _apply_path_overrides(
    resolved: dict[str, Path], overrides: Mapping[str, Any], definitions: tuple[ToolDefinition, ...]
) -> None:
    known_keys = {recipe.config_key for d in definitions for recipe in d.surface_recipes}
    for config_key in known_keys:
        value = overrides.get(config_key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ConfigurationError(f"{config_key} must be a path string, got {value!r}")
        resolved[config_key] = Path(value).expanduser()


def _validated_poll_interval(overrides: Mapping[str, Any]) -> float:
    raw = overrides.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS)
    try:
        interval = float(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"poll_interval_seconds must be a number, got {raw!r}") from exc
    if interval <= 0:
        raise ConfigurationError(f"poll_interval_seconds must be positive, got {interval}")
    return interval


def _validated_secret_policy(overrides: Mapping[str, Any]) -> str:
    policy = overrides.get("secret_policy", SECRET_POLICY_REFUSED)
    if policy not in ALLOWED_SECRET_POLICIES:
        raise ConfigurationError(
            f"secret_policy must be one of {sorted(ALLOWED_SECRET_POLICIES)}, got {policy!r}"
        )
    return str(policy)


def _prepared_state_path(
    overrides: Mapping[str, Any], *, os_name: str, env: Mapping[str, str], home: Path
) -> Path:
    raw = overrides.get("state_path")
    if raw is None:
        state_path = default_state_path(os_name=os_name, env=env, home=home)
    elif isinstance(raw, str):
        state_path = Path(raw).expanduser()
    else:
        raise ConfigurationError(f"state_path must be a path string, got {raw!r}")
    parent = state_path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigurationError(f"state_path parent cannot be created: {parent}") from exc
    return state_path
