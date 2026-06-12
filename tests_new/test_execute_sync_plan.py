"""Unit tests for the executor — content family (rebuild S19 increment 1).

``execute_sync_plan`` walks the planner's intents and performs the I/O in the one
order that preserves data: per-artifact transactions archive EVERY affected file
first and write only if all archives landed (US-06 AC-6); identical renders are
skipped (NFR-05); secret egress applies at absorb and at render (NFR-15 —
refusal is ``blocked``, never a partial write). Recorded digests come from
``surface_content_digest`` so the next poll observes the written surfaces as
unchanged. Real filesystem and real dialects via tmp_path; zero mocks (fault
injection at the shutil/os boundary only).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agents_sync.canonical_store import load_canonical, save_canonical
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.sync_plan import (
    AbsorbToolEdit,
    FreezeArtifact,
    ProjectToTools,
    RebuildCorruptCanonical,
    RejectCollision,
    ReportUnadoptable,
    ReprojectCanonical,
    SyncPlan,
    SyncResult,
)
from agents_sync.domain_model.sync_state import ArtifactRecord, RecordedSurface, SyncState
from agents_sync.domain_model.tool_surface import SurfaceFormat, ToolSurface
from agents_sync.execute_sync_plan import execute_sync_plan
from agents_sync.read_tool_surfaces import (
    DirectorySurfaceSpec,
    read_tool_surfaces,
)
from agents_sync.secret_policy import SECRET_POLICY_ACCEPTED

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"

_MARKDOWN = SurfaceFormat(
    dialect="markdown_frontmatter",
    id_field="pair_id",
    known_fields=(("name", "name"), ("description", "description")),
)


def _agent_text(name: str = "reviewer", body: str = "Be terse.") -> str:
    return f"---\npair_id: {_ARTIFACT_ID}\nname: {name}\n---\n{body}\n"


def _spec(directory: Path, tool: str) -> DirectorySurfaceSpec:
    return DirectorySurfaceSpec(
        tool=tool,
        kind="agent",
        directory=directory,
        filename_suffix=".md",
        surface_format=_MARKDOWN,
    )


def _surface(directory: Path, tool: str, filename: str = "reviewer.md") -> ToolSurface:
    return ToolSurface(tool, "agent", directory / filename, _MARKDOWN)


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A state dir plus one source-tool dir (claude, populated) and one target-tool
    dir (cursor, empty)."""
    state_dir = tmp_path / "state"
    claude_dir = tmp_path / "claude"
    cursor_dir = tmp_path / "cursor"
    claude_dir.mkdir()
    cursor_dir.mkdir()
    (claude_dir / "reviewer.md").write_text(_agent_text())
    return state_dir, claude_dir, cursor_dir


def _observe(claude_dir: Path, cursor_dir: Path) -> tuple[Any, ...]:
    return read_tool_surfaces((_spec(claude_dir, "claude"), _spec(cursor_dir, "cursor")))


def _recorded_state(claude_dir: Path, cursor_dir: Path, **record_overrides: Any) -> SyncState:
    fields: dict[str, Any] = {
        "name": "reviewer",
        "canonical_digest": "stale",
        "surfaces": {
            "claude": RecordedSurface(location=claude_dir / "reviewer.md"),
            "cursor": RecordedSurface(location=cursor_dir / "reviewer.md"),
        },
    }
    fields.update(record_overrides)
    return SyncState(records={_ARTIFACT_ID: ArtifactRecord(**fields)})


# --- result-only intents ---------------------------------------------------------------


def test_an_empty_plan_changes_nothing(tmp_path: Path) -> None:
    result, state = execute_sync_plan(SyncPlan(), (), SyncState(), tmp_path)

    assert result == SyncResult()
    assert state == SyncState()


def test_freeze_is_recorded_without_any_io(tmp_path: Path) -> None:
    plan = SyncPlan(intents=(FreezeArtifact(artifact_id=_ARTIFACT_ID),))

    result, _ = execute_sync_plan(plan, (), SyncState(), tmp_path)

    assert result.frozen == (_ARTIFACT_ID,)
    assert not (tmp_path / "canonical").exists()


def test_reject_collision_and_unadoptable_are_diagnosed(tmp_path: Path) -> None:
    other_id = "22222222-2222-4222-8222-222222222222"
    surface = _surface(tmp_path, "claude", "broken.md")
    plan = SyncPlan(
        intents=(
            RejectCollision(
                artifact_ids=(_ARTIFACT_ID, other_id), reconciliation_key=("agent", "reviewer")
            ),
            ReportUnadoptable(surface=surface),
        )
    )

    result, _ = execute_sync_plan(plan, (), SyncState(), tmp_path)

    assert _ARTIFACT_ID in result.diagnosed
    assert other_id in result.diagnosed
    assert str(surface.location) in result.diagnosed


# --- absorb_tool_edit ------------------------------------------------------------------


def test_absorb_saves_the_winner_canonical_and_updates_the_record(tmp_path: Path) -> None:
    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    observations = _observe(claude_dir, cursor_dir)
    source = _surface(claude_dir, "claude")
    plan = SyncPlan(intents=(AbsorbToolEdit(artifact_id=_ARTIFACT_ID, source=source),))

    result, state = execute_sync_plan(
        plan, observations, _recorded_state(claude_dir, cursor_dir), state_dir
    )

    stored = load_canonical(state_dir, _ARTIFACT_ID)
    assert isinstance(stored, CanonicalDocument)
    assert stored.name == "reviewer"
    assert result.changed == 1
    record = state.records[_ARTIFACT_ID]
    assert record.canonical_digest == stored.content_digest()
    assert record.surfaces["claude"].content_digest != ""


def test_absorb_of_a_secret_bearing_canonical_is_blocked(tmp_path: Path) -> None:
    # secrets_refused (the default): the artifact fails closed — no canonical write.
    state_dir = tmp_path / "state"
    mcp_dir = tmp_path / "mcp"
    mcp_dir.mkdir()
    surface = ToolSurface(
        "cursor",
        "mcp_server",
        mcp_dir / "mcp.json",
        SurfaceFormat(
            dialect="mcp_server",
            id_field="pair_id",
            map_key_path=("mcpServers",),
            file_format="json",
        ),
    )
    (mcp_dir / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {
                        "pair_id": _ARTIFACT_ID,
                        "command": "npx",
                        "env": {"GH_TOKEN": "hunter2"},
                    }
                }
            }
        )
    )
    from agents_sync.read_tool_surfaces import KeyedMapSurfaceSpec

    observations = read_tool_surfaces(
        (
            KeyedMapSurfaceSpec(
                tool="cursor",
                kind="mcp_server",
                file=mcp_dir / "mcp.json",
                surface_format=surface.surface_format,
            ),
        )
    )
    slot_surface = observations[0].tool_surface
    plan = SyncPlan(intents=(AbsorbToolEdit(artifact_id=_ARTIFACT_ID, source=slot_surface),))

    result, state = execute_sync_plan(plan, observations, SyncState(), state_dir)

    assert result.blocked == (_ARTIFACT_ID,)
    assert load_canonical(state_dir, _ARTIFACT_ID) is None  # nothing propagated
    assert state == SyncState()


# --- project_to_tools -------------------------------------------------------------------


def _stored_canonical(state_dir: Path, name: str = "reviewer") -> CanonicalDocument:
    document = CanonicalDocument(
        artifact_id=_ARTIFACT_ID, kind="agent", name=name, body="Be terse."
    )
    save_canonical(state_dir, document)
    return document


def test_project_writes_the_canonical_onto_the_targets(tmp_path: Path) -> None:
    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    _stored_canonical(state_dir)
    target = _surface(cursor_dir, "cursor")
    plan = SyncPlan(intents=(ProjectToTools(artifact_id=_ARTIFACT_ID, targets=(target,)),))

    result, state = execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), _recorded_state(claude_dir, cursor_dir), state_dir
    )

    written = (cursor_dir / "reviewer.md").read_text()
    assert "Be terse." in written
    assert _ARTIFACT_ID in written  # the projection embeds the id
    assert result.changed == 1
    assert state.records[_ARTIFACT_ID].surfaces["cursor"].content_digest != ""


def test_a_projected_surface_reads_back_as_unchanged_next_poll(tmp_path: Path) -> None:
    # The no-churn invariant (NFR-05): the digest recorded at write time equals the
    # digest the read phase observes next poll.
    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    _stored_canonical(state_dir)
    target = _surface(cursor_dir, "cursor")
    plan = SyncPlan(intents=(ProjectToTools(artifact_id=_ARTIFACT_ID, targets=(target,)),))

    _, state = execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), _recorded_state(claude_dir, cursor_dir), state_dir
    )

    [reread] = [
        obs for obs in _observe(claude_dir, cursor_dir) if obs.tool_surface.tool == "cursor"
    ]
    assert reread.content_digest == state.records[_ARTIFACT_ID].surfaces["cursor"].content_digest


def test_projecting_over_prior_content_archives_the_prior_bytes(tmp_path: Path) -> None:
    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    _stored_canonical(state_dir, name="reviewer")
    (cursor_dir / "reviewer.md").write_text("user-authored prior\n")
    target = _surface(cursor_dir, "cursor")
    plan = SyncPlan(intents=(ProjectToTools(artifact_id=_ARTIFACT_ID, targets=(target,)),))

    execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), _recorded_state(claude_dir, cursor_dir), state_dir
    )

    archive_dir = state_dir / "archive" / _ARTIFACT_ID / "cursor"
    [entry] = list(archive_dir.iterdir())
    assert entry.read_text() == "user-authored prior\n"


def test_an_identical_render_is_skipped_without_archive_or_write(tmp_path: Path) -> None:
    # NFR-05/NFR-07: repeated polls with no user change produce no writes and no
    # archive entries.
    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    _stored_canonical(state_dir)
    target = _surface(cursor_dir, "cursor")
    plan = SyncPlan(intents=(ProjectToTools(artifact_id=_ARTIFACT_ID, targets=(target,)),))
    observations = _observe(claude_dir, cursor_dir)
    state = _recorded_state(claude_dir, cursor_dir)
    execute_sync_plan(plan, observations, state, state_dir)
    first_bytes = (cursor_dir / "reviewer.md").read_bytes()

    result, _ = execute_sync_plan(plan, _observe(claude_dir, cursor_dir), state, state_dir)

    assert (cursor_dir / "reviewer.md").read_bytes() == first_bytes
    assert not (state_dir / "archive").exists()  # never archived a fresh/identical target
    assert result.changed == 0


def test_projecting_a_missing_canonical_fails_the_artifact(tmp_path: Path) -> None:
    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    target = _surface(cursor_dir, "cursor")
    plan = SyncPlan(intents=(ProjectToTools(artifact_id=_ARTIFACT_ID, targets=(target,)),))

    result, state = execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), _recorded_state(claude_dir, cursor_dir), state_dir
    )

    assert result.failed == (_ARTIFACT_ID,)
    assert not (cursor_dir / "reviewer.md").exists()


def test_a_failed_archive_abandons_the_intent_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # US-06 AC-6: if archiving the prior bytes fails, nothing is overwritten and
    # no state changes — the intent retries next poll.
    import shutil

    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    _stored_canonical(state_dir)
    (cursor_dir / "reviewer.md").write_text("user-authored prior\n")
    target = _surface(cursor_dir, "cursor")
    plan = SyncPlan(intents=(ProjectToTools(artifact_id=_ARTIFACT_ID, targets=(target,)),))
    prior_state = _recorded_state(claude_dir, cursor_dir)

    def failing_copy(src: Any, dst: Any, **kwargs: Any) -> None:
        raise OSError("archive disk full")

    monkeypatch.setattr(shutil, "copy2", failing_copy)
    result, state = execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), prior_state, state_dir
    )

    assert result.failed == (_ARTIFACT_ID,)
    assert (cursor_dir / "reviewer.md").read_text() == "user-authored prior\n"
    assert state == prior_state


def test_projecting_a_secret_bearing_canonical_is_blocked_before_any_write(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    cursor_dir = tmp_path / "cursor"
    cursor_dir.mkdir()
    save_canonical(
        state_dir,
        CanonicalDocument(
            artifact_id=_ARTIFACT_ID,
            kind="mcp_server",
            name="github",
            transport="stdio",
            command="npx",
            env={"GH_TOKEN": "hunter2"},
        ),
    )
    target = ToolSurface(
        "cursor",
        "mcp_server",
        cursor_dir / "mcp.json",
        SurfaceFormat(
            dialect="mcp_server",
            id_field="pair_id",
            map_key_path=("mcpServers",),
            file_format="json",
        ),
    )
    plan = SyncPlan(intents=(ProjectToTools(artifact_id=_ARTIFACT_ID, targets=(target,)),))

    result, _ = execute_sync_plan(plan, (), SyncState(), state_dir)

    assert result.blocked == (_ARTIFACT_ID,)
    assert not (cursor_dir / "mcp.json").exists()


def test_secrets_accepted_projects_the_literal_verbatim(tmp_path: Path) -> None:
    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    save_canonical(
        state_dir,
        CanonicalDocument(
            artifact_id=_ARTIFACT_ID, kind="agent", name="reviewer", body="sk-abcdefghij"
        ),
    )
    target = _surface(cursor_dir, "cursor")
    plan = SyncPlan(intents=(ProjectToTools(artifact_id=_ARTIFACT_ID, targets=(target,)),))

    result, _ = execute_sync_plan(
        plan,
        _observe(claude_dir, cursor_dir),
        _recorded_state(claude_dir, cursor_dir),
        state_dir,
        secret_policy_value=SECRET_POLICY_ACCEPTED,
    )

    assert result.changed == 1
    assert (cursor_dir / "reviewer.md").exists()


# --- reproject_canonical / rebuild_corrupt_canonical -------------------------------------


def test_reproject_renders_onto_every_recorded_and_observed_surface(tmp_path: Path) -> None:
    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    (cursor_dir / "reviewer.md").write_text(_agent_text(body="stale projection"))
    _stored_canonical(state_dir, name="reviewer")
    plan = SyncPlan(intents=(ReprojectCanonical(artifact_id=_ARTIFACT_ID),))

    result, state = execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), _recorded_state(claude_dir, cursor_dir), state_dir
    )

    assert "Be terse." in (claude_dir / "reviewer.md").read_text()
    assert "Be terse." in (cursor_dir / "reviewer.md").read_text()
    assert result.changed == 1


def test_rebuild_corrupt_canonical_saves_the_freshest_parse(tmp_path: Path) -> None:
    import os

    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    (cursor_dir / "reviewer.md").write_text(_agent_text(body="fresher content"))
    os.utime(claude_dir / "reviewer.md", (1_000_000, 1_000_000))
    os.utime(cursor_dir / "reviewer.md", (2_000_000, 2_000_000))
    plan = SyncPlan(intents=(RebuildCorruptCanonical(artifact_id=_ARTIFACT_ID),))

    result, state = execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), _recorded_state(claude_dir, cursor_dir), state_dir
    )

    stored = load_canonical(state_dir, _ARTIFACT_ID)
    assert isinstance(stored, CanonicalDocument)
    # the freshest surface won (US-09 AC-4); the store normalises the body's newline.
    assert stored.body == "fresher content\n"
    assert result.changed == 1
