"""Adoption package: per-pair adopt / sync / resolve / extend / remove.

Public API:
    AdoptionEngine — owns every operation that mutates a single pair's
    on-disk artifacts or state entry.

Implementation split per responsibility:
- ``engine``             — orchestrator + adopt / N-way sync / conflict /
  extend (the mutually-recursive per-pair core lives on ``AdoptionEngine``)
- ``removal_propagator`` — archive-then-delete survivors + orphan handling
  (composed leaf-mixin)
- ``privacy_gate``       — fail-closed private-canonical detection
  (composed host-free mixin)
"""
from __future__ import annotations

from agents_sync.adoption.engine import AdoptionEngine

__all__ = ["AdoptionEngine"]
