"""Recover identity — the first pure planner step (proposal §7.1).

Partition this poll's surface observations into *managed* (grouped under an
``artifact_id`` recovered from a well-formed embedded id, else from the recorded
state that owns the surface's location) and *candidates* (the id-less remainder).
This is FR-11 made executable: an id is *recovered*, never minted, and recovered
independently of the rest of the metadata. The embedded id takes precedence over a
recorded owner; a present-but-malformed id tag is treated as no id and falls
through. No I/O, no clock — a pure function over the gathered inputs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from agents_sync.domain_model.artifact_identity import InvalidArtifactId, validate_artifact_id
from agents_sync.domain_model.observation import SurfaceObservation
from agents_sync.domain_model.sync_state import SurfaceLocation, SyncState


@dataclass(frozen=True)
class IdentityRecovery:
    """The partition: artifact_id -> its observations, and the id-less candidates."""

    managed: Mapping[str, tuple[SurfaceObservation, ...]] = field(default_factory=dict)
    candidates: tuple[SurfaceObservation, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "managed", MappingProxyType(dict(self.managed)))


def recover_identity(
    observations: Sequence[SurfaceObservation],
    sync_state: SyncState,
) -> IdentityRecovery:
    """Group ``observations`` under their recovered ids; the rest are candidates."""
    recorded_owner = _recorded_owner_index(sync_state)
    managed: dict[str, list[SurfaceObservation]] = {}
    candidates: list[SurfaceObservation] = []
    for observation in observations:
        artifact_id = _recover_id(observation, recorded_owner)
        if artifact_id is None:
            candidates.append(observation)
        else:
            managed.setdefault(artifact_id, []).append(observation)
    return IdentityRecovery(
        managed={artifact_id: tuple(group) for artifact_id, group in managed.items()},
        candidates=tuple(candidates),
    )


def _recorded_owner_index(sync_state: SyncState) -> Mapping[tuple[str, SurfaceLocation], str]:
    """Map each recorded (tool, location) to the artifact_id that owns it."""
    return {
        (tool, recorded.location): artifact_id
        for artifact_id, record in sync_state.records.items()
        for tool, recorded in record.surfaces.items()
    }


def _recover_id(
    observation: SurfaceObservation,
    recorded_owner: Mapping[tuple[str, SurfaceLocation], str],
) -> str | None:
    """Recover the id: a well-formed embedded id first, else the recorded owner."""
    embedded_id = observation.embedded_id
    if embedded_id is not None and _is_canonical_id(embedded_id):
        return embedded_id
    surface = observation.tool_surface
    return recorded_owner.get((surface.tool, surface.location))


def _is_canonical_id(value: str) -> bool:
    """True when ``value`` is a canonical UUIDv4 artifact id (FR-11 well-formed)."""
    try:
        validate_artifact_id(value)
    except InvalidArtifactId:
        return False
    return True
