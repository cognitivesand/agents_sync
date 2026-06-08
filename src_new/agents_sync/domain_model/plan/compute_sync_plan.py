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

from agents_sync.domain_model.observation import SurfaceObservation
from agents_sync.domain_model.plan.adopt_candidates import adopt_candidates
from agents_sync.domain_model.plan.reconcile_known import StoredCanonical, reconcile_known
from agents_sync.domain_model.plan.recover_identity import recover_identity
from agents_sync.domain_model.sync_plan import IntentKind, SyncIntent, SyncPlan
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
    intents: list[SyncIntent] = []
    for artifact_id, group in recovery.managed.items():
        record = sync_state.records.get(artifact_id, ArtifactRecord())
        intents.extend(
            reconcile_known(artifact_id, group, record, stored_canonicals.get(artifact_id))
        )
    intents.extend(adopt_candidates(recovery.candidates))
    if available_tool_count < _MIN_TOOLS_FOR_DESTRUCTIVE:
        intents = [intent for intent in intents if intent.kind not in _DESTRUCTIVE_KINDS]
    return SyncPlan(tuple(intents))
