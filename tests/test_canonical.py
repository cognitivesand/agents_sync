"""Canonicalization invariants — Phase 3.1 of the audit remediation.

The point of these tests is to pin the contract that two adapters
producing the same canonical (modulo list ordering, line endings, and
trailing whitespace) write byte-identical state files.
"""
from __future__ import annotations

from agents_sync.canonical import (
    canonical_content,
    canonical_digest,
    canonical_equal,
    canonical_last_modified,
    canonical_metadata,
    canonicalize,
    empty_canonical,
    set_canonical_metadata,
)


def test_canonicalize_sorts_tools_list():
    a = empty_canonical("agent")
    a["tools"] = ["Read", "Bash", "Edit"]
    normalised = canonicalize(a)
    assert normalised["tools"] == ["Bash", "Edit", "Read"]


def test_canonicalize_sorts_disallowed_tools_list():
    a = empty_canonical("agent")
    a["disallowed_tools"] = ["Write", "Edit"]
    normalised = canonicalize(a)
    assert normalised["disallowed_tools"] == ["Edit", "Write"]


def test_canonicalize_normalises_body_crlf_to_lf():
    a = empty_canonical("skill")
    a["body"] = "line1\r\nline2\r\n"
    normalised = canonicalize(a)
    assert normalised["body"] == "line1\nline2\n"


def test_canonicalize_normalises_body_cr_to_lf():
    a = empty_canonical("skill")
    a["body"] = "line1\rline2\r"
    normalised = canonicalize(a)
    assert normalised["body"] == "line1\nline2\n"


def test_canonicalize_enforces_single_trailing_newline():
    a = empty_canonical("skill")
    a["body"] = "body\n\n\n"
    normalised = canonicalize(a)
    assert normalised["body"] == "body\n"


def test_canonicalize_empty_body_stays_empty():
    a = empty_canonical("skill")
    a["body"] = ""
    normalised = canonicalize(a)
    assert normalised["body"] == ""


def test_canonicalize_strips_name_and_description():
    a = empty_canonical("agent")
    a["name"] = "  hello  "
    a["description"] = "\tworld\n"
    normalised = canonicalize(a)
    assert normalised["name"] == "hello"
    assert normalised["description"] == "world"


def test_canonicalize_preserves_none_for_nullable_fields():
    a = empty_canonical("agent")
    # model / effort / permission_mode are nullable; None is the "not set"
    # signal and must not be elided to a missing key.
    normalised = canonicalize(a)
    assert normalised["model"] is None
    assert normalised["effort"] is None
    assert normalised["permission_mode"] is None


def test_canonicalize_does_not_mutate_input():
    a = empty_canonical("agent")
    a["tools"] = ["Read", "Bash"]
    a["body"] = "line1\r\nline2\n"
    canonicalize(a)
    # Original is untouched.
    assert a["tools"] == ["Read", "Bash"]
    assert a["body"] == "line1\r\nline2\n"


def test_canonical_equal_two_orderings_are_equal():
    a = empty_canonical("agent")
    a["tools"] = ["Read", "Bash", "Edit"]
    b = empty_canonical("agent")
    b["pair_id"] = a["pair_id"]
    b["tools"] = ["Edit", "Read", "Bash"]
    assert canonical_equal(a, b)


def test_canonical_equal_distinguishes_actual_diffs():
    a = empty_canonical("agent")
    a["tools"] = ["Read"]
    b = empty_canonical("agent")
    b["pair_id"] = a["pair_id"]
    b["tools"] = ["Read", "Bash"]
    assert not canonical_equal(a, b)


def test_canonical_metadata_round_trip_helpers():
    a = empty_canonical("skill")
    set_canonical_metadata(a, last_modified=123.5, generation=4)

    assert canonical_metadata(a) == {"last_modified": 123.5, "generation": 4}
    assert canonical_last_modified(a) == 123.5


def test_canonical_content_returns_deep_copy_without_metadata():
    a = empty_canonical("agent")
    a["tools"] = ["Read"]
    set_canonical_metadata(a, last_modified=123.5, generation=4)

    content = canonical_content(a)
    content["tools"].append("Edit")

    assert "metadata" not in content
    assert a["tools"] == ["Read"]
    assert canonical_metadata(a) == {"last_modified": 123.5, "generation": 4}


def test_canonical_digest_excludes_metadata():
    a = empty_canonical("agent")
    b = dict(a)
    set_canonical_metadata(a, last_modified=1.0, generation=1)
    set_canonical_metadata(b, last_modified=2.0, generation=2)

    assert canonical_digest(a) == canonical_digest(b)


def test_canonical_digest_uses_canonicalized_content():
    a = empty_canonical("agent")
    a["tools"] = ["Read", "Bash"]
    a["body"] = "line1\r\n"
    b = empty_canonical("agent")
    b["pair_id"] = a["pair_id"]
    b["tools"] = ["Bash", "Read"]
    b["body"] = "line1\n"

    assert canonical_digest(a) == canonical_digest(b)
