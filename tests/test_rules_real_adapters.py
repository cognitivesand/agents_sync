"""Rules integration tests for Claude Code, Codex, and opencode adapters."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration  # audit slice 10 · TQ-01

import json
import os
from pathlib import Path

from agents_sync.sync import Syncer


def _state(syncer: Syncer) -> dict:
    return json.loads((syncer.state_dir / "state.json").read_text())


def _only_entry(syncer: Syncer) -> tuple[str, dict]:
    entries = _state(syncer)["customization_artifacts"]
    assert len(entries) == 1
    pair_id = next(iter(entries))
    return pair_id, entries[pair_id]


def test_claude_global_rules_sync_to_codex_and_opencode(syncer: Syncer):
    claude_rules = syncer.tool_root("claude", "rules") / "CLAUDE.md"
    claude_rules.write_text("Prefer small, direct changes.\n")

    result = syncer.sync_once(); changed = result.changed

    assert changed == 1
    pair_id, entry = _only_entry(syncer)
    assert entry["customization_type"] == "rules"
    assert set(entry["agentic_tools"]) == {"claude", "codex", "opencode"}
    assert f"pair_id: {pair_id}" in claude_rules.read_text()

    codex_rules = syncer.tool_root("codex", "rules") / "AGENTS.md"
    opencode_rules = syncer.tool_root("opencode", "rules") / "AGENTS.md"
    assert codex_rules.is_file()
    assert opencode_rules.is_file()
    assert "Prefer small, direct changes." in codex_rules.read_text()
    assert "Prefer small, direct changes." in opencode_rules.read_text()

    canonical_path = syncer.state_dir / "canonical" / f"{pair_id}.json"
    canonical = json.loads(canonical_path.read_text())
    assert canonical["kind"] == "rules"
    assert canonical["name"] == "global"


def test_rules_discovery_ignores_unmanaged_markdown_in_rules_roots(syncer: Syncer):
    ignored = syncer.tool_root("codex", "rules") / "README.md"
    ignored.write_text("not a Codex rules surface\n")
    codex_rules = syncer.tool_root("codex", "rules") / "AGENTS.md"
    codex_rules.write_text("Use the repo conventions.\n")

    syncer.sync_once()

    pair_id, entry = _only_entry(syncer)
    assert entry["customization_type"] == "rules"
    assert Path(entry["agentic_tools"]["codex"]["path"]).name == "AGENTS.md"
    assert "pair_id:" not in ignored.read_text()
    assert f"pair_id: {pair_id}" in codex_rules.read_text()


def test_first_boot_reconciles_global_rules_across_real_adapters(syncer: Syncer):
    claude_rules = syncer.tool_root("claude", "rules") / "CLAUDE.md"
    codex_rules = syncer.tool_root("codex", "rules") / "AGENTS.md"
    opencode_rules = syncer.tool_root("opencode", "rules") / "AGENTS.md"
    claude_rules.write_text("Claude version.\n")
    codex_rules.write_text("Codex version.\n")
    opencode_rules.write_text("opencode version wins.\n")
    os.utime(claude_rules, (1000.0, 1000.0))
    os.utime(codex_rules, (2000.0, 2000.0))
    os.utime(opencode_rules, (3000.0, 3000.0))

    syncer.sync_once()

    _pair_id, entry = _only_entry(syncer)
    assert set(entry["agentic_tools"]) == {"claude", "codex", "opencode"}
    assert "opencode version wins." in claude_rules.read_text()
    assert "opencode version wins." in codex_rules.read_text()
    assert "opencode version wins." in opencode_rules.read_text()
