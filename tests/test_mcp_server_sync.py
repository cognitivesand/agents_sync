"""Synthetic end-to-end coverage for ``mcp_server`` shared-map sync."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    SharedKeyedMapLayout,
)
from agents_sync.canonical import load_canonical
from agents_sync.mcp_server_io import (
    extract_pair_id_from_mcp_server_json,
    parse_mcp_server_json,
    render_mcp_server_json,
)
from agents_sync.state import load_state, save_state
from agents_sync.sync import Syncer


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
        "mcp_server_secret_policy": "refuse",
    }


def _mcp_server_spec(
    tool_name: str,
    shared_path_key: str,
    config: dict[str, Any],
) -> AgenticToolSpec:
    def parse(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_mcp_server_json(
            text,
            prior_canonical,
            agentic_tool_name=tool_name,
            artifact_path=artifact_path,
            artifact_root=artifact_root,
            secret_policy=str(config.get("mcp_server_secret_policy", "refuse")),
        )

    def render(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_mcp_server_json(
            canonical,
            prior_text,
            agentic_tool_name=tool_name,
            secret_policy=str(config.get("mcp_server_secret_policy", "refuse")),
        )

    return AgenticToolSpec(
        name=tool_name,
        config_dir_keys={"mcp_server": shared_path_key},
        io={
            "mcp_server": CustomizationTypeIO(
                parse=parse,
                render=render,
                extract_pair_id=extract_pair_id_from_mcp_server_json,
                file_layout=SharedKeyedMapLayout(
                    shared_path_config_key=shared_path_key,
                    map_key_path=("mcpServers",),
                    key_field="name",
                    file_format="json",
                ),
            ),
        },
    )


def _mcp_syncer(
    tmp_path: Path,
    *,
    alpha_file: Path | None = None,
    beta_file: Path | None = None,
    policy: str = "refuse",
) -> Syncer:
    config = _baseline_config(tmp_path)
    config["alpha_mcp_file"] = str(alpha_file or tmp_path / "alpha-mcp.json")
    config["beta_mcp_file"] = str(beta_file or tmp_path / "beta-mcp.json")
    config["mcp_server_secret_policy"] = policy
    return Syncer(
        config,
        agentic_tools={
            "alpha": _mcp_server_spec("alpha", "alpha_mcp_file", config),
            "beta": _mcp_server_spec("beta", "beta_mcp_file", config),
        },
    )


def _pair_id_for_slot(syncer: Syncer, slot: str) -> str:
    state = load_state(syncer.state_dir)
    for pair_id, entry in state.items():
        if any(tool_state.slot == slot for tool_state in entry.agentic_tools.values()):
            return pair_id
    raise AssertionError(f"slot not found in state: {slot}")


def test_mcp_adopt_between_synthetic_adapters(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    beta_file = tmp_path / "beta-mcp.json"
    initial = {
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
            "filesystem": {"name": "filesystem", "command": "fs-mcp"},
            "docs": {
                "name": "docs",
                "transport": "http",
                "url": "https://example.test/mcp",
            },
        },
        "theme": "dark",
    }
    _write_json(alpha_file, initial)
    _write_json(beta_file, initial)

    syncer.sync_once()
    alpha = _read_json(alpha_file)
    alpha["mcpServers"]["sqlite"] = {"name": "sqlite", "command": "sqlite-mcp"}
    _write_json(alpha_file, alpha)

    syncer.sync_once()

    beta = _read_json(beta_file)
    assert set(beta["mcpServers"]) == {"github", "filesystem", "docs", "sqlite"}
    assert beta["mcpServers"]["sqlite"]["command"] == "sqlite-mcp"
    assert beta["theme"] == "dark"


def test_mcp_pair_id_injected_into_slot(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
        },
    })

    syncer.sync_once()

    alpha = _read_json(alpha_file)
    beta = _read_json(tmp_path / "beta-mcp.json")
    assert alpha["mcpServers"]["github"]["pair_id"]
    assert (
        alpha["mcpServers"]["github"]["pair_id"]
        == beta["mcpServers"]["github"]["pair_id"]
    )


def test_mcp_archive_is_per_slot(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    beta_file = tmp_path / "beta-mcp.json"
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
            "filesystem": {"name": "filesystem", "command": "fs-mcp"},
        },
    })
    syncer.sync_once()

    alpha = _read_json(alpha_file)
    alpha["mcpServers"]["github"]["command"] = "gh-mcp-v2"
    _write_json(alpha_file, alpha)
    syncer.sync_once()

    github_pair_id = _pair_id_for_slot(syncer, "github")
    archive_dir = syncer.state_dir / "archive" / github_pair_id / "beta"
    entries = list(archive_dir.iterdir())
    assert len(entries) == 1
    archived = json.loads(entries[0].read_text(encoding="utf-8"))
    assert archived["name"] == "github"
    assert archived["command"] == "gh-mcp"
    assert "mcpServers" not in archived
    assert "filesystem" not in archived

    beta = _read_json(beta_file)
    assert beta["mcpServers"]["filesystem"]["command"] == "fs-mcp"


def test_mcp_remove_slot_removes_in_other_tool(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    beta_file = tmp_path / "beta-mcp.json"
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
            "filesystem": {"name": "filesystem", "command": "fs-mcp"},
        },
        "theme": "dark",
    })
    _write_json(beta_file, {"mcpServers": {}, "theme": "dark"})
    syncer.sync_once()
    github_pair_id = _pair_id_for_slot(syncer, "github")

    alpha = _read_json(alpha_file)
    del alpha["mcpServers"]["github"]
    _write_json(alpha_file, alpha)
    syncer.sync_once()

    beta = _read_json(beta_file)
    assert set(beta["mcpServers"]) == {"filesystem"}
    assert beta.get("theme") == "dark"
    assert github_pair_id not in load_state(syncer.state_dir)
    archive_dir = syncer.state_dir / "archive" / github_pair_id / "beta"
    assert archive_dir.exists()


def test_mcp_secret_policy_refuse_blocks_adoption(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path, policy="refuse")
    alpha_file = tmp_path / "alpha-mcp.json"
    beta_file = tmp_path / "beta-mcp.json"
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {
                "name": "github",
                "command": "gh-mcp",
                "env": {"GITHUB_TOKEN": "ghp_literal"},
            },
        },
    })

    changed = syncer.sync_once()

    assert changed == 0
    assert not beta_file.exists()
    assert "pair_id" not in _read_json(alpha_file)["mcpServers"]["github"]
    assert load_state(syncer.state_dir) == {}


def test_mcp_secret_policy_redact_rewrites(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path, policy="redact")
    alpha_file = tmp_path / "alpha-mcp.json"
    beta_file = tmp_path / "beta-mcp.json"
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {
                "name": "github",
                "command": "gh-mcp",
                "env": {"GITHUB_TOKEN": "ghp_literal"},
            },
        },
    })

    syncer.sync_once()

    alpha = _read_json(alpha_file)
    beta = _read_json(beta_file)
    placeholder = "${env:AGENTS_SYNC_REDACTED_1}"
    assert alpha["mcpServers"]["github"]["env"]["GITHUB_TOKEN"] == placeholder
    assert beta["mcpServers"]["github"]["env"]["GITHUB_TOKEN"] == placeholder
    pair_id = _pair_id_for_slot(syncer, "github")
    canonical = load_canonical(syncer.state_dir, pair_id)
    assert canonical is not None
    assert canonical["secret_redactions"] == [{
        "field_path": "env.GITHUB_TOKEN",
        "original_env_var": None,
    }]


def test_mcp_secret_policy_permissive_warns(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    syncer = _mcp_syncer(tmp_path, policy="permissive")
    alpha_file = tmp_path / "alpha-mcp.json"
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {
                "name": "github",
                "command": "gh-mcp",
                "env": {"GITHUB_TOKEN": "ghp_literal"},
            },
        },
    })

    with caplog.at_level("WARNING"):
        syncer.sync_once()

    beta = _read_json(tmp_path / "beta-mcp.json")
    assert beta["mcpServers"]["github"]["env"]["GITHUB_TOKEN"] == "ghp_literal"
    warnings = [
        r for r in caplog.records
        if "MCP server secret policy permissive" in r.message
    ]
    assert len(warnings) == 1


def test_mcp_sibling_keys_outside_map_preserved(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
        },
        "theme": "dark",
        "inputs": [{"id": "token"}],
    })

    syncer.sync_once()

    alpha = _read_json(alpha_file)
    beta = _read_json(tmp_path / "beta-mcp.json")
    assert alpha["theme"] == "dark"
    assert alpha["inputs"] == [{"id": "token"}]
    assert beta["mcpServers"]["github"]["command"] == "gh-mcp"


def test_mcp_first_boot_reconciliation_by_slot_key(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    beta_file = tmp_path / "beta-mcp.json"
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "older"},
        },
    })
    _write_json(beta_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "newer"},
        },
    })
    os.utime(alpha_file, (1000, 1000))
    os.utime(beta_file, (2000, 2000))

    syncer.sync_once()

    state = load_state(syncer.state_dir)
    assert len(state) == 1
    alpha = _read_json(alpha_file)
    beta = _read_json(beta_file)
    assert alpha["mcpServers"]["github"]["command"] == "newer"
    assert beta["mcpServers"]["github"]["command"] == "newer"
    assert (
        alpha["mcpServers"]["github"]["pair_id"]
        == beta["mcpServers"]["github"]["pair_id"]
    )


def test_mcp_two_adapters_same_shared_file_different_slots_no_collision(tmp_path: Path):
    alpha_file = tmp_path / "alpha-mcp.json"
    syncer = _mcp_syncer(tmp_path, alpha_file=alpha_file)
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
            "filesystem": {"name": "filesystem", "command": "fs-mcp"},
        },
    })

    syncer.tool_status.refresh()
    pairs, _ = syncer.discovery.discover(state={})
    blocked = syncer.discovery.block_target_collisions(pairs, state={})

    assert blocked == set()
    assert len(pairs) == 2


def test_mcp_two_adapters_same_shared_file_same_slot_collide(tmp_path: Path):
    shared_file = tmp_path / "shared-mcp.json"
    syncer = _mcp_syncer(tmp_path, alpha_file=shared_file, beta_file=shared_file)
    _write_json(shared_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
        },
    })

    changed = syncer.sync_once()

    assert changed == 0
    assert load_state(syncer.state_dir) == {}
    assert "pair_id" not in _read_json(shared_file)["mcpServers"]["github"]


def test_mcp_extend_refuses_unmanaged_existing_target_slot(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    beta_file = tmp_path / "beta-mcp.json"
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "managed"},
        },
    })

    syncer.sync_once()
    pair_id = _pair_id_for_slot(syncer, "github")

    state = load_state(syncer.state_dir)
    del state[pair_id].agentic_tools["beta"]
    save_state(syncer.state_dir, state)
    _write_json(beta_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "foreign"},
        },
    })

    changed = syncer.sync_once()

    assert changed == 0
    beta = _read_json(beta_file)
    assert beta["mcpServers"]["github"]["command"] == "foreign"
    assert "pair_id" not in beta["mcpServers"]["github"]
    assert set(load_state(syncer.state_dir)[pair_id].agentic_tools) == {"alpha"}
