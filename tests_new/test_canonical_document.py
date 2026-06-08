"""Unit tests for the pure canonical-document entity (rebuild S1).

Covers FR-14 (content-digest over content only, metadata excluded), NFR-16
(lossless canonical representation: dict round-trip), the normalisation that makes
two semantically-equal documents hash identically, and the value-object contract
(immutable, read-only bags, content-consistent hashing).
"""

from __future__ import annotations

import re
from dataclasses import FrozenInstanceError

import pytest

import agents_sync
from agents_sync.domain_model.canonical_document import CanonicalDocument, CorruptCanonical


def _agent_doc(**overrides: object) -> dict[str, object]:
    """A representative canonical-content dict; overrides patch single fields."""
    base: dict[str, object] = {
        "artifact_id": "11111111-1111-4111-8111-111111111111",
        "kind": "agent",
        "name": "code reviewer",
        "description": "reviews diffs",
        "body": "Be terse.\n",
        "model": "opus",
        "effort": None,
        "tools": ["read", "edit"],
        "disallowed_tools": [],
        "permission_mode": None,
        "provenance": "user",
        "per_tool_only": {"claude": {"color": "blue"}},
        "per_tool_extra": {"codex": {"x_unknown": 1}},
    }
    base.update(overrides)
    return base


def test_parallel_tree_is_the_one_under_test() -> None:
    # Guards the src_new isolation: this suite must exercise the rebuild, not the
    # editable install of src/.
    assert "src_new" in (agents_sync.__file__ or "")


# --- round-trip / lossless representation (NFR-16) ------------------------------


def test_from_dict_then_to_dict_round_trips() -> None:
    source = _agent_doc()

    restored = CanonicalDocument.from_dict(source).to_dict()

    assert restored == source


def test_from_dict_is_inverse_of_to_dict_as_objects() -> None:
    doc = CanonicalDocument.from_dict(_agent_doc())

    assert CanonicalDocument.from_dict(doc.to_dict()) == doc


# --- normalisation -------------------------------------------------------------


def test_normalised_actually_normalises_and_is_idempotent() -> None:
    doc = CanonicalDocument.from_dict(_agent_doc(tools=["read", "edit"], name="  spaced  "))

    once = doc.normalised()

    assert once != doc  # it genuinely changed something (sorted tools, stripped name)
    assert once.normalised() == once  # and applying it again is a no-op


def test_order_insensitive_lists_normalise_equal() -> None:
    forward = CanonicalDocument.from_dict(_agent_doc(tools=["read", "edit"]))
    reversed_ = CanonicalDocument.from_dict(_agent_doc(tools=["edit", "read"]))

    assert forward.normalised() == reversed_.normalised()


def test_body_line_endings_normalised_to_lf_with_single_trailing_newline() -> None:
    doc = CanonicalDocument.from_dict(_agent_doc(body="a\r\nb\r\n\n\n"))

    assert doc.normalised().body == "a\nb\n"


def test_whitespace_only_body_normalises_to_empty_string() -> None:
    doc = CanonicalDocument.from_dict(_agent_doc(body="\n\n"))

    assert doc.normalised().body == ""


def test_name_and_description_are_stripped_by_normalisation() -> None:
    doc = CanonicalDocument.from_dict(_agent_doc(name="  x  ", description="\ty\n"))

    normalised = doc.normalised()

    assert normalised.name == "x"
    assert normalised.description == "y"


# --- content digest (FR-14) ----------------------------------------------------


def test_content_digest_is_lowercase_hex_sha256() -> None:
    digest = CanonicalDocument.from_dict(_agent_doc()).content_digest()

    assert re.fullmatch(r"[0-9a-f]{64}", digest) is not None


def test_content_digest_is_equal_for_semantically_equal_documents() -> None:
    a = CanonicalDocument.from_dict(_agent_doc(tools=["read", "edit"], body="hi\n"))
    b = CanonicalDocument.from_dict(_agent_doc(tools=["edit", "read"], body="hi\r\n"))

    assert a.content_digest() == b.content_digest()


def test_content_digest_changes_when_body_changes() -> None:
    a = CanonicalDocument.from_dict(_agent_doc(body="one\n"))
    b = CanonicalDocument.from_dict(_agent_doc(body="two\n"))

    assert a.content_digest() != b.content_digest()


def test_runtime_metadata_does_not_enter_the_document() -> None:
    # FR-14: metadata must neither survive into the representation nor perturb the
    # digest. Asserted both directly (absent from to_dict) and via the digest.
    plain = CanonicalDocument.from_dict(_agent_doc())
    with_metadata = CanonicalDocument.from_dict(
        _agent_doc() | {"metadata": {"last_modified": 1234.5, "generation": 7}}
    )

    assert "metadata" not in with_metadata.to_dict()
    assert with_metadata.content_digest() == plain.content_digest()


# --- value-object contract: immutable, read-only bags, content-hash ------------


def test_from_dict_isolates_the_document_from_later_source_mutation() -> None:
    source = _agent_doc()
    doc = CanonicalDocument.from_dict(source)

    source["per_tool_only"]["claude"]["color"] = "red"  # type: ignore[index]

    assert doc.to_dict()["per_tool_only"]["claude"]["color"] == "blue"


def test_to_dict_returns_a_copy_the_caller_cannot_use_to_mutate_the_document() -> None:
    doc = CanonicalDocument.from_dict(_agent_doc())

    doc.to_dict()["per_tool_only"]["claude"]["color"] = "red"

    assert doc.to_dict()["per_tool_only"]["claude"]["color"] == "blue"


def test_per_tool_bags_reject_in_place_rebinding() -> None:
    doc = CanonicalDocument.from_dict(_agent_doc())

    with pytest.raises(TypeError):
        doc.per_tool_only["claude"] = {}  # type: ignore[index]


def test_per_tool_bag_nested_fields_also_reject_mutation() -> None:
    # The freeze is deep: a nested field mapping must be read-only too, else the
    # content digest could be changed in place (FR-14 stability).
    doc = CanonicalDocument.from_dict(_agent_doc())

    with pytest.raises(TypeError):
        doc.per_tool_only["claude"]["color"] = "red"  # type: ignore[index]


def test_per_tool_bag_list_leaves_are_immutable_but_round_trip_as_lists() -> None:
    # A list value inside a bag is frozen to a tuple (no in-place append can change
    # the digest), yet to_dict restores it as a JSON list (NFR-16 fidelity).
    doc = CanonicalDocument.from_dict(_agent_doc(per_tool_extra={"codex": {"items": ["a", "b"]}}))

    with pytest.raises(AttributeError):
        doc.per_tool_extra["codex"]["items"].append("c")  # tuple has no append

    assert doc.to_dict()["per_tool_extra"]["codex"]["items"] == ["a", "b"]


def test_equal_documents_are_hashable_and_hash_equal() -> None:
    a = CanonicalDocument.from_dict(_agent_doc())
    b = CanonicalDocument.from_dict(_agent_doc())

    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1


# --- boundary validation (§8) --------------------------------------------------


def test_normalised_sorts_disallowed_tools() -> None:
    # The order-insensitivity guarantee applies to disallowed_tools as well as tools.
    doc = CanonicalDocument.from_dict(_agent_doc(disallowed_tools=["write", "edit", "bash"]))

    assert doc.normalised().disallowed_tools == ("bash", "edit", "write")


def test_content_digest_is_stable_across_repeated_calls() -> None:
    # FR-14: the digest of one document is deterministic call-to-call.
    doc = CanonicalDocument.from_dict(_agent_doc())

    assert doc.content_digest() == doc.content_digest()


@pytest.mark.parametrize("required_field", ["artifact_id", "kind"])
def test_from_dict_rejects_an_absent_required_field(required_field: str) -> None:
    data = _agent_doc()
    del data[required_field]

    with pytest.raises(ValueError, match=required_field):
        CanonicalDocument.from_dict(data)


@pytest.mark.parametrize("required_field", ["artifact_id", "kind"])
def test_from_dict_rejects_an_empty_required_field(required_field: str) -> None:
    data = _agent_doc()
    data[required_field] = ""

    with pytest.raises(ValueError, match=required_field):
        CanonicalDocument.from_dict(data)


# --- corrupt-canonical marker (rebuild S6c) ------------------------------------


def test_corrupt_canonical_is_an_immutable_value_object() -> None:
    # The canonical-store load result is `CanonicalDocument | CorruptCanonical`; the
    # planner routes the corrupt case to `rebuild_corrupt_canonical` (US-09 AC-4).
    a_failure = CorruptCanonical(reason="truncated json")

    assert a_failure == CorruptCanonical(reason="truncated json")
    assert a_failure != CorruptCanonical(reason="other")
    with pytest.raises(FrozenInstanceError):
        a_failure.reason = "changed"  # type: ignore[misc]
