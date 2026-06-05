"""Unit tests for the content reconciliation rule (rebuild S6a).

`reconcile_known` is the common-case planner decision for one already-managed
artifact (proposal §7.2): freeze if it won't parse (FR-11); else digest-detect the
changed surfaces, absorb the freshest (highest `modified_time`, alphabetical
tiebreak — US-06 AC-4) and project the canonical onto the other surfaces (US-01);
else unchanged. This step builds only the content rule — the surface-shape guards
(rename/remove/glitch/mv) and canonical-authority cases land in S6b/S6c. Pure
in-memory tests: no filesystem, no clock, no mocks.
"""

from __future__ import annotations

from pathlib import Path

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.observation import ParseFailure, SurfaceObservation
from agents_sync.domain_model.plan.reconcile_known import reconcile_known
from agents_sync.domain_model.sync_plan import AbsorbToolEdit, FreezeArtifact, ProjectToTools
from agents_sync.domain_model.sync_state import ArtifactRecord, RecordedSurface
from agents_sync.domain_model.tool_surface import SurfaceFormat, ToolSurface

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
_MARKDOWN = SurfaceFormat(dialect="markdown_frontmatter")
_PARSED = CanonicalDocument(artifact_id=_ARTIFACT_ID, kind="agent", name="reviewer")


def _surface(tool: str) -> ToolSurface:
    return ToolSurface(
        tool=tool,
        kind="agent",
        location=Path(f"/u/.{tool}/agents/reviewer.md"),
        surface_format=_MARKDOWN,
    )


def _observed(
    tool: str,
    content_digest: str,
    modified_time: float,
    parsed: CanonicalDocument | ParseFailure = _PARSED,
) -> SurfaceObservation:
    return SurfaceObservation(
        tool_surface=_surface(tool),
        content_digest=content_digest,
        modified_time=modified_time,
        parsed=parsed,
    )


def _record(**recorded_digest_by_tool: str) -> ArtifactRecord:
    return ArtifactRecord(
        surfaces={
            tool: RecordedSurface(location=_surface(tool).location, content_digest=digest)
            for tool, digest in recorded_digest_by_tool.items()
        }
    )


def test_an_unparseable_surface_freezes_the_artifact() -> None:
    # FR-11: a managed artifact whose content won't parse is frozen — not synced,
    # and (crucially) no other intent is emitted for it this poll.
    observation = _observed("claude", "d1", 10.0, parsed=ParseFailure(reason="bad yaml"))

    intents = reconcile_known(_ARTIFACT_ID, [observation], _record(claude="d0"))

    assert intents == (FreezeArtifact(_ARTIFACT_ID),)


def test_no_changed_surface_yields_no_intent() -> None:
    observation = _observed("claude", "unchanged", 10.0)

    intents = reconcile_known(_ARTIFACT_ID, [observation], _record(claude="unchanged"))

    assert intents == ()


def test_one_changed_surface_absorbs_it_and_projects_to_the_peers() -> None:
    # US-01: an edit on one tool propagates to the others — including a peer whose
    # own digest did not move, because the canonical advances past it.
    edited = _observed("claude", "new", 20.0)
    untouched_peer = _observed("codex", "unchanged", 5.0)

    intents = reconcile_known(
        _ARTIFACT_ID,
        [edited, untouched_peer],
        _record(claude="old", codex="unchanged"),
    )

    assert intents == (
        AbsorbToolEdit(_ARTIFACT_ID, edited.tool_surface),
        ProjectToTools(_ARTIFACT_ID, (untouched_peer.tool_surface,)),
    )


def test_a_single_surface_change_absorbs_without_an_empty_projection() -> None:
    edited = _observed("claude", "new", 20.0)

    intents = reconcile_known(_ARTIFACT_ID, [edited], _record(claude="old"))

    assert intents == (AbsorbToolEdit(_ARTIFACT_ID, edited.tool_surface),)


def test_a_conflict_absorbs_the_freshest_change_and_projects_the_loser() -> None:
    # US-06: two surfaces changed — the most-recently-modified wins, the other is
    # overwritten (it is simply among the projection targets).
    older_change = _observed("claude", "claude-new", 10.0)
    fresher_change = _observed("codex", "codex-new", 20.0)

    intents = reconcile_known(
        _ARTIFACT_ID,
        [older_change, fresher_change],
        _record(claude="claude-old", codex="codex-old"),
    )

    assert intents == (
        AbsorbToolEdit(_ARTIFACT_ID, fresher_change.tool_surface),
        ProjectToTools(_ARTIFACT_ID, (older_change.tool_surface,)),
    )


def test_a_three_way_conflict_projects_every_loser() -> None:
    # Three surfaces changed: the freshest wins; both losers are projected, in
    # observation order, the winner excluded exactly once.
    oldest = _observed("claude", "claude-new", 10.0)
    middle = _observed("codex", "codex-new", 15.0)
    freshest = _observed("gemini", "gemini-new", 20.0)

    intents = reconcile_known(
        _ARTIFACT_ID,
        [oldest, middle, freshest],
        _record(claude="claude-old", codex="codex-old", gemini="gemini-old"),
    )

    assert intents == (
        AbsorbToolEdit(_ARTIFACT_ID, freshest.tool_surface),
        ProjectToTools(_ARTIFACT_ID, (oldest.tool_surface, middle.tool_surface)),
    )


def test_a_freeze_suppresses_intents_for_the_other_changed_surfaces() -> None:
    # FR-11 short-circuit: one surface won't parse, so the artifact is frozen and no
    # absorb/project is emitted, even though a sibling surface genuinely changed.
    unparseable = _observed("claude", "d1", 30.0, parsed=ParseFailure(reason="bad yaml"))
    changed_sibling = _observed("codex", "codex-new", 20.0)

    intents = reconcile_known(
        _ARTIFACT_ID,
        [unparseable, changed_sibling],
        _record(claude="d0", codex="codex-old"),
    )

    assert intents == (FreezeArtifact(_ARTIFACT_ID),)


def test_a_tied_mtime_breaks_deterministically_to_the_first_tool_name() -> None:
    # US-06 AC-4: equal modified_time → the winner is the alphabetically-first tool
    # name (Unicode-normalised, case-folded), independent of input order. "claude"
    # sorts before "codex", so claude wins even when codex is listed first.
    claude_change = _observed("claude", "claude-new", 15.0)
    codex_change = _observed("codex", "codex-new", 15.0)

    intents = reconcile_known(
        _ARTIFACT_ID,
        [codex_change, claude_change],
        _record(claude="claude-old", codex="codex-old"),
    )

    assert intents == (
        AbsorbToolEdit(_ARTIFACT_ID, claude_change.tool_surface),
        ProjectToTools(_ARTIFACT_ID, (codex_change.tool_surface,)),
    )
