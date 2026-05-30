"""US-03 AC-11 / FR-11 — a managed customization artifact whose on-disk content
becomes malformed is *frozen* (reported blocked, never synced, never removed)
with a structured warning, while its identity tag is recovered in isolation; and
a malformed *new* artifact never blocks a clean sibling's adoption (AC-10).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

import logging
from pathlib import Path

from agents_sync.state import load_state
from agents_sync.sync import Syncer

from ._helpers import make_syncer, skill_md


def _write_claude_skill(syncer: Syncer, name: str, body: str) -> Path:
    skill_dir = syncer.tool_root("claude", "skill") / name
    skill_dir.mkdir(parents=True)
    md = skill_dir / "SKILL.md"
    md.write_text(body)
    return md


def _corrupt_description(md: Path) -> None:
    """Replace the description line with an unquoted `: ` (invalid YAML),
    leaving the injected pair_id line intact."""
    lines = md.read_text().splitlines()
    rewritten = [
        "description: source/test pair: each pair" if line.startswith("description:") else line
        for line in lines
    ]
    md.write_text("\n".join(rewritten) + "\n")


def test_managed_artifact_with_malformed_content_is_frozen_not_removed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    syncer = make_syncer(tmp_path)
    md = _write_claude_skill(syncer, "demo", skill_md("demo", description="clean"))
    syncer.sync_once()  # adopt + propagate to the other tools

    state = load_state(syncer.state_dir)
    pair_id = next(iter(state))
    assert "codex" in state[pair_id].agentic_tools
    codex_copy = syncer.tool_root("codex", "skill") / "demo" / "SKILL.md"
    assert codex_copy.exists()

    assert "pair_id:" in md.read_text()
    _corrupt_description(md)

    with caplog.at_level(logging.WARNING):
        result = syncer.sync_once()

    # Frozen: reported blocked, not failed; never synced; never removed.
    assert pair_id in result.blocked
    assert pair_id not in result.failed
    assert codex_copy.exists()  # not interpreted as a removal
    assert pair_id in load_state(syncer.state_dir)
    assert "Frozen — unparseable artifact content" in caplog.text


def test_malformed_new_artifact_does_not_block_a_clean_sibling(tmp_path: Path) -> None:
    syncer = make_syncer(tmp_path)
    _write_claude_skill(syncer, "good", skill_md("good", description="fine"))
    # A brand-new artifact (no pair_id) with malformed metadata.
    _write_claude_skill(syncer, "bad", "---\nname: bad\ndescription: a: b: c\n---\nbody\n")

    syncer.sync_once()

    # AC-10: the clean sibling adopts and propagates; the malformed one is not
    # used to block it, and is itself never propagated.
    assert (syncer.tool_root("codex", "skill") / "good" / "SKILL.md").exists()
    assert not (syncer.tool_root("codex", "skill") / "bad" / "SKILL.md").exists()
