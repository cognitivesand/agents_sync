"""Per-artifact secret-egress tests for the customization library export
and import paths (US-12 AC-12 … AC-16).

The contract is type-agnostic: any canonical that ``find_mcp_secret_literals``
flags is considered "secret-bearing". Today only ``mcp_server`` canonicals
can reach that state; future customization_types whose adapters declare
secret-detection heuristics fall under the same rules without amendment.
"""
from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from typing import Any

import pytest

from agents_sync.canonical import canonical_path, save_canonical
from agents_sync.identity import validate_pair_id
from agents_sync.portable_archive import (
    MANIFEST_NAME,
    CANONICAL_PREFIX,
    ExportReport,
    ImportReport,
    export_to_zip,
    import_from_zip,
)
from agents_sync.state import (
    CustomizationArtifactState,
    AgenticToolState,
    save_state,
    load_state,
)


# ----------------------- helpers -----------------------


_CLEAN_PAIR_ID = "00000000-0000-4000-8000-000000000001"
_SECRET_PAIR_ID = "00000000-0000-4000-8000-000000000002"


def _make_clean_mcp_canonical(name: str = "context7") -> dict[str, Any]:
    """An mcp_server canonical with NO literal secrets — uses env-references."""
    return {
        "kind": "mcp_server",
        "name": name,
        "schema_version": 4,
        "url": "https://mcp.context7.com/mcp",
        "headers": {"Authorization": "Bearer ${env:CONTEXT7_TOKEN}"},
        "per_agentic_tool_only": {},
        "per_agentic_tool_extra": {},
    }


def _make_secret_bearing_canonical(name: str = "github") -> dict[str, Any]:
    """An mcp_server canonical that carries a literal token in env.GITHUB_TOKEN.

    Used to simulate a stale canonical written before the policy was
    tightened (or one that bypassed the parse path via direct edit).
    """
    return {
        "kind": "mcp_server",
        "name": name,
        "schema_version": 4,
        "command": "github-mcp",
        "env": {"GITHUB_TOKEN": "ghp_literal_token_for_test"},
        "per_agentic_tool_only": {},
        "per_agentic_tool_extra": {},
    }


def _write_canonical_and_state(
    state_dir: Path, pair_id: str, canonical: dict[str, Any]
) -> None:
    """Persist a canonical + its state entry directly, bypassing the parse path.

    Used to set up exactly the literal-bearing canonical contents that
    ``find_mcp_secret_literals`` will flag at egress time.
    """
    validate_pair_id(pair_id)
    canonical = {**canonical, "pair_id": pair_id}
    save_canonical(state_dir, pair_id, canonical)
    state = load_state(state_dir)
    state[pair_id] = CustomizationArtifactState(
        kind="mcp_server",
        last_modified=0.0,
        generation=1,
        agentic_tools={
            "claude": AgenticToolState(
                path=state_dir / "tools" / "claude" / f"{canonical['name']}.json",
                last_seen=None,
                last_written=None,
                slot=canonical["name"],
            ),
        },
    )
    save_state(state_dir, state)


def _build_state_dir(tmp_path: Path) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    return state_dir


def _build_test_config(state_dir: Path, *, secret_policy: str) -> dict[str, Any]:
    """Minimal config dict shaped like a Syncer config (for import_from_zip)."""
    base = state_dir.parent
    for sub in ("ca", "cc", "cs", "cr", "xa", "xp", "xs", "xr",
                "as", "oa", "oc", "os", "or"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(base / "ca"),
        "claude_commands_dir": str(base / "cc"),
        "claude_skills_dir": str(base / "cs"),
        "claude_rules_dir": str(base / "cr"),
        "claude_mcp_servers_file": str(base / "claude.json"),
        "codex_agents_dir": str(base / "xa"),
        "codex_prompts_dir": str(base / "xp"),
        "codex_skills_dir": str(base / "xs"),
        "codex_rules_dir": str(base / "xr"),
        "codex_config_file": str(base / "codex.toml"),
        "antigravity_skills_dir": str(base / "as"),
        "antigravity_enabled": False,
        "opencode_agents_dir": str(base / "oa"),
        "opencode_commands_dir": str(base / "oc"),
        "opencode_skills_dir": str(base / "os"),
        "opencode_rules_dir": str(base / "or"),
        "opencode_config_file": str(base / "opencode.json"),
        "opencode_enabled": False,
        "import_collision_strategy": "mtime_wins",
        "secret_policy": secret_policy,
    }


def _read_manifest(zip_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path) as zf:
        return json.loads(zf.read(MANIFEST_NAME))


def _zip_canonical_pair_ids(zip_path: Path) -> set[str]:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    return {
        n[len(CANONICAL_PREFIX):-len(".json")]
        for n in names
        if n.startswith(CANONICAL_PREFIX) and n.endswith(".json")
    }


# ----------------------- AC-12 -----------------------


def test_ac12_export_under_secrets_refused_with_no_literals_ships_everything(
    tmp_path: Path,
) -> None:
    state_dir = _build_state_dir(tmp_path)
    _write_canonical_and_state(state_dir, _CLEAN_PAIR_ID, _make_clean_mcp_canonical())

    zip_path = tmp_path / "export.zip"
    report = export_to_zip(state_dir, zip_path, secret_policy="secrets_refused")

    assert isinstance(report, ExportReport)
    assert report.artifact_count == 1
    assert report.skipped_secret_artifacts == []
    assert report.contains_secret_literals is False
    assert _zip_canonical_pair_ids(zip_path) == {_CLEAN_PAIR_ID}
    assert _read_manifest(zip_path)["contains_secret_literals"] is False


# ----------------------- AC-13 -----------------------


def test_ac13_export_under_secrets_refused_skips_literal_bearing_with_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state_dir = _build_state_dir(tmp_path)
    _write_canonical_and_state(state_dir, _CLEAN_PAIR_ID, _make_clean_mcp_canonical())
    _write_canonical_and_state(
        state_dir, _SECRET_PAIR_ID, _make_secret_bearing_canonical()
    )

    zip_path = tmp_path / "export.zip"
    with caplog.at_level(logging.WARNING):
        report = export_to_zip(state_dir, zip_path, secret_policy="secrets_refused")

    # Clean canonical shipped; literal-bearing canonical skipped.
    assert report.artifact_count == 1
    assert report.skipped_secret_artifacts == [_SECRET_PAIR_ID]
    assert report.contains_secret_literals is False
    assert _zip_canonical_pair_ids(zip_path) == {_CLEAN_PAIR_ID}
    assert _read_manifest(zip_path)["contains_secret_literals"] is False

    # One WARNING naming the skipped artifact + the offending field path.
    skip_records = [
        r for r in caplog.records
        if "Skipping export" in r.message
        and _SECRET_PAIR_ID in r.message
        and "env.GITHUB_TOKEN" in r.message
    ]
    assert len(skip_records) == 1


# ----------------------- AC-14 -----------------------


def test_ac14_export_under_secrets_accepted_ships_literals_verbatim(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state_dir = _build_state_dir(tmp_path)
    _write_canonical_and_state(state_dir, _CLEAN_PAIR_ID, _make_clean_mcp_canonical())
    _write_canonical_and_state(
        state_dir, _SECRET_PAIR_ID, _make_secret_bearing_canonical()
    )

    zip_path = tmp_path / "export.zip"
    with caplog.at_level(logging.WARNING):
        report = export_to_zip(state_dir, zip_path, secret_policy="secrets_accepted")

    # Both shipped, manifest flag is true, summary warning logged.
    assert report.artifact_count == 2
    assert report.skipped_secret_artifacts == []
    assert report.contains_secret_literals is True
    assert _zip_canonical_pair_ids(zip_path) == {_CLEAN_PAIR_ID, _SECRET_PAIR_ID}
    assert _read_manifest(zip_path)["contains_secret_literals"] is True

    # The literal token must actually be inside the export.
    with zipfile.ZipFile(zip_path) as zf:
        secret_entry = json.loads(
            zf.read(f"{CANONICAL_PREFIX}{_SECRET_PAIR_ID}.json")
        )
    assert secret_entry["env"]["GITHUB_TOKEN"] == "ghp_literal_token_for_test"

    # Summary WARNING listing the affected pair_id.
    summary_records = [
        r for r in caplog.records
        if "secret_policy=secrets_accepted" in r.message
        and _SECRET_PAIR_ID in r.message
    ]
    assert summary_records, "expected one summary WARNING for secrets_accepted export"


# ----------------------- AC-15 -----------------------


def test_ac15_import_under_secrets_refused_skips_literal_bearing_with_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Producer (secrets_accepted) ships a mixed export.
    source_dir = _build_state_dir(tmp_path / "source")
    _write_canonical_and_state(source_dir, _CLEAN_PAIR_ID, _make_clean_mcp_canonical())
    _write_canonical_and_state(
        source_dir, _SECRET_PAIR_ID, _make_secret_bearing_canonical()
    )
    zip_path = tmp_path / "export.zip"
    export_to_zip(source_dir, zip_path, secret_policy="secrets_accepted")

    # Receiver (secrets_refused) imports.
    target_dir = _build_state_dir(tmp_path / "target")
    config = _build_test_config(target_dir, secret_policy="secrets_refused")

    with caplog.at_level(logging.WARNING):
        report = import_from_zip(
            target_dir,
            zip_path,
            strategy="mtime_wins",
            config=config,
            agentic_tools={},
        )

    assert isinstance(report, ImportReport)
    # The clean canonical landed; the secret-bearing one was filtered.
    assert _CLEAN_PAIR_ID in report.accepted
    assert _SECRET_PAIR_ID not in report.accepted
    assert report.skipped_secret_artifacts == [_SECRET_PAIR_ID]
    assert canonical_path(target_dir, _CLEAN_PAIR_ID).exists()
    assert not canonical_path(target_dir, _SECRET_PAIR_ID).exists()

    # WARNING naming the skipped artifact + field path.
    skip_records = [
        r for r in caplog.records
        if "Skipping import" in r.message
        and _SECRET_PAIR_ID in r.message
        and "env.GITHUB_TOKEN" in r.message
    ]
    assert len(skip_records) == 1


# ----------------------- AC-16 -----------------------


def test_ac16_import_under_secrets_accepted_takes_literals_verbatim_with_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    source_dir = _build_state_dir(tmp_path / "source")
    _write_canonical_and_state(source_dir, _CLEAN_PAIR_ID, _make_clean_mcp_canonical())
    _write_canonical_and_state(
        source_dir, _SECRET_PAIR_ID, _make_secret_bearing_canonical()
    )
    zip_path = tmp_path / "export.zip"
    export_to_zip(source_dir, zip_path, secret_policy="secrets_accepted")

    target_dir = _build_state_dir(tmp_path / "target")
    config = _build_test_config(target_dir, secret_policy="secrets_accepted")

    with caplog.at_level(logging.WARNING):
        report = import_from_zip(
            target_dir,
            zip_path,
            strategy="mtime_wins",
            config=config,
            agentic_tools={},
        )

    # Both canonicals accepted; the literal landed verbatim on disk.
    assert _CLEAN_PAIR_ID in report.accepted
    assert _SECRET_PAIR_ID in report.accepted
    assert report.skipped_secret_artifacts == []
    secret_path = canonical_path(target_dir, _SECRET_PAIR_ID)
    assert secret_path.exists()
    secret = json.loads(secret_path.read_text(encoding="utf-8"))
    assert secret["env"]["GITHUB_TOKEN"] == "ghp_literal_token_for_test"

    # Summary WARNING listing the affected pair_id.
    summary_records = [
        r for r in caplog.records
        if "secret_policy=secrets_accepted" in r.message
        and "import" in r.message.lower()
        and _SECRET_PAIR_ID in r.message
    ]
    assert summary_records, "expected one summary WARNING for secrets_accepted import"
