"""Sync-plan vocabulary — the closed decision set and the poll outcome (pure).

``IntentKind`` is the closed set of decisions the pure planner (``plan/``, S5–S8)
emits and the executor (S19) performs — one member per intent in proposal §6. It
is the stable contract both sides agree on; each intent's payload dataclass grows
with its emitter, per YAGNI, so this step builds the vocabulary alone.

``SyncResult`` is the immutable per-poll outcome the daemon reports. ``changed`` is
a plain count (the "N changed item(s)" log line); the other four carry artifact
identities because the spec needs them *by identity*, not merely counted: the
systemic-failure budget tracks *which* artifacts failed (FR-02), transition-only
logging reports *which* became frozen (FR-11), and the one-diagnostic-per-bad-
surface rule dedupes on *which* were diagnosed unadoptable (NFR-13).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import ClassVar

from agents_sync.domain_model.tool_surface import ToolSurface


class IntentKind(Enum):
    """The closed set of sync decisions (proposal §6); planner emits, executor performs."""

    ADOPT_NEW_ARTIFACT = auto()
    ABSORB_TOOL_EDIT = auto()
    ABSORB_INTO_MANAGED = auto()
    PROJECT_TO_TOOLS = auto()
    RENAME_ARTIFACT = auto()
    REMOVE_ARTIFACT = auto()
    REPROJECT_CANONICAL = auto()
    FREEZE_ARTIFACT = auto()
    REBUILD_CORRUPT_CANONICAL = auto()
    REJECT_COLLISION = auto()
    REPORT_UNADOPTABLE = auto()


@dataclass(frozen=True)
class SyncResult:
    """One poll's outcome: a changed count plus the identities of every other fate."""

    changed: int = 0
    failed: tuple[str, ...] = ()
    blocked: tuple[str, ...] = ()
    frozen: tuple[str, ...] = ()
    diagnosed: tuple[str, ...] = ()


# --- Intent payloads ---------------------------------------------------------
# One immutable dataclass per kind; each tags itself with its `IntentKind` via a
# ClassVar (the discriminator for logging / SyncResult), while the executor may
# also dispatch on the concrete type. The payloads carry only the fields their
# emitter populates; the set grows as later planner steps emit more intents.


@dataclass(frozen=True)
class FreezeArtifact:
    """A managed artifact whose content won't parse — blocked, not synced (FR-11)."""

    artifact_id: str
    kind: ClassVar[IntentKind] = IntentKind.FREEZE_ARTIFACT


@dataclass(frozen=True)
class AbsorbToolEdit:
    """Fold the bytes of the winning changed surface into the canonical."""

    artifact_id: str
    source: ToolSurface
    kind: ClassVar[IntentKind] = IntentKind.ABSORB_TOOL_EDIT


@dataclass(frozen=True)
class ProjectToTools:
    """Write the canonical onto these tool surfaces."""

    artifact_id: str
    targets: tuple[ToolSurface, ...]
    kind: ClassVar[IntentKind] = IntentKind.PROJECT_TO_TOOLS


@dataclass(frozen=True)
class RenameArtifact:
    """The name changed — relocate every projection to the new slug (archive-old first)."""

    artifact_id: str
    new_name: str
    kind: ClassVar[IntentKind] = IntentKind.RENAME_ARTIFACT


@dataclass(frozen=True)
class RemoveArtifact:
    """A surface was deleted — archive then remove the artifact's surviving projections."""

    artifact_id: str
    kind: ClassVar[IntentKind] = IntentKind.REMOVE_ARTIFACT


@dataclass(frozen=True)
class ReprojectCanonical:
    """The canonical changed out of band — re-project it onto the tool surfaces."""

    artifact_id: str
    kind: ClassVar[IntentKind] = IntentKind.REPROJECT_CANONICAL


@dataclass(frozen=True)
class RebuildCorruptCanonical:
    """The stored canonical is corrupt — archive it and rebuild from the tools (US-09)."""

    artifact_id: str
    kind: ClassVar[IntentKind] = IntentKind.REBUILD_CORRUPT_CANONICAL


# The plan's element type — the union of the intent payloads, grown per step.
SyncIntent = (
    FreezeArtifact
    | AbsorbToolEdit
    | ProjectToTools
    | RenameArtifact
    | RemoveArtifact
    | ReprojectCanonical
    | RebuildCorruptCanonical
)
