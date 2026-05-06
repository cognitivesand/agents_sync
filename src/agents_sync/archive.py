"""Archive utilities — placeholder for Phase 2.

Phase 2 introduces the archive-on-overwrite implementation backing the
data-preservation invariant (NFR-01). For now this module exposes only
the ISO-8601 timestamp helper so other modules can adopt the convention
early.
"""
from __future__ import annotations

import datetime as _dt


def iso_timestamp(now: _dt.datetime | None = None) -> str:
    """ISO 8601 UTC timestamp with `:` replaced by `-` for filesystem use."""
    moment = now or _dt.datetime.now(tz=_dt.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H-%M-%SZ")
