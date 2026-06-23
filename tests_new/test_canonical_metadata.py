"""Unit tests for the canonical store's runtime-metadata block (rebuild S23a).

The store envelope carries a nested ``metadata`` block — ``last_modified`` (the
POSIX time the artifact's user content last changed, NOT the file write time) and
``generation`` (a per-artifact monotonic content-change counter) — per the project
glossary and amendment 008. The store stamps a fresh ``last_modified`` + an
incremented ``generation`` iff the content digest changes; a re-save of identical
content preserves them (a heal/reproject must not move ``last_modified``). The
block is excluded from the content digest (FR-14), so loading ignores it — that
purity is covered by ``test_canonical_store``'s round-trip and byte-stability
tests, which now exercise this code path. Real filesystem via ``tmp_path``; the
clock is injected so there is no wall-clock dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents_sync.canonical_store import (
    CanonicalMetadata,
    load_canonical,
    load_canonical_metadata,
    save_canonical,
    save_imported_canonical,
)
from agents_sync.domain_model.canonical_document import CanonicalDocument

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
_OTHER_ID = "22222222-2222-4222-8222-222222222222"


def _document(**overrides: Any) -> CanonicalDocument:
    fields: dict[str, Any] = {
        "artifact_id": _ARTIFACT_ID,
        "kind": "agent",
        "name": "code reviewer",
        "body": "Be terse.\n",
        "tools": ("read", "edit"),
    }
    fields.update(overrides)
    return CanonicalDocument(**fields)


def test_first_save_stamps_the_clock_time_and_first_generation(tmp_path: Path) -> None:
    save_canonical(tmp_path, _document(), clock=lambda: 1000.0)

    assert load_canonical_metadata(tmp_path, _ARTIFACT_ID) == CanonicalMetadata(
        last_modified=1000.0, generation=1
    )


def test_a_content_change_advances_last_modified_and_generation(tmp_path: Path) -> None:
    save_canonical(tmp_path, _document(body="first\n"), clock=lambda: 1000.0)
    save_canonical(tmp_path, _document(body="second\n"), clock=lambda: 2000.0)

    assert load_canonical_metadata(tmp_path, _ARTIFACT_ID) == CanonicalMetadata(
        last_modified=2000.0, generation=2
    )


def test_resaving_identical_content_preserves_last_modified(tmp_path: Path) -> None:
    # A heal/reproject of unchanged content must NOT move last_modified (amendment
    # 008). The second save is byte-different but content-equivalent (tools reordered),
    # proving the rule keys on the content digest, not on the raw bytes.
    save_canonical(tmp_path, _document(tools=("read", "edit")), clock=lambda: 1000.0)
    save_canonical(tmp_path, _document(tools=("edit", "read")), clock=lambda: 9999.0)

    assert load_canonical_metadata(tmp_path, _ARTIFACT_ID) == CanonicalMetadata(
        last_modified=1000.0, generation=1
    )


def test_metadata_is_absent_for_an_unsaved_artifact(tmp_path: Path) -> None:
    assert load_canonical_metadata(tmp_path, _ARTIFACT_ID) is None


def test_generation_counts_per_artifact_not_globally(tmp_path: Path) -> None:
    # generation is a per-artifact counter (glossary): a second artifact starts at 1
    # regardless of how many other artifacts the store already holds.
    save_canonical(tmp_path, _document(), clock=lambda: 1000.0)
    save_canonical(tmp_path, _document(artifact_id=_OTHER_ID), clock=lambda: 2000.0)

    assert load_canonical_metadata(tmp_path, _OTHER_ID) == CanonicalMetadata(
        last_modified=2000.0, generation=1
    )
    # The "not globally" half: saving the second artifact must leave the first
    # artifact's own metadata untouched at generation 1 / last_modified 1000.0. A
    # global counter that perturbed pre-existing artifacts would fail here.
    assert load_canonical_metadata(tmp_path, _ARTIFACT_ID) == CanonicalMetadata(
        last_modified=1000.0, generation=1
    )


def test_save_imported_canonical_preserves_the_given_metadata(tmp_path: Path) -> None:
    # The import path writes the SOURCE's last_modified verbatim — not a fresh stamp —
    # so cross-host last_modified_wins compares correctly across machines (amendment 008).
    # A distinctive non-round last_modified a fresh stamp could not coincidentally equal,
    # so the assertion proves genuine preservation, not a re-stamp that happened to match.
    save_imported_canonical(
        tmp_path, _document(), CanonicalMetadata(last_modified=5555.25, generation=7)
    )

    assert load_canonical_metadata(tmp_path, _ARTIFACT_ID) == CanonicalMetadata(
        last_modified=5555.25, generation=7
    )


def test_save_imported_canonical_round_trips_the_content(tmp_path: Path) -> None:
    document = _document()

    save_imported_canonical(
        tmp_path, document, CanonicalMetadata(last_modified=5555.0, generation=7)
    )

    assert load_canonical(tmp_path, _ARTIFACT_ID) == document.normalised()


def test_a_generation_zero_prior_is_restamped_even_when_content_is_unchanged(
    tmp_path: Path,
) -> None:
    # A prior block that floors to generation 0 (a legacy/absent metadata block, per
    # read_envelope_metadata) carries no valid stamp, so save_canonical re-stamps it
    # even though the content digest is unchanged — the documented self-heal. Here the
    # generation-0 prior is written verbatim via the import path; the re-save uses
    # identical content and a distinct clock, and the block must advance to generation 1.
    save_imported_canonical(
        tmp_path, _document(), CanonicalMetadata(last_modified=1000.0, generation=0)
    )

    save_canonical(tmp_path, _document(), clock=lambda: 2000.0)

    assert load_canonical_metadata(tmp_path, _ARTIFACT_ID) == CanonicalMetadata(
        last_modified=2000.0, generation=1
    )
