"""Surface observation — one tool surface as the read phase gathered it (pure).

A ``SurfaceObservation`` is what the read phase (S17) records for one tool surface
in one poll, and the only thing the pure planner reasons over for that surface:
the ``tool_surface`` it describes, the ``embedded_id`` recovered in isolation
(FR-11, ``None`` when the surface carries no id), the ``content_digest`` the
content rule detects a change by, the ``modified_time`` it breaks a conflict by,
and the ``parsed`` result — a ``CanonicalDocument`` or a ``ParseFailure`` (the read
phase catches a malformed file and records the failure, so the planner routes it to
``freeze_artifact`` rather than ever seeing a raise). It is an immutable value
object. ``parsed`` defaults to a ``ParseFailure``: an observation is unparsed until
the read phase proves otherwise, so a caller that forgets to set it fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import ToolSurface


@dataclass(frozen=True)
class ParseFailure:
    """The read phase could not parse a surface's content into a canonical document."""

    reason: str = ""


@dataclass(frozen=True)
class SurfaceObservation:
    """One tool surface this poll: where it is, what it holds, and how fresh it is."""

    tool_surface: ToolSurface
    embedded_id: str | None = None
    content_digest: str = ""
    modified_time: float = 0.0
    parsed: CanonicalDocument | ParseFailure = field(default_factory=ParseFailure)
