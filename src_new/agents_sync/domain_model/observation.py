"""Surface observation — one tool surface as the read phase gathered it (pure).

A ``SurfaceObservation`` is what the read phase (S17) records for one tool surface
in one poll, and the only thing the pure planner reasons over for that surface.
This step builds the two fields ``recover_identity`` reads — the ``tool_surface``
it describes and the ``embedded_id`` recovered in isolation (FR-11, ``None`` when
the surface carries no id). The remaining inputs the later planner steps need
(content digest, modified time, the parsed canonical or parse failure) grow with
their consumers in S6 / S17, per YAGNI. It is an immutable hashable value object.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents_sync.domain_model.tool_surface import ToolSurface


@dataclass(frozen=True)
class SurfaceObservation:
    """One tool surface this poll: where it is, and the id it carries (if any)."""

    tool_surface: ToolSurface
    embedded_id: str | None = None
