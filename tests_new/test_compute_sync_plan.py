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
    AbsorbToolEdit,
    AdoptNewArtifact,
    FreezeArtifact,
    ProjectToTools,
    RebuildCorruptCanonical,
    RemoveArtifact,
    RenameArtifact,
)
from agents_sync.domain_model.sync_state import ArtifactRecord, RecordedSurface, SyncState
from agents_sync.domain_model.tool_surface import SurfaceFormat, ToolSurface

_ID_X = "11111111-1111-4111-8111-111111111111"
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
    name: str = "reviewer",
    modified_time: float = 10.0,
    parsed: CanonicalDocument | ParseFailure | None = None,
) -> SurfaceObservation:
    # A managed surface carries the recovered id; its parsed canonical defaults to a
    # well-formed document whose name matches the recorded name (no spurious rename).
    canonical: CanonicalDocument | ParseFailure
    canonical = parsed if parsed is not None else CanonicalDocument(_ID_X, "agent", name=name)
    return SurfaceObservation(
        tool_surface=_surface(tool, name),
        embedded_id=_ID_X,
        content_digest=content_digest,
        modified_time=modified_time,
        parsed=canonical,
    )


def _candidate(tool: str, name: str) -> SurfaceObservation:
    # An id-less surface whose parsed canonical supplies the (kind, slug) to group by.
    return SurfaceObservation(
        tool_surface=_surface(tool, name),
        embedded_id=None,
        content_digest="cand",
        modified_time=10.0,
        parsed=CanonicalDocument(_PLACEHOLDER_ID, "agent", name=name),
    )


def _state(name: str = "reviewer", **recorded_digest_by_tool: str) -> SyncState:
    record = ArtifactRecord(
        name=name,
        surfaces={
            tool: RecordedSurface(location=_surface(tool, name).location, content_digest=digest)
            for tool, digest in recorded_digest_by_tool.items()
        },
    )
    return SyncState(records={_ID_X: record})


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
