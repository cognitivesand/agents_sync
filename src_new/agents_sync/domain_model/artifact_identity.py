"""Artifact identity — the sole minter and the validator (pure, no I/O).

``mint_artifact_id`` is the single place a ``customization_artifact_id`` is born
(AD-2): discovery recovers ids from on-disk text, and only the adoption
transaction mints. Other ``uuid4`` uses (e.g. temp-file suffixes in the I/O
gateways) are not identity and live there, not here.
"""

from __future__ import annotations

import uuid


class InvalidArtifactId(ValueError):
    """Raised when a customization_artifact_id is not canonical UUIDv4 text."""


def mint_artifact_id() -> str:
    """Return a fresh canonical UUIDv4 id — the sole minting site (AD-2)."""
    return str(uuid.uuid4())


def validate_artifact_id(value: str) -> str:
    """Return ``value`` when it is canonical UUIDv4 text, else raise.

    Canonical means a version-4 UUID in its lowercase string form: identity is
    compared byte-for-byte downstream, so a parseable-but-non-canonical spelling
    (uppercase, surrounding braces) is rejected rather than silently accepted.
    """
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise InvalidArtifactId(f"artifact_id is not a UUID: {value!r}") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise InvalidArtifactId(f"artifact_id is not canonical UUIDv4: {value!r}")
    return value
