"""Reconcile a known artifact — the content rule + freeze (proposal §7.2, S6a).

One parametric rule decides the common case for an already-managed artifact: if any
surface won't parse, freeze it (FR-11); otherwise detect the changed surfaces by
digest, absorb the freshest, and project the canonical onto the others. *Unchanged*
is the empty case (nothing changed), and *conflict* is just two-or-more changed (the
losers are among the projection targets) — so absorb-one, conflict-many, and
propagation are a single rule, not three branches. The surface-shape guards
(rename / remove / glitch / mv) and the canonical-authority cases land in S6b / S6c.
Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from agents_sync.domain_model.observation import ParseFailure, SurfaceObservation
from agents_sync.domain_model.sync_plan import (
    AbsorbToolEdit,
    FreezeArtifact,
    ProjectToTools,
    SyncIntent,
)
from agents_sync.domain_model.sync_state import ArtifactRecord


def reconcile_known(
    artifact_id: str,
    observations: Sequence[SurfaceObservation],
    record: ArtifactRecord,
) -> tuple[SyncIntent, ...]:
    """Decide the content reconciliation for one already-managed artifact."""
    if any(isinstance(observation.parsed, ParseFailure) for observation in observations):
        return (FreezeArtifact(artifact_id),)
    changed = [observation for observation in observations if _has_changed(observation, record)]
    if not changed:
        return ()
    winner = min(changed, key=_recency_then_name)
    targets = tuple(o.tool_surface for o in observations if o is not winner)
    intents: list[SyncIntent] = [AbsorbToolEdit(artifact_id, winner.tool_surface)]
    if targets:
        intents.append(ProjectToTools(artifact_id, targets))
    return tuple(intents)


def _has_changed(observation: SurfaceObservation, record: ArtifactRecord) -> bool:
    """True iff a recorded surface's content digest moved (digest is the detector)."""
    recorded = record.surfaces.get(observation.tool_surface.tool)
    return recorded is not None and observation.content_digest != recorded.content_digest


def _recency_then_name(observation: SurfaceObservation) -> tuple[float, str]:
    """Winner sort key: most recent first, ties to the alphabetically-first tool name.

    ``min`` over this key picks the highest ``modified_time`` (negated) and, on a
    tie, the Unicode-normalised case-folded first tool name (US-06 AC-4).
    """
    tool = unicodedata.normalize("NFC", observation.tool_surface.tool).casefold()
    return (-observation.modified_time, tool)
