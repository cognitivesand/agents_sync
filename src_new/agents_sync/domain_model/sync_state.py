"""Recorded sync state — what the daemon believed true last poll (pure, no I/O).

``SyncState`` maps each managed ``artifact_id`` to an ``ArtifactRecord``; the record
holds each surface's ``RecordedSurface`` — where it was projected and its content
digest at that projection — so the planner can recover an id-less surface by the
recorded owner of its location (``recover_identity``, proposal §7.1) and detect a
change by comparing an observed digest to the recorded one (``reconcile_known``,
§7.2). The recorded ``name`` is what reconciliation compares the canonical's slug
against to detect a rename (§7.2); the recorded canonical digest and kind grow with
their consumers in S6c, per YAGNI.

All three are immutable value objects: frozen guards attribute rebinding, and the
maps are exposed read-only so a recorded surface set cannot be mutated in place (the
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
class RecordedSurface:
    """One artifact's surface as last recorded: its location and its content digest."""

    location: SurfaceLocation
    content_digest: str = ""


@dataclass(frozen=True)
class ArtifactRecord:
    """One managed artifact's recorded name and surfaces (tool -> its RecordedSurface)."""

    name: str = ""
    surfaces: Mapping[str, RecordedSurface] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "surfaces", MappingProxyType(dict(self.surfaces)))


@dataclass(frozen=True)
class SyncState:
    """What the daemon recorded last poll: artifact_id -> its ArtifactRecord."""

    records: Mapping[str, ArtifactRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", MappingProxyType(dict(self.records)))
