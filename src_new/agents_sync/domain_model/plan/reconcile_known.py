"""Reconcile a known artifact — content rule, freeze, rename, remove (§7.2, S6a/S6b).

A short pipeline decides one already-managed artifact's fate: freeze if any surface
won't parse (FR-11); else remove the artifact if a recorded tool's surface vanished
(US-11, short-circuiting content); else apply the content rule — detect the changed
surfaces by digest, absorb the freshest, and either rename (when the canonical's slug
moved — US-04) or project onto the others. *Unchanged* is the empty case and
*conflict* is just ≥2 changed (losers projected), so absorb-one, conflict-many, and
propagation are a single rule. The cross-artifact downgrades (slug clash →
reject_collision, glitch → reproject) live in S8; canonical authority lands in S6c.
A pure ``mv`` (a moved surface, same digest) needs no intent — its tool still has an
observation, so it is not a vanish. Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from agents_sync.domain_model.artifact_naming import slugify_name
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.observation import ParseFailure, SurfaceObservation
from agents_sync.domain_model.sync_plan import (
    AbsorbToolEdit,
    FreezeArtifact,
    ProjectToTools,
    RemoveArtifact,
    RenameArtifact,
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
    if _has_vanished_surface(observations, record):
        return (RemoveArtifact(artifact_id),)
    changed = [observation for observation in observations if _has_changed(observation, record)]
    if not changed:
        return ()
    winner = min(changed, key=_recency_then_name)
    winner_canonical = winner.parsed
    assert isinstance(winner_canonical, CanonicalDocument)  # the freeze guard ruled out a failure
    intents: list[SyncIntent] = [AbsorbToolEdit(artifact_id, winner.tool_surface)]
    if slugify_name(winner_canonical.name) != slugify_name(record.name):
        # The name moved, so its slug did — rename relocates every projection (it
        # subsumes the projection step, which writes to the old-slug locations).
        intents.append(RenameArtifact(artifact_id, winner_canonical.name))
    else:
        targets = tuple(o.tool_surface for o in observations if o is not winner)
        if targets:
            intents.append(ProjectToTools(artifact_id, targets))
    return tuple(intents)


def _has_vanished_surface(
    observations: Sequence[SurfaceObservation],
    record: ArtifactRecord,
) -> bool:
    """True iff a recorded tool has no observation this poll — a deleted surface (US-11).

    Keyed on tool presence, so a surface that merely moved location still counts as
    present (it has an observation) — that is the ``mv`` case, not a vanish.
    """
    observed_tools = {observation.tool_surface.tool for observation in observations}
    return any(tool not in observed_tools for tool in record.surfaces)


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
