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
        agentic_tools={"claude": AgenticToolState(path=Path("/x"), last_seen="d", last_written="d")},
    )

    encoded = ps.to_dict()

    assert encoded["last_modified"] == 1234567890.5
    assert encoded["customization_type"] == "skill"
    assert "claude" in encoded["agentic_tools"]


def test_from_dict_round_trip_preserves_last_modified():
    original = CustomizationArtifactState(
        kind="agent",
        last_modified=42.0,
        agentic_tools={"claude": AgenticToolState(path=Path("/a.md"))},
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
    encoded = AgenticToolState(path=Path("/x.md"), last_seen="d", last_written="d").to_dict()

    assert "slot" not in encoded


def test_agentic_tool_state_round_trips_slot():
    """v0.5 keyed-map artifacts (mcp_server) carry a slot key. The field
    survives to_dict / from_dict without a schema-version bump."""
    original = AgenticToolState(
        path=Path("/home/u/.cursor/mcp.json"),
        last_seen="d",
        last_written="d",
        slot="github",
    )

    decoded = AgenticToolState.from_dict(original.to_dict())

    assert decoded.slot == "github"
    assert decoded.path == Path("/home/u/.cursor/mcp.json")


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
                "claude": AgenticToolState(path=Path("/x"), last_seen="d", last_written="d"),
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


def test_generation_defaults_to_zero_for_pre_field_entries():
    """Legacy state entries without 'generation' deserialise as generation=0."""
    encoded = {
        "customization_type": "skill",
        "last_modified": 1.0,
        "agentic_tools": {},
    }
    decoded = CustomizationArtifactState.from_dict(encoded)
    assert decoded.generation == 0


def test_bump_advances_generation_and_sets_last_modified():
    ps = CustomizationArtifactState(kind="skill", last_modified=None, generation=0)
    ps.bump(now=100.0)
    assert ps.generation == 1
    assert ps.last_modified == 100.0
    ps.bump(now=200.0)
    assert ps.generation == 2
    assert ps.last_modified == 200.0


def test_to_dict_includes_generation_and_round_trips():
    ps = CustomizationArtifactState(
        kind="agent",
        last_modified=99.5,
        generation=7,
    )
    encoded = ps.to_dict()
    assert encoded["generation"] == 7
    decoded = CustomizationArtifactState.from_dict(encoded)
    assert decoded.generation == 7
    assert decoded.last_modified == 99.5


def test_load_state_quarantines_unparseable_json(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "state.json").write_text("not json {{")

    assert load_state(state_dir) == {}

    quarantined = list((state_dir / "quarantine").iterdir())
    assert len(quarantined) == 1
    assert quarantined[0].name.startswith("state.json.")
    assert quarantined[0].name.endswith(".corrupt")
    assert quarantined[0].read_text() == "not json {{"
    # Original is gone (moved to quarantine, not copied).
    assert not (state_dir / "state.json").exists()


def test_load_state_quarantines_non_dict_root(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "state.json").write_text("[1, 2, 3]")

    assert load_state(state_dir) == {}

    quarantined = list((state_dir / "quarantine").iterdir())
    assert len(quarantined) == 1


def test_load_state_does_not_quarantine_legacy_schema_versions(tmp_path: Path):
    """v2 -> v3 cutover is an expected rebuild, not a corruption signal."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(
        json.dumps({"schema_version": 2, "customization_artifacts": {}})
    )

    assert load_state(state_dir) == {}

    # No quarantine directory created for legacy versions.
    assert not (state_dir / "quarantine").exists()


def test_load_canonical_quarantines_corrupt_file(tmp_path: Path):
    from agents_sync.canonical import canonical_path, load_canonical

    pair_id = "11111111-2222-4333-8444-555555555555"
    state_dir = tmp_path / "state"
    path = canonical_path(state_dir, pair_id)
    path.parent.mkdir(parents=True)
    path.write_text("partial {")

    assert load_canonical(state_dir, pair_id) is None

    quarantined = list((state_dir / "quarantine").iterdir())
    assert len(quarantined) == 1
    assert quarantined[0].name.startswith(f"{pair_id}.json.")


def test_atomic_write_text_two_concurrent_writers_do_not_corrupt(tmp_path: Path):
    """Two concurrent writers produce a file with exactly one writer's content,
    never interleaved bytes nor a stale staging file left behind."""
    import threading

    from agents_sync.state import atomic_write_text

    target = tmp_path / "out.txt"
    payload_a = "a" * 4096
    payload_b = "b" * 4096
    barrier = threading.Barrier(2)

    def write(payload: str) -> None:
        barrier.wait()
        for _ in range(20):
            atomic_write_text(target, payload)

    threads = [
        threading.Thread(target=write, args=(payload_a,)),
        threading.Thread(target=write, args=(payload_b,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = target.read_text(encoding="utf-8")
    assert final in {payload_a, payload_b}
    # No staging files left behind.
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_sync_once_bumps_generation_on_first_write_and_on_edit(syncer):
    """Every render-and-record advances generation by 1 in the persisted state."""
    skill_dir = syncer.tool_root("claude", "skill") / "foo"
    skill_dir.mkdir()
    md = skill_dir / "SKILL.md"
    md.write_text("---\nname: foo\ndescription: x\n---\ninitial\n")
    syncer.sync_once()
    first_gen = next(iter(
        json.loads(
            (syncer.state_dir / "state.json").read_text()
        )["customization_artifacts"].values()
    ))["generation"]
    assert first_gen == 1

    md.write_text(md.read_text().replace("initial", "second"))
    syncer.sync_once()
    second_gen = next(iter(
        json.loads(
            (syncer.state_dir / "state.json").read_text()
        )["customization_artifacts"].values()
    ))["generation"]
    assert second_gen == 2
