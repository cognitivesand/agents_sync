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
from agents_sync.identity import validate_pair_id
from agents_sync.mcp_secret_policy import McpSecretLeakError
from agents_sync.mcp_server_io import (
    extract_pair_id_from_mcp_server_json,
    parse_mcp_server_json,
    render_mcp_server_json,
)
from agents_sync.state import load_state
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


def _archive_files(syncer: Syncer, pair_id: str, tool_name: str) -> list[Path]:
    archive_dir = syncer.state_dir / "archive" / pair_id / tool_name
    if not archive_dir.exists():
        return []
    return sorted(path for path in archive_dir.iterdir() if path.is_file())


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
    beta_before = _read_json(beta_file)
    alpha = _read_json(alpha_file)
    alpha["mcpServers"]["sqlite"] = {"name": "sqlite", "command": "sqlite-mcp"}
    _write_json(alpha_file, alpha)

    syncer.sync_once()

    beta = _read_json(beta_file)
    assert list(beta["mcpServers"]) == ["github", "filesystem", "docs", "sqlite"]
    for server_name in ("github", "filesystem", "docs"):
        assert (
            beta["mcpServers"][server_name]
            == beta_before["mcpServers"][server_name]
        )
    assert beta["mcpServers"]["sqlite"]["command"] == "sqlite-mcp"
    assert beta["theme"] == "dark"


def test_mcp_pair_id_injected_into_slot(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
            "filesystem": {"name": "filesystem", "command": "fs-mcp"},
        },
        "theme": "dark",
        "inputs": [{"id": "token"}],
    })

    syncer.sync_once()

    alpha = _read_json(alpha_file)
    beta = _read_json(tmp_path / "beta-mcp.json")
    github_pair_id = alpha["mcpServers"]["github"]["pair_id"]
    assert validate_pair_id(github_pair_id) == github_pair_id
    assert beta["mcpServers"]["github"]["pair_id"] == github_pair_id
    assert alpha["mcpServers"]["filesystem"]["pair_id"] != github_pair_id
    assert beta["mcpServers"]["filesystem"]["pair_id"] != github_pair_id
    assert alpha["theme"] == "dark"
    assert alpha["inputs"] == [{"id": "token"}]
    assert "pair_id" not in alpha
    assert "pair_id" not in beta

    state = load_state(syncer.state_dir)
    assert github_pair_id in state
    github_state = state[github_pair_id]
    assert set(github_state.agentic_tools) == {"alpha", "beta"}
    assert github_state.agentic_tools["alpha"].slot == "github"
    assert github_state.agentic_tools["beta"].slot == "github"
    canonical = load_canonical(syncer.state_dir, github_pair_id)
    assert canonical is not None
    assert canonical["pair_id"] == github_pair_id
    assert canonical["name"] == "github"
    assert canonical["command"] == "gh-mcp"


def test_mcp_adoption_is_idempotent(tmp_path: Path):
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    beta_file = tmp_path / "beta-mcp.json"
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
        },
    })

    assert syncer.sync_once() == 1
    pair_id = _pair_id_for_slot(syncer, "github")
    canonical_path = syncer.state_dir / "canonical" / f"{pair_id}.json"
    archive_root = syncer.state_dir / "archive"
    archive_before = [
        (path.relative_to(archive_root).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(archive_root.rglob("*"))
        if path.is_file()
    ]
    alpha_before = alpha_file.read_text(encoding="utf-8")
    beta_before = beta_file.read_text(encoding="utf-8")
    state_before = (syncer.state_dir / "state.json").read_text(encoding="utf-8")
    canonical_before = canonical_path.read_text(encoding="utf-8")

    assert syncer.sync_once() == 0

    archive_after = [
        (path.relative_to(archive_root).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(archive_root.rglob("*"))
        if path.is_file()
    ]
    assert alpha_file.read_text(encoding="utf-8") == alpha_before
    assert beta_file.read_text(encoding="utf-8") == beta_before
    assert (
        (syncer.state_dir / "state.json").read_text(encoding="utf-8")
        == state_before
    )
    assert canonical_path.read_text(encoding="utf-8") == canonical_before
    assert archive_after == archive_before


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
    beta_before = _read_json(beta_file)
    deleted_slot = beta_before["mcpServers"]["github"]

    alpha = _read_json(alpha_file)
    del alpha["mcpServers"]["github"]
    _write_json(alpha_file, alpha)
    syncer.sync_once()

    beta = _read_json(beta_file)
    assert set(beta["mcpServers"]) == {"filesystem"}
    assert beta.get("theme") == "dark"
    assert github_pair_id not in load_state(syncer.state_dir)
    archive_entries = _archive_files(syncer, github_pair_id, "beta")
    assert len(archive_entries) == 1
    archived = _read_json(archive_entries[0])
    assert archived == deleted_slot
    assert "mcpServers" not in archived
    assert "filesystem" not in archived


def test_mcp_secret_policy_refuse_blocks_adoption(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
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

    with caplog.at_level("ERROR"):
        changed = syncer.sync_once()

    refusal_records = [
        record for record in caplog.records
        if record.exc_info
        and isinstance(record.exc_info[1], McpSecretLeakError)
    ]
    assert refusal_records
    for record in refusal_records:
        secret_error = record.exc_info[1]
        assert isinstance(secret_error, McpSecretLeakError)
        assert secret_error.policy == "refuse"
        assert [finding.field_path for finding in secret_error.findings] == [
            "env.GITHUB_TOKEN",
        ]
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
        "placeholder_env_var": "AGENTS_SYNC_REDACTED_1",
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


def test_mcp_managed_conflict_newest_mtime_wins_archives_loser_slot(
    tmp_path: Path,
):
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
    _write_json(beta_file, {
        "mcpServers": {},
        "theme": "light",
        "inputs": [{"id": "beta-token"}],
    })
    syncer.sync_once()
    github_pair_id = _pair_id_for_slot(syncer, "github")

    alpha = _read_json(alpha_file)
    beta = _read_json(beta_file)
    alpha["mcpServers"]["github"]["command"] = "alpha-edit"
    beta["mcpServers"]["github"]["command"] = "beta-edit"
    loser_slot = dict(alpha["mcpServers"]["github"])
    _write_json(alpha_file, alpha)
    _write_json(beta_file, beta)
    os.utime(alpha_file, (3000, 3000))
    os.utime(beta_file, (4000, 4000))
    archives_before = set(_archive_files(syncer, github_pair_id, "alpha"))

    assert syncer.sync_once() == 1

    alpha_after = _read_json(alpha_file)
    beta_after = _read_json(beta_file)
    assert alpha_after["mcpServers"]["github"]["command"] == "beta-edit"
    assert beta_after["mcpServers"]["github"]["command"] == "beta-edit"
    assert alpha_after["mcpServers"]["filesystem"]["command"] == "fs-mcp"
    assert beta_after["mcpServers"]["filesystem"]["command"] == "fs-mcp"
    assert alpha_after["theme"] == "dark"
    assert beta_after["theme"] == "light"
    assert beta_after["inputs"] == [{"id": "beta-token"}]

    new_archives = [
        path for path in _archive_files(syncer, github_pair_id, "alpha")
        if path not in archives_before
    ]
    assert new_archives
    for archive_path in new_archives:
        archived = _read_json(archive_path)
        assert archived == loser_slot
        assert "mcpServers" not in archived
        assert "filesystem" not in archived

    canonical = load_canonical(syncer.state_dir, github_pair_id)
    assert canonical is not None
    assert canonical["command"] == "beta-edit"


def test_mcp_two_adapters_same_shared_file_different_slots_no_collision(tmp_path: Path):
    alpha_file = tmp_path / "alpha-mcp.json"
    syncer = _mcp_syncer(tmp_path, alpha_file=alpha_file)
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
            "filesystem": {"name": "filesystem", "command": "fs-mcp"},
        },
    })

    changed = syncer.sync_once()

    assert changed == 2
    state = load_state(syncer.state_dir)
    assert len(state) == 2
    beta = _read_json(tmp_path / "beta-mcp.json")
    assert set(beta["mcpServers"]) == {"github", "filesystem"}
    assert validate_pair_id(beta["mcpServers"]["github"]["pair_id"])
    assert validate_pair_id(beta["mcpServers"]["filesystem"]["pair_id"])
    assert (
        beta["mcpServers"]["github"]["pair_id"]
        != beta["mcpServers"]["filesystem"]["pair_id"]
    )


def test_mcp_two_adapters_same_shared_file_same_slot_collide(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    shared_file = tmp_path / "shared-mcp.json"
    syncer = _mcp_syncer(tmp_path, alpha_file=shared_file, beta_file=shared_file)
    _write_json(shared_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "gh-mcp"},
        },
    })
    original_text = shared_file.read_text(encoding="utf-8")

    with caplog.at_level("ERROR"):
        changed = syncer.sync_once()

    collision_records = [
        record for record in caplog.records
        if record.levelname == "ERROR" and "Target collision" in record.message
    ]
    assert len(collision_records) == 1
    assert str(shared_file) in collision_records[0].message
    assert "slot=github" in collision_records[0].message
    assert changed == 0
    assert load_state(syncer.state_dir) == {}
    assert shared_file.read_text(encoding="utf-8") == original_text
    assert "pair_id" not in _read_json(shared_file)["mcpServers"]["github"]


def test_mcp_occupied_slot_with_different_pair_id_blocks_adoption(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    syncer = _mcp_syncer(tmp_path)
    alpha_file = tmp_path / "alpha-mcp.json"
    beta_file = tmp_path / "beta-mcp.json"
    beta_pair_id = "00000000-0000-4000-8000-0000000000aa"
    _write_json(alpha_file, {
        "mcpServers": {
            "github": {"name": "github", "command": "alpha-mcp"},
        },
    })
    _write_json(beta_file, {
        "mcpServers": {
            "github": {
                "name": "github",
                "command": "beta-mcp",
                "pair_id": beta_pair_id,
            },
        },
    })
    alpha_before = alpha_file.read_text(encoding="utf-8")
    beta_before = beta_file.read_text(encoding="utf-8")

    with caplog.at_level("ERROR"):
        changed = syncer.sync_once()

    collision_records = [
        record for record in caplog.records
        if "slot collision" in record.message.lower()
    ]
    assert collision_records
    assert any(
        str(beta_file) in record.message and "slot=github" in record.message
        for record in collision_records
    )
    assert changed == 0
    assert load_state(syncer.state_dir) == {}
    assert alpha_file.read_text(encoding="utf-8") == alpha_before
    assert beta_file.read_text(encoding="utf-8") == beta_before
