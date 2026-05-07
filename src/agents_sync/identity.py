"""Identity validation helpers."""
from __future__ import annotations

import uuid


class InvalidPairId(ValueError):
    """Raised when a pair_id is not canonical UUIDv4 text."""


def validate_pair_id(value: str) -> str:
    """Return `value` when it is canonical UUIDv4 text, else raise."""
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise InvalidPairId(f"pair_id is not a UUID: {value!r}") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise InvalidPairId(f"pair_id is not canonical UUIDv4: {value!r}")
    return value
