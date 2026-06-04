"""Identity entity: the canonical pair_id, its sole minter and its validator.

`mint_pair_id` is the single place a pair_id is born (amendment 011, RC-6) — no
other module mints identity. Discovery recovers ids; the adoption transaction is
the only caller that mints. (Unrelated `uuid4` uses for unique temp-file suffixes
in the I/O gateways are not identity and live there.)
"""
from __future__ import annotations

import uuid


class InvalidPairId(ValueError):
    """Raised when a pair_id is not canonical UUIDv4 text."""


def mint_pair_id() -> str:
    """Return a fresh canonical UUIDv4 pair_id (the sole minting site)."""
    return str(uuid.uuid4())


def validate_pair_id(value: str) -> str:
    """Return `value` when it is canonical UUIDv4 text, else raise."""
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise InvalidPairId(f"pair_id is not a UUID: {value!r}") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise InvalidPairId(f"pair_id is not canonical UUIDv4: {value!r}")
    return value
