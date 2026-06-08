"""compute_sync_plan — the planner capstone: assembly + cross-artifact guards (proposal §7).

Assembles the whole ``SyncPlan`` from the three pure planner steps —
``recover_identity`` → ``reconcile_known`` (per managed artifact, threading that
artifact's stored canonical) → ``adopt_candidates`` — then applies the cross-artifact
guards that need the whole-poll view and *downgrade* per-artifact intents. S8a builds the
assembly and the **two-tool guard**: with fewer than two available tools no destructive
intent survives, so a degenerate poll performs nothing destructive (US-07 AC-5). The
collision (S8b), absorb-into-managed (S8c), and glitch (S8d) downgrades extend this pass.
Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from agents_sync.domain_model.artifact_naming import candidate_key
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.observation import SurfaceObservation
from agents_sync.domain_model.plan.adopt_candidates import adopt_candidates
from agents_sync.domain_model.plan.reconcile_known import (
    StoredCanonical,
    reconcile_known,
    vanished_tools,
)
from agents_sync.domain_model.plan.recover_identity import recover_identity
from agents_sync.domain_model.sync_plan import (
    AbsorbIntoManaged,
    AdoptNewArtifact,
    IntentKind,
    RejectCollision,
    RemoveArtifact,
    RenameArtifact,
    ReprojectCanonical,
    SyncIntent,
    SyncPlan,
)
from agents_sync.domain_model.sync_state import ArtifactRecord, SyncState

# US-07 AC-5: the destructive intents a degenerate (< 2 available tools) poll must not
# perform — propagation, removal, adoption (including absorb-into-managed, which projects
# the managed canonical onto the new tool). A freeze, an absorb of a tool edit into the
# canonical, a reproject, a rebuild, a report, and a collision rejection are not
# destructive and survive.
_DESTRUCTIVE_KINDS: frozenset[IntentKind] = frozenset(
    {
        IntentKind.ADOPT_NEW_ARTIFACT,
        IntentKind.ABSORB_INTO_MANAGED,
        IntentKind.PROJECT_TO_TOOLS,
        IntentKind.RENAME_ARTIFACT,
        IntentKind.REMOVE_ARTIFACT,
    }
)
_MIN_TOOLS_FOR_DESTRUCTIVE = 2
# US-11 AC-9: a tool losing this many recorded artifacts in one poll is a glitch (an
# emptied root, an unmounted overlay), not user deletions — a lone vanish is deliberate.
_GLITCH_THRESHOLD = 2


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
    managed_plans = _heal_glitched_removals(managed_plans, recovery.managed, sync_state.records)
    owners_by_key = _index_managed_keys(managed_plans, recovery.managed, sync_state.records)
    # A candidate may absorb only into a key owned by exactly one managed artifact; a
    # colliding key (>= 2 owners) is rejected, never an absorption target.
    sole_owner_by_key = {
        key: owners[0] for key, owners in owners_by_key.items() if len(owners) == 1
    }
    intents = _reject_collisions(managed_plans, owners_by_key)
    intents.extend(
        _absorb_into_managed(
            adopt_candidates(recovery.candidates), recovery.candidates, sole_owner_by_key
        )
    )
    if available_tool_count < _MIN_TOOLS_FOR_DESTRUCTIVE:
        intents = [intent for intent in intents if intent.kind not in _DESTRUCTIVE_KINDS]
    return SyncPlan(tuple(intents))


def _heal_glitched_removals(
    managed_plans: Mapping[str, tuple[SyncIntent, ...]],
    managed_observations: Mapping[str, tuple[SurfaceObservation, ...]],
    records: Mapping[str, ArtifactRecord],
) -> dict[str, tuple[SyncIntent, ...]]:
    """A tool that lost ``_GLITCH_THRESHOLD`` or more recorded artifacts this poll suffered
    a glitch, not user deletions: each affected artifact's removal becomes a reproject —
    restoring the files from the canonical (US-11 AC-9). A lone vanish is a deliberate
    deletion and is left to propagate.
    """
    vanished_by_artifact = {
        artifact_id: vanished_tools(managed_observations[artifact_id], records[artifact_id])
        for artifact_id in managed_plans
        if artifact_id in records
    }
    vanish_count: dict[str, int] = {}
    for tools in vanished_by_artifact.values():
        for tool in tools:
            vanish_count[tool] = vanish_count.get(tool, 0) + 1
    glitched = {tool for tool, count in vanish_count.items() if count >= _GLITCH_THRESHOLD}
    healed: dict[str, tuple[SyncIntent, ...]] = {}
    for artifact_id, plan in managed_plans.items():
        if glitched & vanished_by_artifact.get(artifact_id, set()):
            healed[artifact_id] = tuple(
                ReprojectCanonical(artifact_id) if isinstance(intent, RemoveArtifact) else intent
                for intent in plan
            )
        else:
            healed[artifact_id] = plan
    return healed


def _index_managed_keys(
    managed_plans: Mapping[str, tuple[SyncIntent, ...]],
    managed_observations: Mapping[str, tuple[SurfaceObservation, ...]],
    records: Mapping[str, ArtifactRecord],
) -> dict[tuple[str, str], list[str]]:
    """Map each state-managed artifact's effective ``(kind, slug)`` to the ids resolving to
    it. An orphan id (recovered but absent from ``records``) is not an already-managed
    artifact, so it is excluded — it owns no key and can neither collide nor be absorbed into.
    """
    owners_by_key: dict[tuple[str, str], list[str]] = {}
    for artifact_id in managed_plans:
        if artifact_id in records:
            key = _effective_key(
                managed_observations[artifact_id], records[artifact_id], managed_plans[artifact_id]
            )
            owners_by_key.setdefault(key, []).append(artifact_id)
    return owners_by_key


def _reject_collisions(
    managed_plans: Mapping[str, tuple[SyncIntent, ...]],
    owners_by_key: Mapping[tuple[str, str], list[str]],
) -> list[SyncIntent]:
    """Replace the intents of any managed artifacts sharing a reconciliation key with a
    single ``RejectCollision`` per colliding set (US-03 AC-8, US-04 AC-5)."""
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


def _absorb_into_managed(
    candidate_intents: Sequence[SyncIntent],
    candidates: Sequence[SurfaceObservation],
    sole_owner_by_key: Mapping[tuple[str, str], str],
) -> list[SyncIntent]:
    """Downgrade each ``AdoptNewArtifact`` whose group key matches a sole-owner managed key
    to ``AbsorbIntoManaged`` (managed wins, no mint — US-03 AC-6); other intents pass through.
    """
    parsed_by_surface = {obs.tool_surface: obs.parsed for obs in candidates}
    result: list[SyncIntent] = []
    for intent in candidate_intents:
        if isinstance(intent, AdoptNewArtifact):
            parsed = parsed_by_surface[intent.source]
            assert isinstance(parsed, CanonicalDocument)  # adopt emits only for parsed candidates
            owner = sole_owner_by_key.get(candidate_key(intent.source.kind, parsed.name))
            if owner is not None:
                result.append(AbsorbIntoManaged(owner, (intent.source, *intent.others)))
                continue
        result.append(intent)
    return result


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
