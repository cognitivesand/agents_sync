"""Regression guards for bug 602c6d (state-dir size explosion / crash loop).

These pin the clean-core structural property (amendment 011): an id-less
artifact's identity is decided by parse-then-mint inside adoption, so a malformed
artifact is never minted and never churns a fresh pair_id every poll, while a
clean id-less artifact is adopted once with a stable identity.

See archive/clean_core_prototype/clean_core.py for the validated model.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

import logging
from pathlib import Path

from agents_sync.canonical import list_canonical_ids
from agents_sync.sync import Syncer

from ._helpers import make_syncer, skill_md


def _write_claude_skill(syncer: Syncer, name: str, body: str) -> Path:
    skill_dir = syncer.tool_root("claude", "skill") / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(body)
    return skill_dir


# The exact 602c6d trigger: malformed YAML (unquoted ": " in a value) AND no
# recoverable pair_id line.
_MALFORMED = "---\nname: bad\ndescription: structure): this skill helps\n---\nbody\n"


def test_unadoptable_idless_artifact_does_not_churn_identities(tmp_path: Path) -> None:
    """RC-1: a malformed, id-less artifact must not be assigned a fresh identity
    every poll. Across many polls the daemon must recognise it as the same
    unadoptable thing, never mint an id for it, and never grow the canonical
    store."""
    syncer = make_syncer(tmp_path)
    _write_claude_skill(syncer, "bad", _MALFORMED)

    seen_blocked: set[str] = set()
    canonical_counts: list[int] = []
    for _ in range(4):
        result = syncer.sync_once()
        seen_blocked |= set(result.blocked)
        canonical_counts.append(len(list(list_canonical_ids(syncer.state_dir))))

    # No identity churn: the malformed artifact is the *same* unadoptable entry
    # each poll, not a new pair_id every time. (Old code minted a fresh random
    # id per poll -> this set grows to 4.)
    assert len(seen_blocked) <= 1, f"identity churn: {seen_blocked}"
    # Never minted, never persisted.
    assert canonical_counts == [0, 0, 0, 0], canonical_counts


def test_clean_idless_artifact_is_adopted_with_stable_identity(tmp_path: Path) -> None:
    """A clean id-less artifact is adopted once; its identity is stable across
    later polls (recovered from the injected id, never re-minted)."""
    syncer = make_syncer(tmp_path)
    _write_claude_skill(syncer, "writer", skill_md("writer", description="clean"))

    syncer.sync_once()
    ids_after_first = set(list_canonical_ids(syncer.state_dir))
    assert len(ids_after_first) == 1

    syncer.sync_once()
    syncer.sync_once()
    ids_after_more = set(list_canonical_ids(syncer.state_dir))
    assert ids_after_more == ids_after_first, "identity must be stable, not re-minted"


def test_unadoptable_artifact_is_diagnosed_once_not_every_poll(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """RC-3 / NFR-12 / NFR-13: a persistently malformed, id-less artifact is
    reported with a single structured warning, not a full traceback on every
    poll (the symptom was 6.08 M identical error lines)."""
    syncer = make_syncer(tmp_path)
    _write_claude_skill(syncer, "bad", _MALFORMED)

    with caplog.at_level(logging.WARNING):
        for _ in range(4):
            syncer.sync_once()

    diagnoses = [r for r in caplog.records if "Unadoptable artifact" in r.getMessage()]
    assert len(diagnoses) == 1, f"expected one diagnosis across 4 polls, got {len(diagnoses)}"

    # The expected (user-fixable) malformed-content case must not be logged as an
    # unexpected error with a stack trace, and certainly not every poll.
    spam = [
        r
        for r in caplog.records
        if r.exc_info is not None
        and ("Cannot plan adoption target" in r.getMessage() or "cannot parse" in r.getMessage())
    ]
    assert spam == [], f"per-poll traceback spam for an expected malformed file: {len(spam)}"
