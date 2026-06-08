"""Dialect mechanisms — the only place a wire format is understood (proposal §10/§13).

Each dialect module exposes ``parse`` / ``render`` / ``extract_id``; the translation
seam (:mod:`agents_sync.translation`) dispatches to them by ``SurfaceFormat.dialect``.
``MalformedSurfaceError`` is the shared signal a dialect raises when a surface's text
cannot be parsed into a canonical document; the read phase (S17) catches it and records
a ``ParseFailure`` so the pure planner never sees a raise.

This package ``__init__`` deliberately defines only the shared error and imports no
dialect submodule, so a dialect importing the error forms no import cycle.
"""

from __future__ import annotations


class MalformedSurfaceError(ValueError):
    """A dialect could not parse a surface's text into a canonical document."""


__all__ = ["MalformedSurfaceError"]
