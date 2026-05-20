"""Phase 0 (US-12 prerequisite): state schema v3 with per-pair last_modified.

These tests cover the schema bump itself: serialisation, deserialisation,
the v2-or-older rebuild policy, and the rule that update_state_n_way
stamps last_modified on every record-update.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agents_sync.state import (
    STATE_SCHEMA_VERSION,
    AgenticToolState,
    CustomizationArtifactState,
    load_state,
    save_state,
)


def test_schema_version_is_three():
    """Pinning the version keeps callers honest about the migration cutover."""
    assert STATE_SCHEMA_VERSION == 3


def test_to_dict_serialises_last_modified():
    ps = CustomizationArtifactState(
        kind="skill",
        last_modified=1234567890.5,
        agentic_tools={"claude": AgenticToolState(path="/x", last_seen="d", last_written="d")},
    )

    encoded = ps.to_dict()

    assert encoded["last_modified"] == 1234567890.5
    assert encoded["customization_type"] == "skill"
    assert "claude" in encoded["agentic_tools"]


def test_from_dict_round_trip_preserves_last_modified():
    original = CustomizationArtifactState(
        kind="agent",
        last_modified=42.0,
        agentic_tools={"claude": AgenticToolState(path="/a.md")},
    )

    decoded = CustomizationArtifactState.from_dict(original.to_dict())

    assert decoded.last_modified == 42.0
    assert decoded.kind == "agent"


def test_from_dict_tolerates_missing_last_modified_for_forward_compat():
    """An entry written by a future tool that drops the field still loads."""
    encoded = {
        "customization_type": "skill",
        "agentic_tools": {"claude": {"path": "/x", "last_seen": "d", "last_written": "d"}},
    }

    decoded = CustomizationArtifactState.from_dict(encoded)

    assert decoded.last_modified is None


def test_agentic_tool_state_omits_slot_when_none():
    """v3 stays byte-stable for non-keyed-map artifacts: an unset slot does
    not appear in to_dict, so existing state files are not rewritten with
    an extra key on the next save cycle."""
    encoded = AgenticToolState(path="/x.md", last_seen="d", last_written="d").to_dict()

    assert "slot" not in encoded


def test_agentic_tool_state_round_trips_slot():
    """v0.5 keyed-map artifacts (mcp_server) carry a slot key. The field
    survives to_dict / from_dict without a schema-version bump."""
    original = AgenticToolState(
        path="/home/u/.cursor/mcp.json",
        last_seen="d",
        last_written="d",
        slot="github",
    )

    decoded = AgenticToolState.from_dict(original.to_dict())

    assert decoded.slot == "github"
    assert decoded.path == "/home/u/.cursor/mcp.json"


def test_agentic_tool_state_from_dict_tolerates_missing_slot():
    """A state file written by an older agents_sync version has no slot
    field; load it as None rather than rejecting."""
    decoded = AgenticToolState.from_dict({
        "path": "/x.md",
        "last_seen": "d",
        "last_written": "d",
    })

    assert decoded.slot is None


def test_from_dict_rejects_non_numeric_last_modified():
    encoded = {
        "customization_type": "skill",
        "last_modified": "not-a-float",
        "agentic_tools": {},
    }

    with pytest.raises(ValueError, match="last_modified must be a number"):
        CustomizationArtifactState.from_dict(encoded)


def test_load_state_rebuilds_when_schema_version_is_two(tmp_path: Path):
    """v2 → v3 cutover follows the existing policy: regenerate from scratch."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "customization_artifacts": {
                    "11111111-2222-4333-8444-555555555555": {
                        "customization_type": "skill",
                        "agentic_tools": {
                            "claude": {"path": "/x", "last_seen": "d", "last_written": "d"}
                        },
                    }
                },
            }
        )
    )

    assert load_state(state_dir) == {}


def test_save_then_load_round_trip(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    pair_id = "11111111-2222-4333-8444-555555555555"
    state = {
        pair_id: CustomizationArtifactState(
            kind="skill",
            last_modified=99.5,
            agentic_tools={
                "claude": AgenticToolState(path="/x", last_seen="d", last_written="d"),
            },
        ),
    }

    save_state(state_dir, state)
    reloaded = load_state(state_dir)

    assert pair_id in reloaded
    assert reloaded[pair_id].last_modified == 99.5
    assert reloaded[pair_id].kind == "skill"


def test_update_state_n_way_stamps_last_modified(syncer):
    """Every render-and-record bumps last_modified to wall-clock time."""
    skill_dir = syncer.tool_root("claude", "skill") / "foo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: foo\ndescription: x\n---\nbody\n")

    before = time.time()
    syncer.sync_once()
    after = time.time()

    raw = json.loads((syncer.state_dir / "state.json").read_text())
    assert raw["schema_version"] == 3
    entries = raw["customization_artifacts"]
    assert entries, "adoption did not record any state"
    entry = next(iter(entries.values()))
    assert entry["last_modified"] is not None
    assert before <= entry["last_modified"] <= after


def test_update_state_n_way_advances_last_modified_on_subsequent_edit(syncer):
    """A second sync that rewrites bytes updates last_modified strictly forward."""
    skill_dir = syncer.tool_root("claude", "skill") / "foo"
    skill_dir.mkdir()
    md = skill_dir / "SKILL.md"
    md.write_text("---\nname: foo\ndescription: x\n---\ninitial\n")
    syncer.sync_once()
    first = next(iter(
        json.loads((syncer.state_dir / "state.json").read_text())["customization_artifacts"].values()
    ))["last_modified"]

    # Edit and re-sync. Wall clock must move forward enough to observe.
    time.sleep(0.01)
    md.write_text(md.read_text().replace("initial", "second"))
    syncer.sync_once()

    second = next(iter(
        json.loads((syncer.state_dir / "state.json").read_text())["customization_artifacts"].values()
    ))["last_modified"]
    assert second > first
