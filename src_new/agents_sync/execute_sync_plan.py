"""Execute a sync plan — the hands that perform the planner's intents (proposal §8).

Walks the plan in order and performs I/O in the one order that preserves data:
each intent is a per-artifact transaction — every affected file is archived FIRST,
and only if all archives landed are any overwrites performed and state mutated;
a failure abandons the intent with no write and no state change, retried next
poll (US-06 AC-6). The secret policy is enforced at absorb and at render egress
(NFR-15; a refusal is ``blocked``, never a partial write). An identical render is
skipped — repeated polls with no user change produce no writes and no archive
entries (NFR-05/07). Recorded surface digests come from
``surface_content_digest``, so the next poll observes written surfaces as
unchanged. All translation goes through the two centralized functions — the
executor never knows a dialect. Render targets resolve through this poll's
observations (records carry no surface format); a recorded location without an
observation is skipped (a vanish is the planner's removal decision, not ours).
The identity-family intents (adopt/absorb-into-managed/rename/remove) land in
increment 2; encountering one here fails loud.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from agents_sync.artifact_archive import archive_copy
from agents_sync.atomic_file_writer import write_text_atomic
from agents_sync.canonical_store import load_canonical, save_canonical
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.observation import SurfaceObservation
from agents_sync.domain_model.plan.winner_selection import freshest
from agents_sync.domain_model.sync_plan import (
    AbsorbToolEdit,
    FreezeArtifact,
    ProjectToTools,
    RebuildCorruptCanonical,
    RejectCollision,
    ReportUnadoptable,
    ReprojectCanonical,
    SyncIntent,
    SyncPlan,
    SyncResult,
)
from agents_sync.domain_model.sync_state import (
    ArtifactRecord,
    RecordedSurface,
    SurfaceLocation,
    SyncState,
)
from agents_sync.domain_model.tool_surface import KeyedMapSlot, ToolSurface
from agents_sync.read_tool_surfaces import surface_content_digest
from agents_sync.secret_policy import (
    SECRET_POLICY_REFUSED,
    SecretLeakError,
    enforce_secret_policy,
)
from agents_sync.translation import canonical_to_file


def execute_sync_plan(
    sync_plan: SyncPlan,
    observations: tuple[SurfaceObservation, ...],
    sync_state: SyncState,
    state_dir: Path,
    *,
    secret_policy_value: str = SECRET_POLICY_REFUSED,
) -> tuple[SyncResult, SyncState]:
    """Perform every intent; return the poll's result and the updated state."""
    execution = _Execution(
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
        SyncState(records=execution.records),
    )


@dataclass
class _Execution:
    """One poll's mutable execution context — accumulates outcomes and records."""

    observations_by_location: dict[SurfaceLocation, SurfaceObservation]
    records: dict[str, ArtifactRecord]
    state_dir: Path
    secret_policy_value: str
    changed: int = 0
    failed: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    frozen: list[str] = field(default_factory=list)
    diagnosed: list[str] = field(default_factory=list)


def _perform_intent(intent: SyncIntent, execution: _Execution) -> None:
    if isinstance(intent, FreezeArtifact):
        execution.frozen.append(intent.artifact_id)
        return
    if isinstance(intent, ReportUnadoptable):
        execution.diagnosed.append(str(intent.surface.location))
        return
    if isinstance(intent, RejectCollision):
        execution.diagnosed.extend(intent.artifact_ids)
        return
    try:
        if isinstance(intent, AbsorbToolEdit):
            _absorb_tool_edit(intent, execution)
        elif isinstance(intent, ProjectToTools):
            _project_canonical(intent.artifact_id, intent.targets, execution)
        elif isinstance(intent, ReprojectCanonical):
            _project_canonical(
                intent.artifact_id, _recorded_targets(intent.artifact_id, execution), execution
            )
        elif isinstance(intent, RebuildCorruptCanonical):
            _rebuild_corrupt_canonical(intent, execution)
        else:
            raise ValueError(f"intent not yet executable (S19 increment 2): {intent!r}")
    except SecretLeakError:
        # NFR-15 fail-closed: nothing was written for this artifact.
        execution.blocked.append(_intent_artifact_id(intent))
    except OSError:
        # The transaction aborted before any overwrite; retried next poll.
        execution.failed.append(_intent_artifact_id(intent))


def _intent_artifact_id(intent: SyncIntent) -> str:
    artifact_id = getattr(intent, "artifact_id", "")
    assert isinstance(artifact_id, str) and artifact_id  # transactional intents carry one
    return artifact_id


# --- absorb -----------------------------------------------------------------------------


def _absorb_tool_edit(intent: AbsorbToolEdit, execution: _Execution) -> None:
    """Fold the winning surface's parsed content into the stored canonical."""
    observation = execution.observations_by_location.get(intent.source.location)
    if observation is None or not isinstance(observation.parsed, CanonicalDocument):
        raise OSError(f"absorb source has no parsed observation: {intent.source.location}")
    canonical = observation.parsed
    if not canonical.artifact_id:
        canonical = replace(canonical, artifact_id=intent.artifact_id)
    enforce_secret_policy(
        canonical, execution.secret_policy_value, artifact_label=intent.artifact_id
    )
    save_canonical(execution.state_dir, canonical)
    record = execution.records.get(intent.artifact_id, ArtifactRecord())
    execution.records[intent.artifact_id] = replace(
        record,
        name=canonical.name,
        canonical_digest=canonical.content_digest(),
        surfaces={
            **record.surfaces,
            intent.source.tool: RecordedSurface(
                location=intent.source.location,
                content_digest=observation.content_digest,
            ),
        },
    )
    execution.changed += 1


# --- project / reproject ------------------------------------------------------------------


def _project_canonical(
    artifact_id: str, targets: tuple[ToolSurface, ...], execution: _Execution
) -> None:
    """Render the stored canonical onto ``targets`` as one per-artifact transaction:
    render all, archive all displaced bytes, and only then write."""
    canonical = load_canonical(execution.state_dir, artifact_id)
    if not isinstance(canonical, CanonicalDocument):
        raise OSError(f"no stored canonical to project for {artifact_id}")
    enforce_secret_policy(canonical, execution.secret_policy_value, artifact_label=artifact_id)
    pending_writes: list[tuple[ToolSurface, Path, str]] = []
    for target in targets:
        target_file = _target_file(target)
        prior_text = target_file.read_text(encoding="utf-8") if target_file.exists() else None
        new_text = canonical_to_file(canonical, target, prior_text)
        if new_text == prior_text:
            continue  # identical render: no write, no archive (NFR-05/07)
        if prior_text is not None:
            archive_copy(execution.state_dir, artifact_id, target.tool, target_file)
        pending_writes.append((target, target_file, new_text))
    # every displaced byte is archived — now, and only now, overwrite.
    record = execution.records.get(artifact_id, ArtifactRecord())
    written_surfaces = dict(record.surfaces)
    for target, target_file, new_text in pending_writes:
        write_text_atomic(target_file, new_text)
        written_surfaces[target.tool] = RecordedSurface(
            location=target.location,
            content_digest=surface_content_digest(new_text, target),
        )
    if pending_writes:
        execution.records[artifact_id] = replace(
            record,
            name=canonical.name or record.name,
            canonical_digest=canonical.content_digest(),
            surfaces=written_surfaces,
        )
        execution.changed += 1


def _recorded_targets(artifact_id: str, execution: _Execution) -> tuple[ToolSurface, ...]:
    """The artifact's recorded surfaces, resolved to this poll's observed ToolSurfaces."""
    record = execution.records.get(artifact_id)
    if record is None:
        return ()
    targets: list[ToolSurface] = []
    for recorded in record.surfaces.values():
        observation = execution.observations_by_location.get(recorded.location)
        if observation is not None:
            targets.append(observation.tool_surface)
    return tuple(targets)


def _target_file(target: ToolSurface) -> Path:
    """The file a render lands in — the slot's shared file for keyed-map surfaces."""
    location = target.location
    return location.file if isinstance(location, KeyedMapSlot) else location


# --- rebuild ------------------------------------------------------------------------------


def _rebuild_corrupt_canonical(intent: RebuildCorruptCanonical, execution: _Execution) -> None:
    """The stored canonical was lost (quarantined): rebuild it from the freshest
    parseable recorded surface (US-09 AC-4)."""
    parseable = [
        observation
        for observation in (
            execution.observations_by_location.get(recorded.location)
            for recorded in execution.records.get(
                intent.artifact_id, ArtifactRecord()
            ).surfaces.values()
        )
        if observation is not None and isinstance(observation.parsed, CanonicalDocument)
    ]
    if not parseable:
        raise OSError(f"no parseable surface to rebuild canonical for {intent.artifact_id}")
    winner = freshest(parseable)
    canonical = winner.parsed
    assert isinstance(canonical, CanonicalDocument)
    if not canonical.artifact_id:
        canonical = replace(canonical, artifact_id=intent.artifact_id)
    enforce_secret_policy(
        canonical, execution.secret_policy_value, artifact_label=intent.artifact_id
    )
    save_canonical(execution.state_dir, canonical)
    record = execution.records.get(intent.artifact_id, ArtifactRecord())
    execution.records[intent.artifact_id] = replace(
        record, name=canonical.name, canonical_digest=canonical.content_digest()
    )
    execution.changed += 1
