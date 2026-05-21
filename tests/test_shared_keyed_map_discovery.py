"""Discovery + collision tests for SharedKeyedMapLayout artifacts.

Covers Phase 2 of the v0.5 mcp_server implementation plan:
- DiscoveryWalker walks slots inside the shared file, not file paths.
- Two slots in the same shared file are distinct artifacts (no
  collision on file path alone).
- Two adapters writing to the same (shared_file, slot_key) collide.
- state_owner_for_path is slot-aware: matching on path alone is not
  enough to claim ownership of a slot.
- Missing shared file / missing map key are recoverable absences,
  not errors.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    SharedKeyedMapLayout,
)
from agents_sync.canonical import new_pair_id
from agents_sync.shared_keyed_map_io import read_slots
from agents_sync.state import AgenticToolState, CustomizationArtifactState
from agents_sync.sync import Syncer


_PAIR_ID_KEY = "pair_id"


def _slot_parse(
    text: str,
    prior_canonical: dict[str, Any] | None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Parse one MCP slot. The slot text is JSON for a single server."""
    obj = json.loads(text or "{}")
    return {
        "kind": "mcp_server",
        "name": obj.get("name", ""),
        "pair_id": obj.get(_PAIR_ID_KEY),
        **{k: v for k, v in obj.items() if k != _PAIR_ID_KEY},
    }


def _slot_render(canonical: dict[str, Any], prior_text: str | None) -> str:
    out: dict[str, Any] = {}
    for key, value in canonical.items():
        if key in {"kind"}:
            continue
        if key == "pair_id":
            if value is not None:
                out[_PAIR_ID_KEY] = value
            continue
        out[key] = value
    return json.dumps(out, indent=2) + "\n"


def _slot_extract_pair_id(text: str) -> str | None:
    try:
        obj = json.loads(text or "{}")
    except json.JSONDecodeError:
        return None
    pair_id = obj.get(_PAIR_ID_KEY)
    return pair_id if isinstance(pair_id, str) else None


def _mcp_spec(tool_name: str, shared_path_key: str) -> AgenticToolSpec:
    return AgenticToolSpec(
        name=tool_name,
        config_dir_keys={"mcp_server": shared_path_key},
        io={
            "mcp_server": CustomizationTypeIO(
                parse=_slot_parse,
                render=_slot_render,
                extract_pair_id=_slot_extract_pair_id,
                file_layout=SharedKeyedMapLayout(
                    shared_path_config_key=shared_path_key,
                    map_key_path=("mcpServers",),
                    key_field="name",
                ),
            ),
        },
    )


def _baseline_config(tmp_path: Path) -> dict[str, Any]:
    state_dir = tmp_path / "state"
    return {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "unused-ca"),
        "claude_commands_dir": str(tmp_path / "unused-cc"),
        "claude_skills_dir": str(tmp_path / "unused-cs"),
        "claude_rules_dir": str(tmp_path / "unused-cr"),
        "codex_agents_dir": str(tmp_path / "unused-xa"),
        "codex_prompts_dir": str(tmp_path / "unused-xp"),
        "codex_skills_dir": str(tmp_path / "unused-xs"),
        "codex_rules_dir": str(tmp_path / "unused-xr"),
        "antigravity_skills_dir": str(tmp_path / "unused-as"),
        "opencode_agents_dir": str(tmp_path / "unused-oa"),
        "opencode_commands_dir": str(tmp_path / "unused-oc"),
        "opencode_skills_dir": str(tmp_path / "unused-os"),
        "opencode_rules_dir": str(tmp_path / "unused-or"),
    }


def _mcp_syncer(
    tmp_path: Path,
    *,
    alpha_file: Path | None = None,
    beta_file: Path | None = None,
) -> Syncer:
    config = _baseline_config(tmp_path)
    config["alpha_mcp_file"] = str(alpha_file or tmp_path / "alpha-mcp.json")
    config["beta_mcp_file"] = str(beta_file or tmp_path / "beta-mcp.json")
    return Syncer(
        config,
        agentic_tools={
            "alpha": _mcp_spec("alpha", "alpha_mcp_file"),
            "beta": _mcp_spec("beta", "beta_mcp_file"),
        },
    )


def test_discover_enumerates_slots_under_map_key_path(tmp_path: Path):
    shared_file = tmp_path / "alpha-mcp.json"
    shared_file.write_text(json.dumps({
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
            "filesystem": {"name": "filesystem", "command": "fs-mcp"},
        },
        "theme": "dark",
    }))
    syncer = _mcp_syncer(tmp_path, alpha_file=shared_file)

    syncer.tool_status.refresh()
    pairs, blocked = syncer.discovery.discover(state={})

    assert blocked == set()
    assert len(pairs) == 2
    discovered_slots = {
        next(iter(info.agentic_tools.values())).slot
        for info in pairs.values()
    }
    assert discovered_slots == {"github", "filesystem"}


def test_discover_skips_missing_shared_file(tmp_path: Path):
    """First-boot before the user has any MCP server is a silent skip,
    not an error."""
    syncer = _mcp_syncer(tmp_path)

    syncer.tool_status.refresh()
    pairs, blocked = syncer.discovery.discover(state={})

    assert pairs == {}
    assert blocked == set()


def test_discover_skips_when_map_key_absent(tmp_path: Path):
    """File exists but the configured map key is not in it. Treat as
    'no slots to sync' rather than an error."""
    shared_file = tmp_path / "alpha-mcp.json"
    shared_file.write_text(json.dumps({"theme": "dark"}))
    syncer = _mcp_syncer(tmp_path, alpha_file=shared_file)

    syncer.tool_status.refresh()
    pairs, blocked = syncer.discovery.discover(state={})

    assert pairs == {}
    assert blocked == set()


def test_state_owner_for_path_is_slot_aware(tmp_path: Path):
    """Two slots in the same shared file are owned by distinct
    pair_ids; state_owner_for_path must require slot equality."""
    shared_file = tmp_path / "alpha-mcp.json"
    shared_file.write_text("{}")
    syncer = _mcp_syncer(tmp_path, alpha_file=shared_file)

    state = {
        "p1": CustomizationArtifactState(
            kind="mcp_server",
            agentic_tools={
                "alpha": AgenticToolState(
                    path=shared_file,
                    slot="github",
                ),
            },
        ),
    }

    owner_same_slot = syncer.discovery.state_owner_for_path(
        shared_file, state, slot="github",
    )
    owner_different_slot = syncer.discovery.state_owner_for_path(
        shared_file, state, slot="filesystem",
    )
    owner_no_slot = syncer.discovery.state_owner_for_path(
        shared_file, state, slot=None,
    )

    assert owner_same_slot == "p1"
    assert owner_different_slot is None
    assert owner_no_slot is None


def test_two_slots_in_same_file_do_not_collide(tmp_path: Path):
    """``alpha-mcp.json`` has two slots; ``beta-mcp.json`` is empty.
    Adopting either alpha slot to beta plans a target inside
    ``beta-mcp.json`` — those targets share the file but have
    different slot keys, so they must not collide with each other."""
    alpha_file = tmp_path / "alpha-mcp.json"
    alpha_file.write_text(json.dumps({
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
            "filesystem": {"name": "filesystem", "command": "fs-mcp"},
        },
    }))
    syncer = _mcp_syncer(tmp_path, alpha_file=alpha_file)

    syncer.tool_status.refresh()
    pairs, _ = syncer.discovery.discover(state={})
    blocked = syncer.discovery.block_target_collisions(pairs, state={})

    assert blocked == set()
    assert len(pairs) == 2
