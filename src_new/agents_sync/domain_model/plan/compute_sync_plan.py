"""compute_sync_plan — the planner capstone: assembly + cross-artifact guards (proposal §7).

Assembles the whole ``SyncPlan`` from the three pure planner steps —
``recover_identity`` → ``reconcile_known`` (per managed artifact, threading that
artifact's stored canonical) → ``adopt_candidates`` — then applies the cross-artifact
guards that need the whole-poll view and *downgrade* per-artifact intents. S8a builds the
assembly and the **two-tool guard**: with fewer than two available tools no destructive
intent survives, so a degenerate poll performs nothing destructive (US-07 AC-5). The
key-conflict (S8b) and glitch (S8c) downgrades extend this pass. Pure: no I/O, no clock,
no randomness.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from agents_sync.domain_model.artifact_naming import candidate_key
from agents_sync.domain_model.observation import SurfaceObservation
from agents_sync.domain_model.plan.adopt_candidates import adopt_candidates
from agents_sync.domain_model.plan.reconcile_known import StoredCanonical, reconcile_known
from agents_sync.domain_model.plan.recover_identity import recover_identity
from agents_sync.domain_model.sync_plan import (
    IntentKind,
    RejectCollision,
    RenameArtifact,
    SyncIntent,
    SyncPlan,
)
from agents_sync.domain_model.sync_state import ArtifactRecord, SyncState

# US-07 AC-5: the destructive intents a degenerate (< 2 available tools) poll must not
# perform — propagation, removal, adoption. Absorbing an edit into the canonical, a
# freeze, a reproject, a rebuild, and a report are not destructive and survive.
_DESTRUCTIVE_KINDS: frozenset[IntentKind] = frozenset(
    {
        IntentKind.ADOPT_NEW_ARTIFACT,
        IntentKind.PROJECT_TO_TOOLS,
        IntentKind.RENAME_ARTIFACT,
        IntentKind.REMOVE_ARTIFACT,
    }
)
_MIN_TOOLS_FOR_DESTRUCTIVE = 2


def compute_sync_plan(
    observations: Sequence[SurfaceObservation],
    sync_state: SyncState,
    stored_canonicals: Mapping[str, StoredCanonical | None],
    available_tool_count: int,
) -> SyncPlan:
    """Decide the whole poll's ``SyncPlan`` from the gathered inputs (pure).

    ``stored_canonicals`` maps each managed ``artifact_id`` to its stored canonical (or
    ``None`` when none is stored); the read phase (S17) fills it. ``available_tool_count``
    is how many tools are ``available`` this poll, gating the two-tool guard.
    """
    recovery = recover_identity(observations, sync_state)
    managed_plans: dict[str, tuple[SyncIntent, ...]] = {}
    for artifact_id, group in recovery.managed.items():
        record = sync_state.records.get(artifact_id, ArtifactRecord())
        managed_plans[artifact_id] = reconcile_known(
            artifact_id, group, record, stored_canonicals.get(artifact_id)
        )
    intents = _reject_collisions(managed_plans, recovery.managed, sync_state.records)
    intents.extend(adopt_candidates(recovery.candidates))
    if available_tool_count < _MIN_TOOLS_FOR_DESTRUCTIVE:
        intents = [intent for intent in intents if intent.kind not in _DESTRUCTIVE_KINDS]
    return SyncPlan(tuple(intents))


def _reject_collisions(
    managed_plans: Mapping[str, tuple[SyncIntent, ...]],
    managed_observations: Mapping[str, tuple[SurfaceObservation, ...]],
    records: Mapping[str, ArtifactRecord],
) -> list[SyncIntent]:
    """Replace the intents of any managed artifacts sharing a reconciliation key with a
    single ``RejectCollision`` per colliding set (US-03 AC-8, US-04 AC-5).

    Only state-managed artifacts participate; an orphan id (recovered but absent from
    ``records``) is not an "already-managed" artifact and never figures in a collision.
    """
    owners_by_key: dict[tuple[str, str], list[str]] = {}
    for artifact_id in managed_plans:
        if artifact_id in records:
            key = _effective_key(
                managed_observations[artifact_id], records[artifact_id], managed_plans[artifact_id]
            )
            owners_by_key.setdefault(key, []).append(artifact_id)
    collisions = {key: owners for key, owners in owners_by_key.items() if len(owners) >= 2}
    colliding = {aid for owners in collisions.values() for aid in owners}
    surviving: list[SyncIntent] = []
    for artifact_id, plan in managed_plans.items():
        if artifact_id not in colliding:
            surviving.extend(plan)
    surviving.extend(
        RejectCollision(tuple(sorted(owners)), key) for key, owners in collisions.items()
    )
    return surviving


def _effective_key(
    observations: Sequence[SurfaceObservation],
    record: ArtifactRecord,
    plan: Sequence[SyncIntent],
) -> tuple[str, str]:
    """The ``(kind, slug)`` a managed artifact would occupy: its kind from the observed
    surfaces, its name from the record unless a pending rename moves it to a new name."""
    name = record.name
    for intent in plan:
        if isinstance(intent, RenameArtifact):
            name = intent.new_name
    return candidate_key(observations[0].tool_surface.kind, name)
