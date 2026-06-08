"""Winner selection — the freshest surface (pure; proposal §7, US-06 AC-4 / US-03 AC-7).

The single home for "which surface wins": the most recently modified, ties broken
deterministically by the Unicode-normalised case-folded tool name. The proposal
mandates the *same* rule for a sync conflict (``reconcile_known``) and an adoption
tie (``adopt_candidates``), so both call this one function.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from agents_sync.domain_model.observation import SurfaceObservation


def freshest(observations: Sequence[SurfaceObservation]) -> SurfaceObservation:
    """Return the most-recently-modified observation; ties to the first tool name."""
    return min(observations, key=_recency_then_name)


def _recency_then_name(observation: SurfaceObservation) -> tuple[float, str]:
    """Sort key picking the highest ``modified_time``, then the first tool name.

    ``min`` over this key takes the largest ``modified_time`` (negated) and, on a
    tie, the alphabetically-first Unicode-normalised case-folded tool name.
    """
    tool = unicodedata.normalize("NFC", observation.tool_surface.tool).casefold()
    return (-observation.modified_time, tool)
