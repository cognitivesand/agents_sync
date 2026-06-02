"""Regression: adopt a canonical whose body uses CRLF line endings.

The digest recorded in state after the first projection must compare equal to
the projected tool-side file on the next poll so no phantom re-projection loop
fires (NFR-05). Covers the adopt-from-CRLF-source path that
test_text_newline_convergence.py does not exercise (that file tests the
tool-side-edit CRLF path; this file tests the canonical-as-source CRLF path).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agents_sync.canonical import save_canonical, set_canonical_metadata
from agents_sync.state import load_state

from ._helpers import make_syncer

_PAIR_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def _write_crlf_canonical(syncer, pair_id: str, name: str, lf_body: str) -> None:
    """Write a canonical whose body field uses CRLF line endings to the store."""
    canonical = {
        "pair_id": pair_id,
        "kind": "skill",
        "name": name,
        "description": "crlf regression test",
        "body": lf_body.replace("\n", "\r\n"),
        "per_agentic_tool_only": {},
        "per_agentic_tool_extra": {},
    }
    set_canonical_metadata(canonical, last_modified=1_000_000.0, generation=1)
    save_canonical(syncer.state_dir, pair_id, canonical)


def test_adopt_crlf_canonical_first_sync_projects_second_is_noop(tmp_path: Path) -> None:
    """Adopting a CRLF-body canonical must not cause a phantom re-projection loop.

    Regression for the digest normalisation fix (v0.6): the digest recorded in
    state after the first projection must compare equal on the next poll even
    when the adapter normalises CRLF→LF during rendering (NFR-05).
    """
    syncer = make_syncer(tmp_path)
    _write_crlf_canonical(syncer, _PAIR_ID, "crlf-skill", "line one\nline two\nline three\n")

    # The canonical is an orphan; the first poll adopts (FR-16) and projects it.
    first = syncer.sync_once()
    assert first.changed >= 1

    skill_file = syncer.tool_root("claude", "skill") / "crlf-skill" / "SKILL.md"
    assert skill_file.exists()
    assert _PAIR_ID in load_state(syncer.state_dir)

    # Second poll must be a strict no-op (no stale-digest re-projection loop).
    second = syncer.sync_once()
    assert second.changed == 0


def test_adopt_crlf_canonical_idempotent_across_multiple_polls(tmp_path: Path) -> None:
    """CRLF digest idempotency is stable across several consecutive polls."""
    syncer = make_syncer(tmp_path)
    _write_crlf_canonical(
        syncer, _PAIR_ID, "multi-poll", "first line\nsecond line\nthird line\n"
    )

    syncer.sync_once()  # adopt + project

    for _ in range(3):
        result = syncer.sync_once()
        assert result.changed == 0
