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
