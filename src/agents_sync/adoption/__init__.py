"""Adoption package: per-pair adopt / sync / resolve / extend / remove.

Public API:
    AdoptionEngine — owns every operation that mutates a single pair's
    on-disk artifacts or state entry.

Implementation split per responsibility:
- ``engine``             — orchestrator (process_pair dispatcher, shared helpers)
- ``adopter``            — adopt-new-pair + N-way sync
- ``conflict_resolver``  — argmax(mtime) + loser archival
- ``extender``           — render to newly-available tools
- ``removal_propagator`` — archive-then-delete survivors + orphan handling
- ``privacy_gate``       — fail-closed private-canonical detection
"""
from __future__ import annotations

from agents_sync.adoption.engine import AdoptionEngine

__all__ = ["AdoptionEngine"]
