"""Unit tests for the planner capstone — compute_sync_plan assembly + two-tool guard (rebuild S8a).

`compute_sync_plan` (proposal §7) assembles the whole `SyncPlan` from the three
shipped pure steps — `recover_identity` → `reconcile_known` (per managed artifact,
threading each artifact's stored canonical) → `adopt_candidates` — and then applies
the two-tool guard: fewer than two available tools → drop every destructive intent
(adopt / project / rename / remove), so a degenerate one-tool poll performs nothing
destructive (US-07 AC-5). The key-conflict and glitch downgrades are S8b/S8c. Pure
in-memory tests: no filesystem, no clock, no mocks.
"""

from __future__ import annotations

from pathlib import Path

from agents_sync.domain_model.canonical_document import CanonicalDocument, CorruptCanonical
from agents_sync.domain_model.observation import ParseFailure, SurfaceObservation
from agents_sync.domain_model.plan.compute_sync_plan import compute_sync_plan
from agents_sync.domain_model.sync_plan import (
    AbsorbIntoManaged,
    AbsorbToolEdit,
    AdoptNewArtifact,
    FreezeArtifact,
    ProjectToTools,
    RebuildCorruptCanonical,
    RejectCollision,
    RemoveArtifact,
    RenameArtifact,
    ReportUnadoptable,
)
from agents_sync.domain_model.sync_state import ArtifactRecord, RecordedSurface, SyncState
from agents_sync.domain_model.tool_surface import SurfaceFormat, ToolSurface

_ID_X = "11111111-1111-4111-8111-111111111111"
_ID_Y = "22222222-2222-4222-9222-222222222222"
_ID_Z = "33333333-3333-4333-8333-333333333333"
_PLACEHOLDER_ID = "00000000-0000-4000-8000-000000000000"
_MARKDOWN = SurfaceFormat(dialect="markdown_frontmatter")
_TWO_TOOLS = 2
_ONE_TOOL = 1


def _surface(tool: str, name: str = "reviewer") -> ToolSurface:
    return ToolSurface(
        tool=tool,
        kind="agent",
        location=Path(f"/u/.{tool}/agents/{name}.md"),
        surface_format=_MARKDOWN,
    )


def _managed(
    tool: str,
    content_digest: str,
    *,
    artifact_id: str = _ID_X,
    name: str = "reviewer",
    modified_time: float = 10.0,
    parsed: CanonicalDocument | ParseFailure | None = None,
) -> SurfaceObservation:
    # A managed surface carries the recovered id; its parsed canonical defaults to a
    # well-formed document whose name matches the recorded name (no spurious rename).
    canonical: CanonicalDocument | ParseFailure
    canonical = parsed if parsed is not None else CanonicalDocument(artifact_id, "agent", name=name)
    return SurfaceObservation(
        tool_surface=_surface(tool, name),
        embedded_id=artifact_id,
        content_digest=content_digest,
        modified_time=modified_time,
        parsed=canonical,
    )


def _candidate(
    tool: str,
    name: str = "reviewer",
    *,
    modified_time: float = 10.0,
    parsed: CanonicalDocument | ParseFailure | None = None,
) -> SurfaceObservation:
    # An id-less surface; its parsed canonical supplies the (kind, slug) to group by.
    canonical: CanonicalDocument | ParseFailure
    canonical = (
        parsed if parsed is not None else CanonicalDocument(_PLACEHOLDER_ID, "agent", name=name)
    )
    return SurfaceObservation(
        tool_surface=_surface(tool, name),
        embedded_id=None,
        content_digest="cand",
        modified_time=modified_time,
        parsed=canonical,
    )


def _record(name: str = "reviewer", **recorded_digest_by_tool: str) -> ArtifactRecord:
    return ArtifactRecord(
        name=name,
        surfaces={
            tool: RecordedSurface(location=_surface(tool, name).location, content_digest=digest)
            for tool, digest in recorded_digest_by_tool.items()
        },
    )


def _state(name: str = "reviewer", **recorded_digest_by_tool: str) -> SyncState:
    return SyncState(records={_ID_X: _record(name, **recorded_digest_by_tool)})


# --- assembly: the three shipped steps wired into one SyncPlan -------------------


def test_assembles_a_managed_conflict_into_absorb_plus_project() -> None:
    # claude edited (digest moved), codex unchanged -> absorb the winner, project the rest.
    observations = [
        _managed("claude", content_digest="new", modified_time=20.0),
        _managed("codex", content_digest="old", modified_time=10.0),
    ]

    plan = compute_sync_plan(observations, _state(claude="old", codex="old"), {}, _TWO_TOOLS)

    assert plan.intents == (
        AbsorbToolEdit(_ID_X, _surface("claude")),
        ProjectToTools(_ID_X, (_surface("codex"),)),
    )


def test_assembles_an_id_less_candidate_into_an_adoption() -> None:
    candidate = _candidate("claude", name="newhelper")

    plan = compute_sync_plan([candidate], SyncState(), {}, _TWO_TOOLS)

    assert plan.intents == (AdoptNewArtifact(candidate.tool_surface, ()),)


def test_assembles_managed_and_candidate_pipelines_together() -> None:
    # A managed edit and an unrelated new candidate are both planned, independently.
    managed_edit = _managed("claude", content_digest="new")
    candidate = _candidate("codex", name="newhelper")

    plan = compute_sync_plan([managed_edit, candidate], _state(claude="old"), {}, _TWO_TOOLS)

    assert AbsorbToolEdit(_ID_X, _surface("claude")) in plan.intents
    assert AdoptNewArtifact(candidate.tool_surface, ()) in plan.intents
    assert len(plan.intents) == 2


def test_threads_each_artifacts_stored_canonical_into_reconciliation() -> None:
    # An unchanged managed artifact whose STORED canonical is corrupt must rebuild —
    # only reachable if compute_sync_plan passes stored_canonicals to reconcile_known.
    observation = _managed("claude", content_digest="same")

    plan = compute_sync_plan(
        [observation], _state(claude="same"), {_ID_X: CorruptCanonical()}, _TWO_TOOLS
    )

    assert plan.intents == (RebuildCorruptCanonical(_ID_X),)


def test_an_unchanged_managed_artifact_yields_an_empty_plan() -> None:
    observation = _managed("claude", content_digest="same")

    plan = compute_sync_plan([observation], _state(claude="same"), {}, _TWO_TOOLS)

    assert plan.intents == ()


def test_a_managed_id_absent_from_state_does_not_crash() -> None:
    # A file carrying a valid id unknown to state, with no stored canonical, is a
    # plan-time no-op (orphan handling is the read phase / executor's job, not S8a's).
    observation = _managed("claude", content_digest="x")

    plan = compute_sync_plan([observation], SyncState(), {}, _TWO_TOOLS)

    assert plan.intents == ()


def test_an_orphan_id_with_a_corrupt_canonical_still_reaches_reconciliation() -> None:
    # The id is unknown to state but its stored canonical is corrupt -> rebuild. Proves
    # the default-record fallback threads the orphan through reconcile_known — the empty
    # plan above is a deliberate no-op (nothing to do), not the artifact being dropped.
    observation = _managed("claude", content_digest="x")

    plan = compute_sync_plan(
        [observation], SyncState(), {_ID_X: CorruptCanonical()}, _TWO_TOOLS
    )

    assert plan.intents == (RebuildCorruptCanonical(_ID_X),)


# --- the two-tool guard: US-07 AC-5 ---------------------------------------------


def test_two_tool_guard_drops_adoption_below_two_available_tools() -> None:
    candidate = _candidate("claude", name="newhelper")

    plan = compute_sync_plan([candidate], SyncState(), {}, _ONE_TOOL)

    assert plan.intents == ()


def test_destructive_intents_survive_at_exactly_two_available_tools() -> None:
    # Boundary: two available tools is the threshold at which destructive work runs.
    candidate = _candidate("claude", name="newhelper")

    plan = compute_sync_plan([candidate], SyncState(), {}, _TWO_TOOLS)

    assert plan.intents == (AdoptNewArtifact(candidate.tool_surface, ()),)


def test_two_tool_guard_drops_projection_but_keeps_the_absorb() -> None:
    # Folding an edit into the canonical is not destructive; projecting it outward is.
    observations = [
        _managed("claude", content_digest="new", modified_time=20.0),
        _managed("codex", content_digest="old", modified_time=10.0),
    ]

    plan = compute_sync_plan(observations, _state(claude="old", codex="old"), {}, _ONE_TOOL)

    assert plan.intents == (AbsorbToolEdit(_ID_X, _surface("claude")),)


def test_a_rename_is_planned_when_two_tools_are_available() -> None:
    # The canonical's name moved -> absorb the edit and rename the projections.
    renamed = _managed(
        "claude",
        content_digest="new",
        parsed=CanonicalDocument(_ID_X, "agent", name="auditor"),
    )

    plan = compute_sync_plan([renamed], _state(name="reviewer", claude="old"), {}, _TWO_TOOLS)

    assert plan.intents == (
        AbsorbToolEdit(_ID_X, _surface("claude")),
        RenameArtifact(_ID_X, "auditor"),
    )


def test_two_tool_guard_drops_the_rename_but_keeps_the_absorb() -> None:
    # Contrast with the two-tool case above: below two tools the rename is dropped.
    renamed = _managed(
        "claude",
        content_digest="new",
        parsed=CanonicalDocument(_ID_X, "agent", name="auditor"),
    )

    plan = compute_sync_plan([renamed], _state(name="reviewer", claude="old"), {}, _ONE_TOOL)

    assert plan.intents == (AbsorbToolEdit(_ID_X, _surface("claude")),)


def test_a_removal_is_planned_when_two_tools_are_available() -> None:
    # codex was recorded but is absent this poll -> the artifact's removal is planned.
    observations = [_managed("claude", content_digest="same")]

    plan = compute_sync_plan(observations, _state(claude="same", codex="same"), {}, _TWO_TOOLS)

    assert plan.intents == (RemoveArtifact(_ID_X),)


def test_two_tool_guard_drops_the_removal() -> None:
    # Contrast with the two-tool case above: below two tools the removal is dropped.
    observations = [_managed("claude", content_digest="same")]

    plan = compute_sync_plan(observations, _state(claude="same", codex="same"), {}, _ONE_TOOL)

    assert plan.intents == ()


def test_two_tool_guard_keeps_a_freeze() -> None:
    # A malformed managed artifact is frozen, not destructive -> survives a one-tool poll.
    malformed = _managed("claude", content_digest="new", parsed=ParseFailure(reason="bad yaml"))

    plan = compute_sync_plan([malformed], _state(claude="old"), {}, _ONE_TOOL)

    assert plan.intents == (FreezeArtifact(_ID_X),)


# --- the collision guard: US-03 AC-8 + US-04 AC-5 -------------------------------


def test_two_managed_artifacts_at_one_key_are_rejected() -> None:
    # Different ids resolving to the same (kind, slug) — a slug collision that should
    # not exist; the rejection is emitted naming both ids (US-03 AC-8). (The sibling
    # test below proves any pending intents are also dropped.)
    observations = [
        _managed("claude", content_digest="same", artifact_id=_ID_X),
        _managed("codex", content_digest="same", artifact_id=_ID_Y),
    ]
    state = SyncState(records={_ID_X: _record(claude="same"), _ID_Y: _record(codex="same")})

    plan = compute_sync_plan(observations, state, {}, _TWO_TOOLS)

    assert plan.intents == (RejectCollision((_ID_X, _ID_Y), ("agent", "reviewer")),)


def test_a_collision_drops_the_colliding_artifacts_pending_intents() -> None:
    # Both colliding artifacts had pending edits; rejection removes them so nothing
    # destructive is planned for either — "left untouched" (US-03 AC-8).
    observations = [
        _managed("claude", content_digest="new", artifact_id=_ID_X),
        _managed("codex", content_digest="new", artifact_id=_ID_Y),
    ]
    state = SyncState(records={_ID_X: _record(claude="old"), _ID_Y: _record(codex="old")})

    plan = compute_sync_plan(observations, state, {}, _TWO_TOOLS)

    assert plan.intents == (RejectCollision((_ID_X, _ID_Y), ("agent", "reviewer")),)


def test_a_rename_creating_a_slug_clash_is_rejected() -> None:
    # X renames to 'auditor'; Y already occupies 'auditor' — the rename creates the
    # collision, so it is rejected and no rename happens (US-04 AC-5).
    observations = [
        _managed(
            "claude",
            content_digest="new",
            artifact_id=_ID_X,
            parsed=CanonicalDocument(_ID_X, "agent", name="auditor"),
        ),
        _managed("codex", content_digest="same", artifact_id=_ID_Y, name="auditor"),
    ]
    state = SyncState(
        records={
            _ID_X: _record(name="reviewer", claude="old"),
            _ID_Y: _record(name="auditor", codex="same"),
        }
    )

    plan = compute_sync_plan(observations, state, {}, _TWO_TOOLS)

    assert plan.intents == (RejectCollision((_ID_X, _ID_Y), ("agent", "auditor")),)


def test_managed_artifacts_at_distinct_keys_are_not_rejected() -> None:
    # Different slugs -> no collision; each artifact's plan is left untouched.
    observations = [
        _managed("claude", content_digest="new", artifact_id=_ID_X, name="reviewer"),
        _managed("codex", content_digest="same", artifact_id=_ID_Y, name="auditor"),
    ]
    state = SyncState(
        records={
            _ID_X: _record(name="reviewer", claude="old"),
            _ID_Y: _record(name="auditor", codex="same"),
        }
    )

    plan = compute_sync_plan(observations, state, {}, _TWO_TOOLS)

    assert plan.intents == (AbsorbToolEdit(_ID_X, _surface("claude")),)


def test_a_collision_leaves_non_colliding_artifacts_untouched() -> None:
    # X and Y collide on 'reviewer'; Z at a distinct key has a pending edit that must
    # survive — the rejection is scoped to the colliding set, not the whole poll.
    observations = [
        _managed("claude", content_digest="same", artifact_id=_ID_X),
        _managed("codex", content_digest="same", artifact_id=_ID_Y),
        _managed("cursor", content_digest="new", artifact_id=_ID_Z, name="auditor"),
    ]
    state = SyncState(
        records={
            _ID_X: _record(claude="same"),
            _ID_Y: _record(codex="same"),
            _ID_Z: _record(name="auditor", cursor="old"),
        }
    )

    plan = compute_sync_plan(observations, state, {}, _TWO_TOOLS)

    assert plan.intents == (
        AbsorbToolEdit(_ID_Z, _surface("cursor", "auditor")),
        RejectCollision((_ID_X, _ID_Y), ("agent", "reviewer")),
    )


def test_three_managed_artifacts_at_one_key_are_named_in_sorted_order() -> None:
    # Three-way collision; the colliding ids are reported in deterministic sorted order
    # regardless of the order their observations arrived in (here: descending Z, Y, X).
    observations = [
        _managed("cursor", content_digest="same", artifact_id=_ID_Z),
        _managed("codex", content_digest="same", artifact_id=_ID_Y),
        _managed("claude", content_digest="same", artifact_id=_ID_X),
    ]
    state = SyncState(
        records={
            _ID_Z: _record(cursor="same"),
            _ID_Y: _record(codex="same"),
            _ID_X: _record(claude="same"),
        }
    )

    plan = compute_sync_plan(observations, state, {}, _TWO_TOOLS)

    assert plan.intents == (RejectCollision((_ID_X, _ID_Y, _ID_Z), ("agent", "reviewer")),)


def test_a_collision_is_reported_even_below_two_available_tools() -> None:
    # reject_collision is a structured error, not a destructive op — the two-tool
    # guard does not suppress it.
    observations = [
        _managed("claude", content_digest="same", artifact_id=_ID_X),
        _managed("codex", content_digest="same", artifact_id=_ID_Y),
    ]
    state = SyncState(records={_ID_X: _record(claude="same"), _ID_Y: _record(codex="same")})

    plan = compute_sync_plan(observations, state, {}, _ONE_TOOL)

    assert plan.intents == (RejectCollision((_ID_X, _ID_Y), ("agent", "reviewer")),)


def test_orphan_ids_at_one_key_are_not_a_collision() -> None:
    # Ids unknown to state are not 'already-managed' artifacts; they do not collide
    # (and produce no intents) — only state-managed artifacts participate (US-03 AC-8).
    observations = [
        _managed("claude", content_digest="x", artifact_id=_ID_X),
        _managed("codex", content_digest="x", artifact_id=_ID_Y),
    ]

    plan = compute_sync_plan(observations, SyncState(), {}, _TWO_TOOLS)

    assert plan.intents == ()


# --- the absorb-into-managed guard: US-03 AC-6 ----------------------------------


def test_a_candidate_matching_a_managed_key_absorbs_into_it() -> None:
    # A new id-less artifact at an already-managed artifact's key: managed wins, the new
    # bytes absorb under the existing id, no mint (US-03 AC-6).
    managed = _managed("claude", content_digest="same", artifact_id=_ID_X, name="reviewer")
    candidate = _candidate("codex", name="reviewer")
    state = _state(name="reviewer", claude="same")

    plan = compute_sync_plan([managed, candidate], state, {}, _TWO_TOOLS)

    assert plan.intents == (AbsorbIntoManaged(_ID_X, (candidate.tool_surface,)),)


def test_a_candidate_at_a_distinct_key_is_still_adopted() -> None:
    # No managed artifact shares its key -> it remains a fresh adoption, not an absorb.
    managed = _managed("claude", content_digest="same", artifact_id=_ID_X, name="reviewer")
    candidate = _candidate("codex", name="newhelper")
    state = _state(name="reviewer", claude="same")

    plan = compute_sync_plan([managed, candidate], state, {}, _TWO_TOOLS)

    assert plan.intents == (AdoptNewArtifact(candidate.tool_surface, ()),)


def test_a_candidate_group_absorbs_all_its_surfaces_into_the_managed_id() -> None:
    # An id-less duplicate on two tools at a managed key absorbs the whole group's bytes.
    managed = _managed("claude", content_digest="same", artifact_id=_ID_X, name="reviewer")
    winner = _candidate("codex", name="reviewer", modified_time=20.0)
    loser = _candidate("cursor", name="reviewer", modified_time=10.0)
    state = _state(name="reviewer", claude="same")

    plan = compute_sync_plan([managed, winner, loser], state, {}, _TWO_TOOLS)

    assert plan.intents == (
        AbsorbIntoManaged(_ID_X, (winner.tool_surface, loser.tool_surface)),
    )


def test_a_candidate_at_a_colliding_key_is_not_absorbed() -> None:
    # The managed side is ambiguous (two ids collide on the key, so it is rejected); the
    # candidate cannot absorb into an ambiguous target and stays a fresh adoption.
    observations = [
        _managed("claude", content_digest="same", artifact_id=_ID_X),
        _managed("codex", content_digest="same", artifact_id=_ID_Y),
        _candidate("cursor", name="reviewer"),
    ]
    state = SyncState(records={_ID_X: _record(claude="same"), _ID_Y: _record(codex="same")})

    plan = compute_sync_plan(observations, state, {}, _TWO_TOOLS)

    assert plan.intents == (
        RejectCollision((_ID_X, _ID_Y), ("agent", "reviewer")),
        AdoptNewArtifact(observations[2].tool_surface, ()),
    )


def test_an_unparseable_candidate_passes_through_the_absorb_guard() -> None:
    # ReportUnadoptable is not an adoption, so the absorb guard leaves it untouched.
    managed = _managed("claude", content_digest="same", artifact_id=_ID_X, name="reviewer")
    unparseable = _candidate("codex", parsed=ParseFailure(reason="bad yaml"))
    state = _state(name="reviewer", claude="same")

    plan = compute_sync_plan([managed, unparseable], state, {}, _TWO_TOOLS)

    assert plan.intents == (ReportUnadoptable(unparseable.tool_surface),)


def test_two_tool_guard_drops_an_absorb_into_managed() -> None:
    # absorb_into_managed projects the managed canonical outward -> destructive; dropped
    # below two available tools (US-07 AC-5).
    managed = _managed("claude", content_digest="same", artifact_id=_ID_X, name="reviewer")
    candidate = _candidate("codex", name="reviewer")
    state = _state(name="reviewer", claude="same")

    plan = compute_sync_plan([managed, candidate], state, {}, _ONE_TOOL)

    assert plan.intents == ()
