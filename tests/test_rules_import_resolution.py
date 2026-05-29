"""US-15: global-rules `@import` resolution + framework-specific egress guard.

Unit tests cover ``resolve_rules_imports`` and ``detect_framework_specific``;
integration tests drive ``Syncer.sync_once`` over the two-tool harness from
``test_rules_filename_detection`` (claudelike detects AGENTS.md>CLAUDE.md,
codexlike detects/creates AGENTS.md).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

from pathlib import Path

from agents_sync.rules_io import (
    RulesImportError,
    detect_framework_specific,
    resolve_rules_imports,
)

from .test_rules_filename_detection import _syncer

# ---------- unit: resolve_rules_imports ----------


def test_resolve_inlines_a_single_import(tmp_path: Path):
    (tmp_path / "shared.md").write_text("Shared body.\n")
    effective, had = resolve_rules_imports("@shared.md\nlocal line\n", tmp_path)
    assert had is True
    assert "Shared body." in effective
    assert "@shared.md" not in effective
    assert "local line" in effective


def test_resolve_is_transitive(tmp_path: Path):
    (tmp_path / "a.md").write_text("@b.md\n")
    (tmp_path / "b.md").write_text("deep content\n")
    effective, had = resolve_rules_imports("@a.md\n", tmp_path)
    assert had is True
    assert "deep content" in effective


def test_resolve_without_directive_returns_body_verbatim(tmp_path: Path):
    body = "no imports here\njust text\n"
    effective, had = resolve_rules_imports(body, tmp_path)
    assert had is False
    assert effective == body


def test_resolve_missing_target_raises(tmp_path: Path):
    with pytest.raises(RulesImportError):
        resolve_rules_imports("@nope.md\n", tmp_path)


def test_resolve_escaping_root_raises(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.md").write_text("secret\n")
    with pytest.raises(RulesImportError):
        resolve_rules_imports("@../outside.md\n", root)


def test_resolve_cycle_raises(tmp_path: Path):
    (tmp_path / "a.md").write_text("@b.md\n")
    (tmp_path / "b.md").write_text("@a.md\n")
    with pytest.raises(RulesImportError):
        resolve_rules_imports("@a.md\n", tmp_path)


# ---------- unit: detect_framework_specific ----------


@pytest.mark.parametrize(
    "body",
    [
        "See ~/.claude/skills for details.",
        "edit .codex/prompts/foo",
        r"on windows: C:\Users\me\.cursor\rules",
        "look under ~/.config/github-copilot/",
    ],
)
def test_detect_flags_tool_private_paths(body: str):
    assert detect_framework_specific(body) is not None


def test_detect_returns_none_for_generic_content():
    assert detect_framework_specific("Always write small, tested functions.") is None


# ---------- integration: @import resolution (AC-2 / AC-3) ----------


def test_import_resolved_for_others_source_directive_preserved(tmp_path: Path):
    syncer = _syncer(tmp_path)
    claude_root = syncer.tool_root("claudelike", "rules")
    (claude_root / "CLAUDE.md").write_text(
        "---\nname: global\n---\n@shared.md\nClaude-authored note.\n"
    )
    (claude_root / "shared.md").write_text("Shared imported content.\n")

    result = syncer.sync_once()

    assert result.changed == 1
    # AC-2: the source keeps its @import directive; it is not flattened.
    source_text = (claude_root / "CLAUDE.md").read_text()
    assert "@shared.md" in source_text
    assert "Shared imported content." not in source_text
    # AC-3: the other tool receives the resolved effective content inline.
    target_text = (syncer.tool_root("codexlike", "rules") / "AGENTS.md").read_text()
    assert "Shared imported content." in target_text
    assert "Claude-authored note." in target_text
    assert "@shared.md" not in target_text


def test_missing_import_fails_closed_without_propagating(tmp_path: Path):
    syncer = _syncer(tmp_path)
    claude_root = syncer.tool_root("claudelike", "rules")
    (claude_root / "CLAUDE.md").write_text("---\nname: global\n---\n@nope.md\n")

    result = syncer.sync_once()

    # AC-4: skipped + recorded as failed, nothing partially synced, no crash.
    assert result.failed
    assert not (syncer.tool_root("codexlike", "rules") / "AGENTS.md").exists()


# ---------- integration: framework-specific egress guard ----------


def test_framework_specific_source_is_held_back(tmp_path: Path, caplog):
    syncer = _syncer(tmp_path)
    claude_root = syncer.tool_root("claudelike", "rules")
    (claude_root / "CLAUDE.md").write_text(
        "---\nname: global\n---\nKeep skills under ~/.claude/skills.\n"
    )

    with caplog.at_level("WARNING", logger="root"):
        result = syncer.sync_once()

    # Whole file is not mapped to the other tool.
    assert result.changed == 0
    assert not (syncer.tool_root("codexlike", "rules") / "AGENTS.md").exists()
    assert any(
        getattr(rec, "event", "") == "rules_framework_specific_held_back"
        for rec in caplog.records
    )


def test_framework_specific_reached_through_import_is_held_back(tmp_path: Path):
    syncer = _syncer(tmp_path)
    claude_root = syncer.tool_root("claudelike", "rules")
    (claude_root / "CLAUDE.md").write_text("---\nname: global\n---\n@private.md\n")
    (claude_root / "private.md").write_text("Edit agents under ~/.claude/agents.\n")

    syncer.sync_once()

    # The framework token lives in the imported file; the resolved effective
    # body still trips the guard, so nothing propagates.
    assert not (syncer.tool_root("codexlike", "rules") / "AGENTS.md").exists()


def test_framework_specific_target_is_not_overwritten(tmp_path: Path):
    syncer = _syncer(tmp_path)
    claude_root = syncer.tool_root("claudelike", "rules")
    codex_root = syncer.tool_root("codexlike", "rules")
    (claude_root / "CLAUDE.md").write_text(
        "---\nname: global\n---\nGeneric shared rules.\n"
    )
    codex_specific = "---\nname: global\n---\nUse ~/.codex/prompts here.\n"
    (codex_root / "AGENTS.md").write_text(codex_specific)

    syncer.sync_once()

    # codexlike's framework-specific file is left exactly as authored.
    assert (codex_root / "AGENTS.md").read_text() == codex_specific
