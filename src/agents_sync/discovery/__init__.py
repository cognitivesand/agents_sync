"""Discovery package: on-disk artifact walking and collision blocking.

Public API:
    DiscoveryWalker — the orchestrator class consumed by Syncer.

The implementation is split across submodules per responsibility:
- ``walker``           — orchestrator class, public methods
- ``enumerator``       — per-cell artifact reading and registration
- ``adoption_planner`` — target planning for not-yet-managed pairs
- ``collision_blocker``— veto pairs whose targets clobber others
"""
from __future__ import annotations

from agents_sync.discovery.walker import DiscoveryWalker

__all__ = ["DiscoveryWalker"]
