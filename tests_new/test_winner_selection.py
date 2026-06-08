"""Unit tests for the shared winner-selection rule (rebuild S7).

`freshest` is the single home for "which surface wins" — the most recently modified,
ties broken to the Unicode-normalised case-folded first tool name. The proposal
mandates the same rule for a sync conflict (US-06 AC-4) and an adoption tie
(US-03 AC-7); both reconcile_known and adopt_candidates call it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.domain_model.observation import SurfaceObservation
from agents_sync.domain_model.plan.winner_selection import freshest
from agents_sync.domain_model.tool_surface import SurfaceFormat, ToolSurface

_MARKDOWN = SurfaceFormat(dialect="markdown_frontmatter")


def _observed(tool: str, modified_time: float) -> SurfaceObservation:
    surface = ToolSurface(
        tool=tool,
        kind="agent",
        location=Path(f"/u/.{tool}/agents/reviewer.md"),
        surface_format=_MARKDOWN,
    )
    return SurfaceObservation(tool_surface=surface, modified_time=modified_time)


def test_freshest_picks_the_most_recently_modified() -> None:
    # The fresher surface is the alphabetically-LATER tool, so a name-first
    # implementation would wrongly pick claude — recency must dominate the tiebreak.
    older = _observed("claude", 10.0)
    newer = _observed("codex", 20.0)

    assert freshest([older, newer]) is newer


def test_a_tie_breaks_to_the_alphabetically_first_tool_name() -> None:
    # Equal modified_time: "claude" sorts before "codex", independent of input order.
    claude = _observed("claude", 15.0)
    codex = _observed("codex", 15.0)

    assert freshest([codex, claude]) is claude


def test_the_tie_break_is_case_folded_not_raw_byte_order() -> None:
    # "Codex" sorts before "claude" by raw ASCII (uppercase C < lowercase c), but the
    # tiebreak case-folds first, so "claude" < "codex" wins — proving the casefold() is
    # load-bearing (a raw str sort would pick Codex).
    capital_codex = _observed("Codex", 15.0)
    claude = _observed("claude", 15.0)

    assert freshest([capital_codex, claude]) is claude


def test_freshest_rejects_an_empty_group() -> None:
    # An empty group is a caller bug; freshest fails loud rather than via min()'s ValueError.
    with pytest.raises(AssertionError):
        freshest([])
