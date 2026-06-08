"""Adopt candidates — the pure planner step for id-less surfaces (proposal §7.3, S7).

The id-less remainder from ``recover_identity``. Parsed candidates are grouped by
``(kind, slug)`` — the ``candidate_key`` — and each group becomes one
``AdoptNewArtifact`` (winner by the shared mtime tiebreak, US-03 AC-7); an
unparseable candidate has no name to derive a slug from, so it is reported
individually via ``ReportUnadoptable`` (US-03), never minted. The managed-match
(``absorb_into_managed``) downgrade needs the whole-poll managed-key map and lives
in S8; cross-identity reconciliation is an import concern (``portable_library``).
Pure: no I/O, no clock, and no mint here — adoption mints later, in the executor.
"""

from __future__ import annotations

from collections.abc import Sequence

from agents_sync.domain_model.artifact_naming import candidate_key
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.observation import SurfaceObservation
from agents_sync.domain_model.plan.winner_selection import freshest
from agents_sync.domain_model.sync_plan import AdoptNewArtifact, ReportUnadoptable, SyncIntent


def adopt_candidates(candidates: Sequence[SurfaceObservation]) -> tuple[SyncIntent, ...]:
    """Group the id-less candidates by (kind, slug); adopt each group, report the rest."""
    groups: dict[tuple[str, str], list[SurfaceObservation]] = {}
    reports: list[SyncIntent] = []
    for candidate in candidates:
        parsed = candidate.parsed
        if isinstance(parsed, CanonicalDocument):
            key = candidate_key(candidate.tool_surface.kind, parsed.name)
            groups.setdefault(key, []).append(candidate)
        else:
            reports.append(ReportUnadoptable(candidate.tool_surface))
    adoptions: list[SyncIntent] = [_adopt(group) for group in groups.values()]
    return tuple(adoptions) + tuple(reports)


def _adopt(group: Sequence[SurfaceObservation]) -> AdoptNewArtifact:
    """Adopt one candidate group from its freshest surface; the rest are already present."""
    winner = freshest(group)
    others = tuple(candidate.tool_surface for candidate in group if candidate is not winner)
    return AdoptNewArtifact(winner.tool_surface, others)
