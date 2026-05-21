"""Shared test helpers extracted from individual test modules.

Phase 2.7 of the audit remediation collected duplicated test scaffolding —
syncer factory, baseline config builder, skill-document builders, mtime
setters, state readers — that had drifted across half a dozen test files.
Centralising them here means a new tool root (e.g. v0.6 ``foo_dir``) is a
one-line addition rather than a six-place edit.

Public API:

- :func:`make_config` — produce a config dict for ``Syncer`` over a given
  ``tmp_path``. Caller can toggle optional tools (Antigravity / opencode)
  and override individual keys for parametric tests.
- :func:`make_syncer` — instantiate a ``Syncer`` from a fresh tmp tree.
- :func:`skill_md` — produce a SKILL.md / agent .md body with optional
  description and pair_id.
- :func:`set_artifact_mtime` — set both file and parent-directory mtime
  in one call (required so first-boot reconciliation sees a stable wall
  clock).
- :func:`read_state` / :func:`list_state` — load ``state.json`` from a
  Syncer's state dir as a dict / list of entries.
- :func:`skill_with_macos_metadata` — materialise a SKILL.md plus the
  Finder/AppleDouble sidecars that adapters must ignore.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agents_sync.sync import Syncer


# Two-letter tmp_path directory names are the historic shorthand for
# ``<tool>_<kind>_dir``. The mapping is exposed so a test can reach for
# ``CONFIG_DIRS["claude_agents_dir"]`` instead of remembering the cipher.
CONFIG_DIRS: dict[str, str] = {
    "claude_agents_dir": "ca",
    "claude_commands_dir": "cc",
    "claude_skills_dir": "cs",
    "claude_rules_dir": "cr",
    "codex_agents_dir": "xa",
    "codex_prompts_dir": "xp",
    "codex_skills_dir": "xs",
    "codex_rules_dir": "xr",
    "antigravity_skills_dir": "as",
    "opencode_agents_dir": "oa",
    "opencode_commands_dir": "oc",
    "opencode_skills_dir": "os",
    "opencode_rules_dir": "or",
}


def make_config(
    tmp_path: Path,
    *,
    antigravity_enabled: bool = True,
    opencode_enabled: bool = True,
    **overrides: Any,
) -> dict[str, Any]:
    """Return a Syncer-ready config dict over ``tmp_path``.

    Pre-creates each tool-root directory and emits the canonical file
    paths for shared-keyed-map artifacts (mcp_server). Optional flags
    let a test exercise the same setup with selected tools disabled
    without copying the entire 16-key dict.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    for sub in CONFIG_DIRS.values():
        (tmp_path / sub).mkdir(exist_ok=True)
    config: dict[str, Any] = {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "antigravity_enabled": antigravity_enabled,
        "opencode_enabled": opencode_enabled,
        "claude_mcp_servers_file": str(tmp_path / "claude-mcp.json"),
        "codex_config_file": str(tmp_path / "codex-config.toml"),
        "opencode_config_file": str(tmp_path / "opencode.json"),
    }
    for config_key, dir_name in CONFIG_DIRS.items():
        config[config_key] = str(tmp_path / dir_name)
    config.update(overrides)
    return config


def make_syncer(
    tmp_path: Path,
    *,
    antigravity_enabled: bool = True,
    opencode_enabled: bool = True,
    **overrides: Any,
) -> Syncer:
    """Instantiate a Syncer from a tmp_path-rooted config."""
    return Syncer(
        make_config(
            tmp_path,
            antigravity_enabled=antigravity_enabled,
            opencode_enabled=opencode_enabled,
            **overrides,
        )
    )


def skill_md(
    name: str, description: str = "x", body: str = "body",
    *, pair_id: str | None = None,
) -> str:
    """Return a minimal SKILL.md / agent .md document."""
    pair_id_line = f"pair_id: {pair_id}\n" if pair_id else ""
    return f"---\n{pair_id_line}name: {name}\ndescription: {description}\n---\n{body}\n"


def set_artifact_mtime(skill_dir: Path, value: float) -> None:
    """Set mtime on SKILL.md *and* its directory in one call.

    First-boot reconciliation sometimes reads the directory's mtime as a
    tiebreaker — keeping the file and the dir in sync stops the test
    from depending on filesystem mtime-update order.
    """
    os.utime(skill_dir / "SKILL.md", (value, value))
    os.utime(skill_dir, (value, value))


def read_state(syncer: Syncer) -> dict[str, Any]:
    """Load ``state.json`` from a Syncer's state_dir as a raw dict."""
    state_path = syncer.state_dir / "state.json"
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text())


def list_state(syncer: Syncer) -> dict[str, Any]:
    """Same as :func:`read_state` but pre-extracts ``customization_artifacts``."""
    return read_state(syncer)


def skill_with_macos_metadata(skill_dir: Path) -> Path:
    """Materialise a SKILL.md plus the macOS sidecar files that the
    adoption / archive paths must ignore. Returns the skill directory."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\n---\nbody\n", encoding="utf-8",
    )
    (skill_dir / ".DS_Store").write_text("finder metadata", encoding="utf-8")
    (skill_dir / "._asset.png").write_text(
        "appledouble metadata", encoding="utf-8",
    )
    return skill_dir
