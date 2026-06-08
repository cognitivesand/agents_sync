"""Unit tests for the pure artifact-identity module (rebuild S2).

Covers the sole minter (mint_artifact_id — the single uuid4 site, AD-2) and the
validator (validate_artifact_id — canonical UUIDv4, fail-fast §8).
"""

from __future__ import annotations

import uuid

import pytest

from agents_sync.domain_model.artifact_identity import (
    InvalidArtifactId,
    mint_artifact_id,
    validate_artifact_id,
)

# Includes alphabetic hex digits so the uppercase-rejection test is not vacuous.
_CANONICAL_V4 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_mint_returns_a_canonical_uuid4() -> None:
    minted = mint_artifact_id()

    assert validate_artifact_id(minted) == minted  # accepted as canonical v4
    assert uuid.UUID(minted).version == 4


def test_mint_returns_a_fresh_id_on_every_call() -> None:
    minted = [mint_artifact_id() for _ in range(100)]

    assert len(set(minted)) == len(minted)


def test_validate_accepts_a_canonical_v4_and_returns_it_unchanged() -> None:
    assert validate_artifact_id(_CANONICAL_V4) == _CANONICAL_V4


def test_validate_rejects_non_uuid_text() -> None:
    with pytest.raises(InvalidArtifactId):
        validate_artifact_id("not-a-uuid")


def test_validate_rejects_a_non_v4_uuid() -> None:
    # Same digits but the version nibble is 1 (a UUIDv1 shape), not 4.
    v1_shaped = "11111111-1111-1111-8111-111111111111"

    with pytest.raises(InvalidArtifactId):
        validate_artifact_id(v1_shaped)


def test_validate_rejects_a_non_canonical_uppercase_form() -> None:
    # uuid.UUID parses case-insensitively, but the canonical text is lowercase; an
    # uppercased id must be rejected so identity comparison stays byte-exact.
    with pytest.raises(InvalidArtifactId):
        validate_artifact_id(_CANONICAL_V4.upper())


def test_a_validation_failure_is_catchable_as_a_value_error() -> None:
    # Fail-fast contract (§8): callers may catch the broad ValueError. Proven by a
    # real raised failure, not just the class hierarchy declared on paper.
    with pytest.raises(ValueError):
        validate_artifact_id("not-a-uuid")


def test_a_brace_wrapped_uuid_is_rejected_as_non_canonical() -> None:
    # uuid.UUID parses "{...}" but str() drops the braces, so it is not the canonical
    # spelling — the `str(parsed) != value` guard must reject it (FR-11), a distinct
    # rejection path from the uppercase/version cases.
    with pytest.raises(InvalidArtifactId):
        validate_artifact_id("{" + _CANONICAL_V4 + "}")
