"""Unit tests for candidate adoption (rebuild S7).

`adopt_candidates` is the pure planner step for the id-less candidates from
recover_identity (proposal §7.3): group the parsed candidates by (kind, slug) and
emit `AdoptNewArtifact` per group (winner by the shared mtime tiebreak, US-03 AC-7);
each unparseable candidate has no slug to group by, so it is reported individually via
`ReportUnadoptable` (US-03). The managed-match (`absorb_into_managed`) downgrade is
cross-artifact and lives in S8, so it is out of scope here. Pure in-memory tests.
"""

from __future__ import annotations

from pathlib import Path

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.observation import ParseFailure, SurfaceObservation
from agents_sync.domain_model.plan.adopt_candidates import adopt_candidates
from agents_sync.domain_model.sync_plan import AdoptNewArtifact, ReportUnadoptable
from agents_sync.domain_model.tool_surface import SurfaceFormat, ToolSurface

_MARKDOWN = SurfaceFormat(dialect="markdown_frontmatter")
# A candidate is id-less on disk; its parsed canonical carries no real id (adoption
# mints one later). adopt_candidates reads only the name + kind, never this id.
_PLACEHOLDER_ID = "00000000-0000-4000-8000-000000000000"


def _surface(tool: str, name: str = "reviewer", kind: str = "agent") -> ToolSurface:
    return ToolSurface(
        tool=tool,
        kind=kind,
        location=Path(f"/u/.{tool}/{kind}s/{name}.md"),
        surface_format=_MARKDOWN,
    )


def _candidate(
    tool: str,
    name: str = "reviewer",
    kind: str = "agent",
    modified_time: float = 10.0,
    parsed: CanonicalDocument | ParseFailure | None = None,
) -> SurfaceObservation:
    canonical = parsed or CanonicalDocument(artifact_id=_PLACEHOLDER_ID, kind=kind, name=name)
    return SurfaceObservation(
        tool_surface=_surface(tool, name, kind),
        embedded_id=None,
        modified_time=modified_time,
        parsed=canonical,
    )


def test_a_single_parsed_candidate_is_adopted() -> None:
    candidate = _candidate("claude", name="reviewer")

    intents = adopt_candidates([candidate])

    assert intents == (AdoptNewArtifact(candidate.tool_surface, ()),)


def test_candidates_sharing_a_key_adopt_as_one_with_the_freshest_winner() -> None:
    # The same artifact appears id-less on two tools → one adoption; the freshest is
    # the source, the rest are the already-present others.
    older = _candidate("claude", name="reviewer", modified_time=10.0)
    newer = _candidate("codex", name="reviewer", modified_time=20.0)

    intents = adopt_candidates([older, newer])

    assert intents == (AdoptNewArtifact(newer.tool_surface, (older.tool_surface,)),)


def test_an_adoption_tie_breaks_to_the_first_tool_name() -> None:
    # US-03 AC-7: equal modified_time → the alphabetically-first tool wins, here
    # claude over codex, independent of input order.
    claude = _candidate("claude", name="reviewer", modified_time=15.0)
    codex = _candidate("codex", name="reviewer", modified_time=15.0)

    intents = adopt_candidates([codex, claude])

    assert intents == (AdoptNewArtifact(claude.tool_surface, (codex.tool_surface,)),)


def test_candidates_with_different_keys_adopt_separately() -> None:
    reviewer = _candidate("claude", name="reviewer")
    auditor = _candidate("claude", name="auditor")

    intents = adopt_candidates([reviewer, auditor])

    assert intents == (
        AdoptNewArtifact(reviewer.tool_surface, ()),
        AdoptNewArtifact(auditor.tool_surface, ()),
    )


def test_an_unparseable_candidate_is_reported_not_adopted() -> None:
    candidate = _candidate("claude", parsed=ParseFailure(reason="bad front-matter"))

    intents = adopt_candidates([candidate])

    assert intents == (ReportUnadoptable(candidate.tool_surface),)


def test_parsed_and_unparseable_candidates_are_handled_together() -> None:
    good = _candidate("claude", name="reviewer")
    bad = _candidate("codex", name="broken", parsed=ParseFailure(reason="x"))

    intents = adopt_candidates([good, bad])

    assert intents == (
        AdoptNewArtifact(good.tool_surface, ()),
        ReportUnadoptable(bad.tool_surface),
    )


def test_no_candidates_yields_no_intent() -> None:
    assert adopt_candidates([]) == ()
