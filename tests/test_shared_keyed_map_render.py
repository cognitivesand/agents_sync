"""End-to-end render coverage for SharedKeyedMapLayout artifacts.

Two synthetic adapters share the same map_key_path under different
shared files. The test exercises the full adoption + projection flow
through Syncer.sync_once and asserts:

- Slot is created in the target file, sibling slots and out-of-map
  top-level keys are preserved byte-for-byte.
- pair_id is injected into the source slot the first time round.
- Archive contains the prior slot text, not the whole shared file.
- State entries carry the slot key.

The synthetic adapter mirrors what an mcp_server adapter would look
like once Phase 5 (mcp_server_io + secret policy) lands.
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
from agents_sync.canonical import load_canonical
from agents_sync.state import load_state
from agents_sync.sync import Syncer

_PAIR_ID_KEY = "pair_id"


def _slot_parse(
    text: str,
    prior_canonical: dict[str, Any] | None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
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
        if key == "kind":
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


def _mcp_syncer(tmp_path: Path) -> Syncer:
    config = _baseline_config(tmp_path)
    config["alpha_mcp_file"] = str(tmp_path / "alpha-mcp.json")
    config["beta_mcp_file"] = str(tmp_path / "beta-mcp.json")
    return Syncer(
        config,
        agentic_tools={
            "alpha": _mcp_spec("alpha", "alpha_mcp_file"),
            "beta": _mcp_spec("beta", "beta_mcp_file"),
        },
    )


def test_adoption_projects_slot_and_preserves_siblings(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    beta_file = tmp_path / "beta-mcp.json"
    alpha_file.write_text(json.dumps({
        "mcpServers": {
            "filesystem": {"name": "filesystem", "command": "fs-mcp"},
            "github": {"name": "github", "command": "gh-mcp"},
        },
        "theme": "dark",
    }))

    result = syncer.sync_once(); changed = result.changed

    assert changed == 2  # two pairs adopted

    beta = json.loads(beta_file.read_text())
    assert set(beta["mcpServers"]) == {"filesystem", "github"}
    assert beta["mcpServers"]["github"]["command"] == "gh-mcp"
    assert beta["mcpServers"]["filesystem"]["command"] == "fs-mcp"

    # Alpha's siblings and out-of-map keys survive the adoption.
    alpha = json.loads(alpha_file.read_text())
    assert alpha["theme"] == "dark"
    assert set(alpha["mcpServers"]) == {"filesystem", "github"}


def test_pair_id_injected_into_source_slot(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    alpha_file.write_text(json.dumps({
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
        },
    }))

    syncer.sync_once()

    alpha = json.loads(alpha_file.read_text())
    assert "pair_id" in alpha["mcpServers"]["github"]
    beta_file = tmp_path / "beta-mcp.json"
    beta = json.loads(beta_file.read_text())
    assert (
        alpha["mcpServers"]["github"]["pair_id"]
        == beta["mcpServers"]["github"]["pair_id"]
    )


def test_state_carries_slot_field(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    alpha_file.write_text(json.dumps({
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
        },
    }))

    syncer.sync_once()

    state = load_state(syncer.state_dir)
    pair_id, entry = next(iter(state.items()))
    assert entry.kind == "mcp_server"
    assert set(entry.agentic_tools) == {"alpha", "beta"}
    for tool_name, tool_state in entry.agentic_tools.items():
        assert tool_state.slot == "github"

    canonical = load_canonical(syncer.state_dir, pair_id)
    assert canonical is not None
    assert canonical["name"] == "github"


def test_archive_contains_prior_slot_text_not_whole_file(tmp_path: Path):
    """Pair_id injection rewrites the source slot. The archive entry
    is the prior slot text alone (a few hundred bytes), never the
    whole shared file. The shared file's bytes outside the slot are
    not part of the archive."""
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    alpha_file.write_text(json.dumps({
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
            "filesystem": {"name": "filesystem", "command": "fs-mcp"},
        },
        "theme": "dark",
    }))

    syncer.sync_once()

    state = load_state(syncer.state_dir)
    pair_ids = list(state.keys())
    assert len(pair_ids) == 2
    for pair_id in pair_ids:
        archive_dir = syncer.state_dir / "archive" / pair_id / "alpha"
        assert archive_dir.exists()
        entries = list(archive_dir.iterdir())
        assert len(entries) == 1
        archived = entries[0].read_text()
        # Archived blob must be ONE slot's serialised content — not the
        # full shared file with all slots and "theme".
        archived_obj = json.loads(archived)
        assert "mcpServers" not in archived_obj
        assert "theme" not in archived_obj
        assert "name" in archived_obj


def test_removal_deletes_slot_preserving_siblings(tmp_path: Path):
    """Removing a slot from the source tool's shared file propagates as
    a slot delete (not a file delete) on the projection target. Sibling
    slots and out-of-map keys must survive on both sides."""
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    beta_file = tmp_path / "beta-mcp.json"
    alpha_file.write_text(json.dumps({
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
            "filesystem": {"name": "filesystem", "command": "fs-mcp"},
        },
        "theme": "dark",
    }))

    # First poll adopts both pairs into beta.
    syncer.sync_once()

    # User removes 'github' from alpha's shared file by hand.
    current = json.loads(alpha_file.read_text())
    del current["mcpServers"]["github"]
    alpha_file.write_text(json.dumps(current, indent=2) + "\n")

    syncer.sync_once()

    state = load_state(syncer.state_dir)
    surviving_slots = {
        next(iter(entry.agentic_tools.values())).slot
        for entry in state.values()
    }
    assert surviving_slots == {"filesystem"}, "github pair must be dropped"

    beta = json.loads(beta_file.read_text())
    assert set(beta["mcpServers"]) == {"filesystem"}
    alpha = json.loads(alpha_file.read_text())
    assert alpha["theme"] == "dark"
    assert set(alpha["mcpServers"]) == {"filesystem"}


def test_second_sync_does_not_re_archive(tmp_path: Path):
    """Once both tools carry the pair_id, the slot bytes match across
    polls. A no-op sync_once must not produce a fresh archive entry."""
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    alpha_file.write_text(json.dumps({
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
        },
    }))

    syncer.sync_once()
    syncer.sync_once()

    state = load_state(syncer.state_dir)
    pair_id = next(iter(state))
    archive_alpha = syncer.state_dir / "archive" / pair_id / "alpha"
    assert len(list(archive_alpha.iterdir())) == 1
    # Beta is brand-new on first sync; no prior slot existed there, so
    # there should be no beta archive at all.
    archive_beta = syncer.state_dir / "archive" / pair_id / "beta"
    assert not archive_beta.exists()
