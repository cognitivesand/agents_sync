"""Reconcile a known artifact — a short pipeline of guards (§7.2, S6a–S6c).

One already-managed artifact's fate, in precedence order: **freeze** if any surface
won't parse (FR-11); **rebuild** if the stored canonical is corrupt (US-09 AC-4);
**remove** if a recorded tool's surface vanished (US-11, short-circuiting content);
the **content rule** — detect the changed surfaces by digest, absorb the freshest,
and either rename (the canonical's slug moved — US-04) or project onto the others;
else **reproject** if the stored canonical changed out of band (an import — US-09).
The two integrity guards (freeze, rebuild) come first: a broken artifact is fixed
before it is acted on. *Unchanged* is the empty case, *conflict* is just ≥2 changed
(losers projected) — so absorb-one, conflict-many, and propagation are one rule. The
cross-artifact downgrades (slug clash → reject_collision, glitch → reproject) live in
S8. A pure ``mv`` (a moved surface, same digest) needs no intent — its tool still has
an observation, so it is not a vanish. Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from agents_sync.domain_model.artifact_naming import slugify_name
from agents_sync.domain_model.canonical_document import CanonicalDocument, CorruptCanonical
from agents_sync.domain_model.observation import ParseFailure, SurfaceObservation
from agents_sync.domain_model.sync_plan import (
    AbsorbToolEdit,
    FreezeArtifact,
    ProjectToTools,
    RebuildCorruptCanonical,
    RemoveArtifact,
    RenameArtifact,
    ReprojectCanonical,
    SyncIntent,
)
from agents_sync.domain_model.sync_state import ArtifactRecord

StoredCanonical = CanonicalDocument | CorruptCanonical


def reconcile_known(
    artifact_id: str,
    observations: Sequence[SurfaceObservation],
    record: ArtifactRecord,
    stored_canonical: StoredCanonical | None = None,
) -> tuple[SyncIntent, ...]:
    """Decide one already-managed artifact's fate — a short pipeline of guards.

    ``stored_canonical`` is the artifact's truth loaded by the read phase; it is
    ``None`` until S8 wires it, in which case the canonical-authority checks are
    skipped (the content/shape decisions still apply).
    """
    if any(isinstance(observation.parsed, ParseFailure) for observation in observations):
        return (FreezeArtifact(artifact_id),)
    if isinstance(stored_canonical, CorruptCanonical):
        return (RebuildCorruptCanonical(artifact_id),)
    if _has_vanished_surface(observations, record):
        return (RemoveArtifact(artifact_id),)
    changed = [observation for observation in observations if _has_changed(observation, record)]
    if changed:
        return _absorb_change(artifact_id, observations, record, changed)
    if _canonical_moved_out_of_band(stored_canonical, record):
        return (ReprojectCanonical(artifact_id),)
    return ()


def _absorb_change(
    artifact_id: str,
    observations: Sequence[SurfaceObservation],
    record: ArtifactRecord,
    changed: Sequence[SurfaceObservation],
) -> tuple[SyncIntent, ...]:
    """Absorb the freshest changed surface, then rename or project onto the rest."""
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


def _canonical_moved_out_of_band(
    stored_canonical: StoredCanonical | None,
    record: ArtifactRecord,
) -> bool:
    """True iff the stored canonical's digest differs from the recorded one (an import)."""
    return (
        isinstance(stored_canonical, CanonicalDocument)
        and stored_canonical.content_digest() != record.canonical_digest
    )


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
