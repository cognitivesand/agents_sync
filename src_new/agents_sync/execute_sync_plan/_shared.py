"""Shared execution context + surface helpers for the executor package (pure plumbing)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agents_sync.domain_model.observation import SurfaceObservation
from agents_sync.domain_model.sync_plan import SyncIntent
from agents_sync.domain_model.sync_state import ArtifactRecord, SurfaceLocation, SyncState
from agents_sync.domain_model.tool_surface import KeyedMapSlot, ToolSurface


class IntentAbortError(RuntimeError):
    """A plan-vs-state inconsistency aborts this intent (not a real I/O failure;
    routed to ``failed`` and converging next poll — e.g. a canonical the planner
    expected was quarantined this poll, or an observation a race removed)."""


@dataclass
class ExecutionContext:
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


def intent_label(intent: SyncIntent) -> str:
    """The artifact id when the intent carries one, else its source location —
    the name a failure/refusal is reported under."""
    artifact_id = getattr(intent, "artifact_id", "")
    if isinstance(artifact_id, str) and artifact_id:
        return artifact_id
    source = getattr(intent, "source", None)
    assert isinstance(source, ToolSurface)  # every transactional intent has one or the other
    return str(source.location)


def target_file(target: ToolSurface) -> Path:
    """The file a render lands in — the slot's shared file for keyed-map surfaces."""
    location = target.location
    return location.file if isinstance(location, KeyedMapSlot) else location


def reject_shared_write_file(surfaces: tuple[ToolSurface, ...], artifact_id: str) -> None:
    """Abort the intent when two surfaces resolve to the same write file: a second
    atomic write would clobber the first surface's bytes. One clobber invariant for
    every multi-surface writer (project, adopt, rename), routed to ``failed`` and
    retried next poll rather than corrupting the file (US-06 AC-6; NFR-01/NFR-16)."""
    write_files = [target_file(surface) for surface in surfaces]
    if len(set(write_files)) != len(write_files):
        raise IntentAbortError(f"intent surfaces share a write file for {artifact_id}")


def recorded_targets(artifact_id: str, execution: ExecutionContext) -> tuple[ToolSurface, ...]:
    """The artifact's recorded surfaces, resolved to this poll's observed ToolSurfaces.

    A recorded location without an observation is skipped — a vanish is the
    planner's removal decision, not the executor's."""
    record = execution.records.get(artifact_id)
    if record is None:
        return ()
    targets: list[ToolSurface] = []
    for recorded in record.surfaces.values():
        observation = execution.observations_by_location.get(recorded.location)
        if observation is not None:
            targets.append(observation.tool_surface)
    return tuple(targets)


def sync_state_of(execution: ExecutionContext) -> SyncState:
    return SyncState(records=execution.records)
