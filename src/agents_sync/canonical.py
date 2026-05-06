"""Canonical schema — placeholder for Phase 2.

Phase 2 introduces a per-pair canonical JSON document as the lossless
intermediate between Claude and Codex sides. Until then this module is
intentionally empty (only the schema-version constant is set) so the
package shape matches the v0.2 implementation plan from day one.
"""
from __future__ import annotations

SCHEMA_VERSION = 1
