"""Unit tests for artifact naming & the candidate key (rebuild S3a).

`slugify_name` derives the filesystem-safe basename an artifact projects to on
every tool; `candidate_key` (kind + slug) groups id-less candidate surfaces that
should be adopted as one customization artifact (US-03).
"""

from __future__ import annotations

import pytest

from agents_sync.domain_model.artifact_naming import candidate_key, slugify_name


def test_slugify_lowercases_and_replaces_unsafe_characters() -> None:
    assert slugify_name("My Agent!!") == "my-agent"


def test_slugify_collapses_adjacent_hyphens_into_one() -> None:
    # "a - b" -> "a" + "-"(space) + "-"(literal) + "-"(space) + "b" = "a---b",
    # which must collapse; if the collapse step were dropped this would be "a---b".
    assert slugify_name("a - b") == "a-b"


def test_slugify_maps_a_dot_to_a_hyphen() -> None:
    assert slugify_name("Hello.World") == "hello-world"


def test_slugify_strips_leading_and_trailing_hyphens() -> None:
    assert slugify_name("--edge--") == "edge"


def test_slugify_preserves_underscores_and_internal_hyphens() -> None:
    assert slugify_name("my_agent-v2") == "my_agent-v2"


def test_slugify_is_idempotent() -> None:
    once = slugify_name("My Agent!!")

    assert once == "my-agent"  # it actually transformed the input
    assert slugify_name(once) == once  # and the slug is a fixed point


@pytest.mark.parametrize("blank", ["", "   ", "!!!", "...."])
def test_slugify_returns_a_placeholder_when_nothing_safe_remains(blank: str) -> None:
    assert slugify_name(blank) == "converted"


@pytest.mark.parametrize(
    ("reserved", "expected"),
    [("CON", "con-item"), ("nul", "nul-item"), ("COM1", "com1-item"), ("lpt9", "lpt9-item")],
)
def test_slugify_suffixes_windows_reserved_basenames(reserved: str, expected: str) -> None:
    # A bare reserved basename is unusable on Windows, so it must be disambiguated.
    assert slugify_name(reserved) == expected


def test_candidate_key_pairs_kind_with_the_slugified_name() -> None:
    assert candidate_key("agent", "My Agent") == ("agent", "my-agent")


def test_names_that_slugify_equal_share_one_candidate_key() -> None:
    assert candidate_key("agent", "My Agent") == candidate_key("agent", "my  agent!")


def test_different_kinds_do_not_share_a_candidate_key() -> None:
    assert candidate_key("agent", "x") != candidate_key("skill", "x")


def test_same_kind_different_names_have_distinct_candidate_keys() -> None:
    assert candidate_key("agent", "alpha") != candidate_key("agent", "beta")
