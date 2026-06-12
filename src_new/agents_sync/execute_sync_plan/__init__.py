"""Execute a sync plan — the hands that perform the planner's intents (proposal §8).

Walks the plan in order and performs I/O in the one order that preserves data:
each intent is a per-artifact transaction — every affected file is archived FIRST,
and only if all archives landed are any overwrites performed and state mutated; a
failure abandons the intent with no write and no state change, retried next poll
(US-06 AC-6; a ``SecretLeakError`` is ``blocked``, an I/O error ``failed``). All
translation goes through the centralized seam — the executor never knows a
dialect. Recorded digests come from ``surface_content_digest`` so the next poll
observes written surfaces as unchanged (NFR-05).

Package layout (split for the 300-line limit):
- ``_shared`` — the mutable execution context + surface helpers both families use.
- ``content_intents`` — absorb, project/reproject, rebuild.
- ``identity_intents`` — adopt (the SOLE mint, AD-2), absorb-into-managed,
  rename, remove.
"""

from __future__ import annotations

from pathlib import Path

from agents_sync.domain_model.observation import SurfaceObservation
from agents_sync.domain_model.sync_plan import (
    AbsorbIntoManaged,
    AbsorbToolEdit,
    AdoptNewArtifact,
    FreezeArtifact,
    ProjectToTools,
    RebuildCorruptCanonical,
    RejectCollision,
    RemoveArtifact,
    RenameArtifact,
    ReportUnadoptable,
    ReprojectCanonical,
    SyncIntent,
    SyncPlan,
    SyncResult,
)
from agents_sync.domain_model.sync_state import SyncState
from agents_sync.execute_sync_plan import content_intents, identity_intents
from agents_sync.execute_sync_plan._shared import (
    ExecutionContext,
    IntentAbortError,
    intent_label,
    recorded_targets,
    sync_state_of,
)
from agents_sync.secret_policy import SECRET_POLICY_REFUSED, SecretLeakError

__all__ = ["execute_sync_plan"]


def execute_sync_plan(
    sync_plan: SyncPlan,
    observations: tuple[SurfaceObservation, ...],
    sync_state: SyncState,
    state_dir: Path,
    *,
    secret_policy_value: str = SECRET_POLICY_REFUSED,
) -> tuple[SyncResult, SyncState]:
    """Perform every intent; return the poll's result and the updated state."""
    execution = ExecutionContext(
        observations_by_location={obs.tool_surface.location: obs for obs in observations},
        records=dict(sync_state.records),
        state_dir=state_dir,
        secret_policy_value=secret_policy_value,
    )
    for intent in sync_plan.intents:
        _perform_intent(intent, execution)
    return (
        SyncResult(
            changed=execution.changed,
            failed=tuple(execution.failed),
            blocked=tuple(execution.blocked),
            frozen=tuple(execution.frozen),
            diagnosed=tuple(execution.diagnosed),
        ),
        sync_state_of(execution),
    )


def _perform_intent(intent: SyncIntent, execution: ExecutionContext) -> None:
    if isinstance(intent, FreezeArtifact):
        execution.frozen.append(intent.artifact_id)
        return
    if isinstance(intent, ReportUnadoptable):
        execution.diagnosed.append(str(intent.surface.location))
        return
    if isinstance(intent, RejectCollision):
        execution.diagnosed.extend(intent.artifact_ids)
        return
    label = intent_label(intent)  # computed before the try: its invariant must not
    try:  # surface inside an except handler masking the original failure
        _perform_transactional_intent(intent, execution)
    except SecretLeakError:
        # NFR-15 fail-closed: nothing was written for this artifact.
        execution.blocked.append(label)
    except (IntentAbortError, OSError, UnicodeDecodeError):
        # The transaction aborted before any overwrite; retried next poll.
        # UnicodeDecodeError: the executor reads surface files itself (a binary file
        # at a recorded location must fail the intent, not crash the poll).
        execution.failed.append(label)


def _perform_transactional_intent(intent: SyncIntent, execution: ExecutionContext) -> None:
    if isinstance(intent, AbsorbToolEdit):
        content_intents.absorb_tool_edit(intent, execution)
    elif isinstance(intent, ProjectToTools):
        content_intents.project_canonical(intent.artifact_id, intent.targets, execution)
    elif isinstance(intent, ReprojectCanonical):
        content_intents.project_canonical(
            intent.artifact_id, recorded_targets(intent.artifact_id, execution), execution
        )
    elif isinstance(intent, RebuildCorruptCanonical):
        content_intents.rebuild_corrupt_canonical(intent, execution)
    elif isinstance(intent, AdoptNewArtifact):
        identity_intents.adopt_new_artifact(intent, execution)
    elif isinstance(intent, AbsorbIntoManaged):
        identity_intents.absorb_into_managed(intent, execution)
    elif isinstance(intent, RenameArtifact):
        identity_intents.rename_artifact(intent, execution)
    else:
        assert isinstance(intent, RemoveArtifact)  # the closed IntentKind vocabulary
        identity_intents.remove_artifact(intent, execution)
