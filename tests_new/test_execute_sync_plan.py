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
    # the recorded digest IS the observation's digest — anything else re-absorbs forever
    [claude_observation] = [o for o in observations if o.tool_surface.tool == "claude"]
    assert record.surfaces["claude"].content_digest == claude_observation.content_digest


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


def test_a_failing_intent_does_not_abort_the_rest_of_the_plan(tmp_path: Path) -> None:
    # Per-intent isolation: the first intent fails (no stored canonical), the second
    # succeeds, and changed aggregates across intents.
    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    other_id = "22222222-2222-4222-8222-222222222222"
    _stored_canonical(state_dir)  # only _ARTIFACT_ID has a canonical
    plan = SyncPlan(
        intents=(
            ProjectToTools(artifact_id=other_id, targets=(_surface(cursor_dir, "cursor", "x.md"),)),
            ProjectToTools(artifact_id=_ARTIFACT_ID, targets=(_surface(cursor_dir, "cursor"),)),
        )
    )

    result, _ = execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), _recorded_state(claude_dir, cursor_dir), state_dir
    )

    assert result.failed == (other_id,)
    assert result.changed == 1
    assert (cursor_dir / "reviewer.md").exists()  # the second intent ran


def test_a_projected_slot_reads_back_as_unchanged_next_poll(tmp_path: Path) -> None:
    # The keyed-map analogue of the no-churn invariant: the recorded SLOT digest
    # equals what the read phase observes after the write (NFR-05).
    from agents_sync.read_tool_surfaces import KeyedMapSurfaceSpec

    state_dir = tmp_path / "state"
    mcp_dir = tmp_path / "mcp"
    mcp_dir.mkdir()
    mcp_format = SurfaceFormat(
        dialect="mcp_server", id_field="pair_id", map_key_path=("mcpServers",), file_format="json"
    )
    (mcp_dir / "mcp.json").write_text(json.dumps({"mcpServers": {"gitlab": {"command": "glab"}}}))
    save_canonical(
        state_dir,
        CanonicalDocument(
            artifact_id=_ARTIFACT_ID,
            kind="mcp_server",
            name="github",
            transport="stdio",
            command="npx",
        ),
    )
    spec = KeyedMapSurfaceSpec("cursor", "mcp_server", mcp_dir / "mcp.json", mcp_format)
    from agents_sync.domain_model.tool_surface import KeyedMapSlot

    target = ToolSurface(
        "cursor", "mcp_server", KeyedMapSlot(file=mcp_dir / "mcp.json", slot="github"), mcp_format
    )
    plan = SyncPlan(intents=(ProjectToTools(artifact_id=_ARTIFACT_ID, targets=(target,)),))

    _, state = execute_sync_plan(plan, read_tool_surfaces((spec,)), SyncState(), state_dir)

    [reread] = [
        obs for obs in read_tool_surfaces((spec,)) if obs.tool_surface.location.slot == "github"
    ]
    assert reread.content_digest == state.records[_ARTIFACT_ID].surfaces["cursor"].content_digest


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
    assert "sk-abcdefghij" in (cursor_dir / "reviewer.md").read_text()  # verbatim, not redacted


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


# --- adopt_new_artifact (increment 2: the SOLE mint site) --------------------------------


def _candidate_text(name: str = "helper", body: str = "Help tersely.") -> str:
    return f"---\nname: {name}\n---\n{body}\n"  # id-less: a candidate


def test_adopt_mints_an_id_and_injects_it_into_every_group_surface(tmp_path: Path) -> None:
    from agents_sync.domain_model.artifact_identity import validate_artifact_id
    from agents_sync.domain_model.sync_plan import AdoptNewArtifact

    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    (claude_dir / "helper.md").write_text(_candidate_text())
    (cursor_dir / "helper.md").write_text(_candidate_text())
    plan = SyncPlan(
        intents=(
            AdoptNewArtifact(
                source=_surface(claude_dir, "claude", "helper.md"),
                others=(_surface(cursor_dir, "cursor", "helper.md"),),
            ),
        )
    )

    result, state = execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), SyncState(), state_dir
    )

    [minted_id] = [aid for aid in state.records if aid != _ARTIFACT_ID]
    validate_artifact_id(minted_id)  # a genuine UUIDv4 was minted
    assert minted_id in (claude_dir / "helper.md").read_text()  # id injected
    assert minted_id in (cursor_dir / "helper.md").read_text()
    assert isinstance(load_canonical(state_dir, minted_id), CanonicalDocument)
    assert result.changed == 1
    assert set(state.records[minted_id].surfaces) == {"claude", "cursor"}


def test_adopt_archives_the_pre_injection_bytes(tmp_path: Path) -> None:
    from agents_sync.domain_model.sync_plan import AdoptNewArtifact

    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    (claude_dir / "helper.md").write_text(_candidate_text())
    plan = SyncPlan(intents=(AdoptNewArtifact(source=_surface(claude_dir, "claude", "helper.md")),))

    _, state = execute_sync_plan(plan, _observe(claude_dir, cursor_dir), SyncState(), state_dir)

    [minted_id] = list(state.records)
    [entry] = list((state_dir / "archive" / minted_id / "claude").iterdir())
    assert entry.read_text() == _candidate_text()  # the user's pre-injection bytes


def test_two_adopts_mint_distinct_ids(tmp_path: Path) -> None:
    from agents_sync.domain_model.sync_plan import AdoptNewArtifact

    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    (claude_dir / "helper.md").write_text(_candidate_text("helper"))
    (claude_dir / "writer.md").write_text(_candidate_text("writer"))
    plan = SyncPlan(
        intents=(
            AdoptNewArtifact(source=_surface(claude_dir, "claude", "helper.md")),
            AdoptNewArtifact(source=_surface(claude_dir, "claude", "writer.md")),
        )
    )

    _, state = execute_sync_plan(plan, _observe(claude_dir, cursor_dir), SyncState(), state_dir)

    assert len(state.records) == 2  # two distinct minted ids


def test_adopting_a_secret_bearing_candidate_is_blocked_unminted(tmp_path: Path) -> None:
    from agents_sync.domain_model.sync_plan import AdoptNewArtifact
    from agents_sync.read_tool_surfaces import KeyedMapSurfaceSpec

    state_dir = tmp_path / "state"
    mcp_dir = tmp_path / "mcp"
    mcp_dir.mkdir()
    mcp_format = SurfaceFormat(
        dialect="mcp_server", id_field="pair_id", map_key_path=("mcpServers",), file_format="json"
    )
    (mcp_dir / "mcp.json").write_text(
        json.dumps({"mcpServers": {"github": {"command": "npx", "env": {"T": "hunter2"}}}})
    )
    observations = read_tool_surfaces(
        (KeyedMapSurfaceSpec("cursor", "mcp_server", mcp_dir / "mcp.json", mcp_format),)
    )
    plan = SyncPlan(intents=(AdoptNewArtifact(source=observations[0].tool_surface),))

    result, state = execute_sync_plan(plan, observations, SyncState(), state_dir)

    assert len(result.blocked) == 1
    assert state == SyncState()  # nothing recorded
    assert not (state_dir / "canonical").exists()  # nothing persisted


# --- absorb_into_managed ------------------------------------------------------------------


def test_absorb_into_managed_projects_the_managed_canonical_over_the_newcomer(
    tmp_path: Path,
) -> None:
    from agents_sync.domain_model.sync_plan import AbsorbIntoManaged

    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    _stored_canonical(state_dir)  # the managed artifact's truth
    (cursor_dir / "reviewer.md").write_text("---\nname: reviewer\n---\nnewcomer content\n")
    plan = SyncPlan(
        intents=(
            AbsorbIntoManaged(artifact_id=_ARTIFACT_ID, sources=(_surface(cursor_dir, "cursor"),)),
        )
    )

    result, state = execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), _recorded_state(claude_dir, cursor_dir), state_dir
    )

    written = (cursor_dir / "reviewer.md").read_text()
    assert "Be terse." in written  # managed wins (US-03 AC-6)
    assert _ARTIFACT_ID in written  # the existing id, no mint
    archive_dir = state_dir / "archive" / _ARTIFACT_ID / "cursor"
    [entry] = list(archive_dir.iterdir())
    assert "newcomer content" in entry.read_text()  # the new bytes preserved
    assert result.changed == 1


# --- rename_artifact ------------------------------------------------------------------------


def test_rename_relocates_every_projection_to_the_new_slug(tmp_path: Path) -> None:
    from agents_sync.domain_model.sync_plan import RenameArtifact

    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    (cursor_dir / "reviewer.md").write_text(_agent_text())
    _stored_canonical(state_dir)
    plan = SyncPlan(intents=(RenameArtifact(artifact_id=_ARTIFACT_ID, new_name="critic"),))

    result, state = execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), _recorded_state(claude_dir, cursor_dir), state_dir
    )

    assert not (claude_dir / "reviewer.md").exists()
    assert "critic" in (claude_dir / "critic.md").read_text()
    assert (cursor_dir / "critic.md").exists()
    stored = load_canonical(state_dir, _ARTIFACT_ID)
    assert isinstance(stored, CanonicalDocument)
    assert stored.name == "critic"
    record = state.records[_ARTIFACT_ID]
    assert record.name == "critic"
    assert record.surfaces["claude"].location == claude_dir / "critic.md"
    assert result.changed == 1


def test_a_failed_archive_aborts_a_multi_surface_rename_wholesale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # US-06 AC-6 for the identity family: with TWO surfaces to relocate, an archive
    # failure must leave BOTH untouched — never the first renamed and the second not.
    import shutil

    from agents_sync.domain_model.sync_plan import RenameArtifact

    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    (cursor_dir / "reviewer.md").write_text(_agent_text())
    _stored_canonical(state_dir)
    prior_state = _recorded_state(claude_dir, cursor_dir)
    plan = SyncPlan(intents=(RenameArtifact(artifact_id=_ARTIFACT_ID, new_name="critic"),))
    copies = {"allowed": 1}
    real_copy = shutil.copy2

    def second_copy_fails(src: Any, dst: Any, **kwargs: Any) -> Any:
        if copies["allowed"] <= 0:
            raise OSError("archive disk full")
        copies["allowed"] -= 1
        return real_copy(src, dst, **kwargs)

    monkeypatch.setattr(shutil, "copy2", second_copy_fails)
    result, state = execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), prior_state, state_dir
    )

    assert result.failed == (_ARTIFACT_ID,)
    assert (claude_dir / "reviewer.md").exists()  # neither surface was touched
    assert (cursor_dir / "reviewer.md").exists()
    assert not (claude_dir / "critic.md").exists()
    assert state == prior_state


def test_rename_relocates_a_slot_and_a_file_in_one_intent(tmp_path: Path) -> None:
    # Both relocation mechanisms (shared-file rewrite + new-file-plus-unlink) in
    # one transaction, one record update.
    from agents_sync.domain_model.sync_plan import RenameArtifact
    from agents_sync.domain_model.tool_surface import KeyedMapSlot
    from agents_sync.read_tool_surfaces import KeyedMapSurfaceSpec

    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    mcp_format = SurfaceFormat(
        dialect="mcp_server", id_field="pair_id", map_key_path=("mcpServers",), file_format="json"
    )
    (cursor_dir / "mcp.json").write_text(
        json.dumps({"mcpServers": {"reviewer": {"pair_id": _ARTIFACT_ID, "command": "npx"}}})
    )
    save_canonical(
        state_dir,
        CanonicalDocument(
            artifact_id=_ARTIFACT_ID,
            kind="mcp_server",
            name="reviewer",
            transport="stdio",
            command="npx",
        ),
    )
    observations = read_tool_surfaces(
        (
            _spec(claude_dir, "claude"),
            KeyedMapSurfaceSpec("cursor", "mcp_server", cursor_dir / "mcp.json", mcp_format),
        )
    )
    state = SyncState(
        records={
            _ARTIFACT_ID: ArtifactRecord(
                name="reviewer",
                surfaces={
                    "claude": RecordedSurface(location=claude_dir / "reviewer.md"),
                    "cursor": RecordedSurface(
                        location=KeyedMapSlot(file=cursor_dir / "mcp.json", slot="reviewer")
                    ),
                },
            )
        }
    )
    plan = SyncPlan(intents=(RenameArtifact(artifact_id=_ARTIFACT_ID, new_name="critic"),))

    result, new_state = execute_sync_plan(plan, observations, state, state_dir)

    assert (claude_dir / "critic.md").exists() and not (claude_dir / "reviewer.md").exists()
    stored_map = json.loads((cursor_dir / "mcp.json").read_text())["mcpServers"]
    assert "critic" in stored_map and "reviewer" not in stored_map
    record = new_state.records[_ARTIFACT_ID]
    assert record.surfaces["claude"].location == claude_dir / "critic.md"
    assert record.surfaces["cursor"].location == KeyedMapSlot(
        file=cursor_dir / "mcp.json", slot="critic"
    )
    assert result.changed == 1


def test_rename_archives_the_old_surfaces(tmp_path: Path) -> None:
    from agents_sync.domain_model.sync_plan import RenameArtifact

    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    _stored_canonical(state_dir)
    plan = SyncPlan(intents=(RenameArtifact(artifact_id=_ARTIFACT_ID, new_name="critic"),))

    execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), _recorded_state(claude_dir, cursor_dir), state_dir
    )

    archive_dir = state_dir / "archive" / _ARTIFACT_ID / "claude"
    [entry] = list(archive_dir.iterdir())
    assert entry.read_text() == _agent_text()  # old-slug bytes preserved (US-04)


def test_rename_moves_a_keyed_map_slot_preserving_siblings(tmp_path: Path) -> None:
    from agents_sync.domain_model.sync_plan import RenameArtifact
    from agents_sync.domain_model.tool_surface import KeyedMapSlot
    from agents_sync.read_tool_surfaces import KeyedMapSurfaceSpec

    state_dir = tmp_path / "state"
    mcp_dir = tmp_path / "mcp"
    mcp_dir.mkdir()
    mcp_format = SurfaceFormat(
        dialect="mcp_server", id_field="pair_id", map_key_path=("mcpServers",), file_format="json"
    )
    (mcp_dir / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {"pair_id": _ARTIFACT_ID, "command": "npx"},
                    "gitlab": {"command": "glab"},
                }
            }
        )
    )
    save_canonical(
        state_dir,
        CanonicalDocument(
            artifact_id=_ARTIFACT_ID,
            kind="mcp_server",
            name="github",
            transport="stdio",
            command="npx",
        ),
    )
    observations = read_tool_surfaces(
        (KeyedMapSurfaceSpec("cursor", "mcp_server", mcp_dir / "mcp.json", mcp_format),)
    )
    state = SyncState(
        records={
            _ARTIFACT_ID: ArtifactRecord(
                name="github",
                surfaces={
                    "cursor": RecordedSurface(
                        location=KeyedMapSlot(file=mcp_dir / "mcp.json", slot="github")
                    )
                },
            )
        }
    )
    plan = SyncPlan(intents=(RenameArtifact(artifact_id=_ARTIFACT_ID, new_name="hub"),))

    result, new_state = execute_sync_plan(plan, observations, state, state_dir)

    stored_map = json.loads((mcp_dir / "mcp.json").read_text())["mcpServers"]
    assert "github" not in stored_map
    assert stored_map["hub"]["command"] == "npx"
    assert stored_map["gitlab"] == {"command": "glab"}  # sibling untouched
    assert result.changed == 1


# --- remove_artifact -------------------------------------------------------------------------


def test_remove_archives_and_deletes_the_surviving_projections(tmp_path: Path) -> None:
    from agents_sync.domain_model.sync_plan import RemoveArtifact

    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    (cursor_dir / "reviewer.md").write_text(_agent_text())
    _stored_canonical(state_dir)
    plan = SyncPlan(intents=(RemoveArtifact(artifact_id=_ARTIFACT_ID),))

    result, state = execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), _recorded_state(claude_dir, cursor_dir), state_dir
    )

    assert not (claude_dir / "reviewer.md").exists()
    assert not (cursor_dir / "reviewer.md").exists()
    assert _ARTIFACT_ID not in state.records  # the record is gone
    claude_entries = list((state_dir / "archive" / _ARTIFACT_ID / "claude").iterdir())
    assert len(claude_entries) == 1  # bytes preserved (NFR-01)
    assert result.changed == 1


def test_remove_archives_the_canonical_under_the_reserved_side(tmp_path: Path) -> None:
    from agents_sync.domain_model.sync_plan import RemoveArtifact

    state_dir, claude_dir, cursor_dir = _workspace(tmp_path)
    _stored_canonical(state_dir)
    plan = SyncPlan(intents=(RemoveArtifact(artifact_id=_ARTIFACT_ID),))

    execute_sync_plan(
        plan, _observe(claude_dir, cursor_dir), _recorded_state(claude_dir, cursor_dir), state_dir
    )

    assert load_canonical(state_dir, _ARTIFACT_ID) is None  # never re-projected (NFR-16)
    [entry] = list((state_dir / "archive" / _ARTIFACT_ID / "_canonical").iterdir())
    assert _ARTIFACT_ID in entry.read_text()  # the canonical's bytes preserved (US-05 AC-5)


def test_remove_deletes_a_keyed_map_slot_preserving_siblings(tmp_path: Path) -> None:
    from agents_sync.domain_model.sync_plan import RemoveArtifact
    from agents_sync.domain_model.tool_surface import KeyedMapSlot
    from agents_sync.read_tool_surfaces import KeyedMapSurfaceSpec

    state_dir = tmp_path / "state"
    mcp_dir = tmp_path / "mcp"
    mcp_dir.mkdir()
    mcp_format = SurfaceFormat(
        dialect="mcp_server", id_field="pair_id", map_key_path=("mcpServers",), file_format="json"
    )
    (mcp_dir / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {"pair_id": _ARTIFACT_ID, "command": "npx"},
                    "gitlab": {"command": "glab"},
                }
            }
        )
    )
    observations = read_tool_surfaces(
        (KeyedMapSurfaceSpec("cursor", "mcp_server", mcp_dir / "mcp.json", mcp_format),)
    )
    state = SyncState(
        records={
            _ARTIFACT_ID: ArtifactRecord(
                name="github",
                surfaces={
                    "cursor": RecordedSurface(
                        location=KeyedMapSlot(file=mcp_dir / "mcp.json", slot="github")
                    )
                },
            )
        }
    )
    plan = SyncPlan(intents=(RemoveArtifact(artifact_id=_ARTIFACT_ID),))

    result, new_state = execute_sync_plan(plan, observations, state, state_dir)

    stored_map = json.loads((mcp_dir / "mcp.json").read_text())["mcpServers"]
    assert "github" not in stored_map
    assert stored_map["gitlab"] == {"command": "glab"}  # sibling untouched
    [entry] = list((state_dir / "archive" / _ARTIFACT_ID / "cursor").iterdir())
    # the archive entry is the SLOT's recoverable fragment, not a whole-file dump
    archived_fragment = json.loads(entry.read_text())
    assert archived_fragment == {"pair_id": _ARTIFACT_ID, "command": "npx"}
    assert "gitlab" not in entry.read_text()
    assert _ARTIFACT_ID not in new_state.records
