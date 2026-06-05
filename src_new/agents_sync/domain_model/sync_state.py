"""Recorded sync state — what the daemon believed true last poll (pure, no I/O).

``SyncState`` maps each managed ``artifact_id`` to an ``ArtifactRecord``; the record
holds where that artifact's surfaces live, so the planner can recover an id-less
surface by the recorded owner of its location (``recover_identity``, proposal §7.1).
This step builds only those recorded surface *locations*; the recorded per-surface
digests and the canonical digest grow with their consumer in S6, per YAGNI.

Both are immutable value objects: frozen guards attribute rebinding, and the maps
are exposed read-only so a recorded surface set cannot be mutated in place (the
trap the canonical-document deep-freeze already established). The persistence I/O
lives in the ``sync_state_store`` gateway (S15); this is the in-memory entity only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from agents_sync.domain_model.tool_surface import KeyedMapSlot

# Where one recorded surface lives — a per-file path or a keyed-map slot.
SurfaceLocation = Path | KeyedMapSlot


@dataclass(frozen=True)
class ArtifactRecord:
    """One managed artifact's recorded surfaces: tool -> where it was projected."""

    surfaces: Mapping[str, SurfaceLocation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "surfaces", MappingProxyType(dict(self.surfaces)))


@dataclass(frozen=True)
class SyncState:
    """What the daemon recorded last poll: artifact_id -> its ArtifactRecord."""

    records: Mapping[str, ArtifactRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", MappingProxyType(dict(self.records)))
