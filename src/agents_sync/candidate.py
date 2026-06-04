"""Provisional identity for id-less artifacts within a single poll.

An artifact that carries no embedded ``pair_id`` and is not yet recorded in state
has no identity yet: it is a *candidate*. Discovery must not mint a real id for
it (that is RC-1 of bug 602c6d — a fresh random id every poll caused identity
churn). Instead discovery tags a candidate with a deterministic *provisional
key*, so the same on-disk artifact is the same entry on every poll, and the real
``pair_id`` is minted exactly once — inside the adoption transaction, after a
successful parse (amendment 011, validated by
``archive/clean_core_prototype/clean_core.py``).

A provisional key is an in-memory, per-poll placeholder only. It is never
written to disk: by the time anything is persisted (canonical, state, archive)
the candidate has either been minted a real id or been left unadopted.
"""
from __future__ import annotations

from pathlib import Path

_PROVISIONAL_PREFIX = "new:"


def provisional_key(tool_name: str, path: Path, slot: str | None = None) -> str:
    """Return a deterministic, poll-stable placeholder identity for one tool's
    view of an id-less artifact observed at ``(path, slot)``. Keyed per tool so
    two tools pointing at the same physical slot remain distinct candidates (and
    so collide, rather than silently merging). Not a real ``pair_id``."""
    return f"{_PROVISIONAL_PREFIX}{tool_name}:{path}::{slot or ''}"


def is_provisional(pair_id: str) -> bool:
    """Whether ``pair_id`` is a discovery placeholder rather than a minted id."""
    return pair_id.startswith(_PROVISIONAL_PREFIX)
