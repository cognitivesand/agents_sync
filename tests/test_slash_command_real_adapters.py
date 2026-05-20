"""Integration tests for real Claude/Codex/Cursor/opencode slash commands."""
from __future__ import annotations

import os
from pathlib import Path

from agents_sync.slash_command_io import (
    extract_pair_id_from_slash_command_markdown,
    parse_slash_command_markdown,
)
from agents_sync.state import load_state
from agents_sync.sync import Syncer


def _slash_command_md(
    body: str,
    *,
    description: str = "Exercise slash command sync",
) -> str:
    return (
        "---\n"
        f"description: {description}\n"
        'argument-hint: "[target]"\n'
        "---\n"
        f"{body}"
    )


def _slash_command_md_with_pair_id(
    pair_id: str,
    body: str,
    *,
    description: str = "Exercise slash command sync",
    argument_hint: str = "[target]",
    extra_frontmatter: tuple[str, ...] = (),
) -> str:
    frontmatter = [
        "---",
        f"pair_id: {pair_id}",
        f"description: {description}",
        f'argument-hint: "{argument_hint}"',
        *extra_frontmatter,
        "---",
    ]
    return "\n".join(frontmatter) + "\n" + body


def _parse_tool_command(
    syncer: Syncer,
    tool: str,
    path: Path,
) -> dict:
    return parse_slash_command_markdown(
        path.read_text(encoding="utf-8"),
        None,
        agentic_tool_name=tool,
        artifact_path=path,
        artifact_root=syncer.tool_root(tool, "slash_command"),
    )


def test_claude_slash_command_adopts_to_codex_and_opencode(syncer: Syncer):
    body = "Use $ARGUMENTS exactly.\n!git status\n@README.md\n"
    source = syncer.tool_root("claude", "slash_command") / "git" / "commit.md"
    source.parent.mkdir(parents=True)
    source.write_text(_slash_command_md(body), encoding="utf-8")

    assert syncer.sync_once() == 1

    injected = source.read_text(encoding="utf-8")
    pair_id = extract_pair_id_from_slash_command_markdown(injected)
    assert pair_id is not None

    codex_target = syncer.tool_root("codex", "slash_command") / "git" / "commit.md"
    opencode_target = (
        syncer.tool_root("opencode", "slash_command") / "git" / "commit.md"
    )
    assert codex_target.exists()
    assert opencode_target.exists()

    for tool, path in (("codex", codex_target), ("opencode", opencode_target)):
        canonical = _parse_tool_command(syncer, tool, path)
        assert canonical["pair_id"] == pair_id
        assert canonical["kind"] == "slash_command"
        assert canonical["name"] == "git:commit"
        assert canonical["argument_hint"] == "[target]"
        assert canonical["body"] == body

    state = load_state(syncer.state_dir)
    assert set(state[pair_id].agentic_tools) == {
        "claude",
        "codex",
        "cursor",
        "opencode",
    }


def test_duplicate_new_slash_commands_reconcile_by_mtime_before_adoption(
    syncer: Syncer,
):
    older_body = "Older Claude draft.\n"
    newer_body = "Newer Codex draft with {{args}}.\n"
    claude_source = syncer.tool_root("claude", "slash_command") / "ops" / "deploy.md"
    codex_source = syncer.tool_root("codex", "slash_command") / "ops" / "deploy.md"
    claude_source.parent.mkdir(parents=True)
    codex_source.parent.mkdir(parents=True)
    claude_source.write_text(
        _slash_command_md(older_body, description="Older draft"),
        encoding="utf-8",
    )
    codex_source.write_text(
        _slash_command_md(newer_body, description="Newer draft"),
        encoding="utf-8",
    )
    os.utime(claude_source, (1_000, 1_000))
    os.utime(codex_source, (2_000, 2_000))

    assert syncer.sync_once() == 1

    state = load_state(syncer.state_dir)
    assert len(state) == 1
    pair_id = next(iter(state))
    assert set(state[pair_id].agentic_tools) == {
        "claude",
        "codex",
        "cursor",
        "opencode",
    }

    for tool in ("claude", "codex", "opencode"):
        target = syncer.tool_root(tool, "slash_command") / "ops" / "deploy.md"
        canonical = _parse_tool_command(syncer, tool, target)
        assert canonical["pair_id"] == pair_id
        assert canonical["name"] == "ops:deploy"
        assert canonical["description"] == "Newer draft"
        assert canonical["body"] == newer_body

    archive_dir = syncer.state_dir / "archive" / pair_id / "claude"
    archived_texts = [
        path.read_text(encoding="utf-8") for path in archive_dir.glob("*.md.*")
    ]
    assert any(older_body in text for text in archived_texts)


def test_codex_slash_command_adopts_to_claude_and_opencode(syncer: Syncer):
    body = "Refactor $1 using $STYLE.\n"
    source = syncer.tool_root("codex", "slash_command") / "refactor.md"
    source.write_text(_slash_command_md(body), encoding="utf-8")

    assert syncer.sync_once() == 1

    pair_id = extract_pair_id_from_slash_command_markdown(
        source.read_text(encoding="utf-8")
    )
    assert pair_id is not None
    for tool in ("claude", "opencode"):
        target = syncer.tool_root(tool, "slash_command") / "refactor.md"
        assert target.exists()
        canonical = _parse_tool_command(syncer, tool, target)
        assert canonical["pair_id"] == pair_id
        assert canonical["name"] == "refactor"
        assert canonical["body"] == body


def test_codex_slash_command_edit_propagates_without_tool_field_leakage(
    syncer: Syncer,
):
    source = syncer.tool_root("codex", "slash_command") / "triage.md"
    source.write_text(_slash_command_md("Initial triage.\n"), encoding="utf-8")
    assert syncer.sync_once() == 1
    pair_id = extract_pair_id_from_slash_command_markdown(
        source.read_text(encoding="utf-8")
    )
    assert pair_id is not None

    updated_body = "Triage {{args}}.\n!{git diff --stat}\n@{README.md}\n"
    source.write_text(
        _slash_command_md_with_pair_id(
            pair_id,
            updated_body,
            description="Updated from Codex",
            argument_hint="[ticket]",
            extra_frontmatter=(
                "mode: inspect",
                "codex-local: keep",
            ),
        ),
        encoding="utf-8",
    )

    assert syncer.sync_once() == 1

    codex_canonical = _parse_tool_command(syncer, "codex", source)
    assert codex_canonical["per_agentic_tool_only"]["codex"] == {
        "mode": "inspect",
    }
    assert codex_canonical["per_agentic_tool_extra"]["codex"] == {
        "codex-local": "keep",
    }

    for tool in ("claude", "opencode"):
        target = syncer.tool_root(tool, "slash_command") / "triage.md"
        canonical = _parse_tool_command(syncer, tool, target)
        raw = target.read_text(encoding="utf-8")
        assert canonical["description"] == "Updated from Codex"
        assert canonical["argument_hint"] == "[ticket]"
        assert canonical["body"] == updated_body
        assert "mode: inspect" not in raw
        assert "codex-local" not in raw


def test_slash_command_conflict_uses_newest_mtime_and_archives_loser(
    syncer: Syncer,
    caplog,
):
    source = syncer.tool_root("claude", "slash_command") / "conflict.md"
    source.write_text(_slash_command_md("Base body.\n"), encoding="utf-8")
    assert syncer.sync_once() == 1
    pair_id = extract_pair_id_from_slash_command_markdown(
        source.read_text(encoding="utf-8")
    )
    assert pair_id is not None

    claude_path = source
    codex_path = syncer.tool_root("codex", "slash_command") / "conflict.md"
    opencode_path = syncer.tool_root("opencode", "slash_command") / "conflict.md"
    loser_body = "Claude older edit.\n"
    winner_body = "Codex newer edit with $ARGUMENTS.\n"
    claude_path.write_text(
        _slash_command_md_with_pair_id(
            pair_id,
            loser_body,
            description="Claude edit",
        ),
        encoding="utf-8",
    )
    codex_path.write_text(
        _slash_command_md_with_pair_id(
            pair_id,
            winner_body,
            description="Codex edit",
        ),
        encoding="utf-8",
    )
    os.utime(claude_path, (1_000, 1_000))
    os.utime(codex_path, (2_000, 2_000))

    with caplog.at_level("WARNING"):
        assert syncer.sync_once() == 1

    assert "Conflict resolved (codex wins)" in caplog.text
    for tool, path in (
        ("claude", claude_path),
        ("codex", codex_path),
        ("opencode", opencode_path),
    ):
        canonical = _parse_tool_command(syncer, tool, path)
        assert canonical["description"] == "Codex edit"
        assert canonical["body"] == winner_body

    archive_dir = syncer.state_dir / "archive" / pair_id / "claude"
    archived_texts = [
        path.read_text(encoding="utf-8") for path in archive_dir.glob("*.md.*")
    ]
    assert any(loser_body in text for text in archived_texts)


def test_slash_command_delete_on_one_tool_removes_available_counterparts(
    syncer: Syncer,
):
    source = syncer.tool_root("claude", "slash_command") / "cleanup.md"
    source.write_text(_slash_command_md("Remove me everywhere.\n"), encoding="utf-8")
    assert syncer.sync_once() == 1
    pair_id = extract_pair_id_from_slash_command_markdown(
        source.read_text(encoding="utf-8")
    )
    assert pair_id is not None

    codex_target = syncer.tool_root("codex", "slash_command") / "cleanup.md"
    cursor_target = syncer.tool_root("cursor", "slash_command") / "cleanup.md"
    opencode_target = syncer.tool_root("opencode", "slash_command") / "cleanup.md"
    codex_target.unlink()

    assert syncer.sync_once() == 1

    assert not source.exists()
    assert not codex_target.exists()
    assert not cursor_target.exists()
    assert not opencode_target.exists()
    assert pair_id not in load_state(syncer.state_dir)
    for tool in ("claude", "cursor", "opencode"):
        archive_dir = syncer.state_dir / "archive" / pair_id / tool
        assert any(archive_dir.glob("*.md.*"))


def test_opencode_reserved_slash_command_name_skips_opencode_only(
    syncer: Syncer,
    caplog,
):
    source = syncer.tool_root("claude", "slash_command") / "plan.md"
    source.write_text(_slash_command_md("Plan with {{args}}.\n"), encoding="utf-8")

    with caplog.at_level("WARNING"):
        assert syncer.sync_once() == 1

    pair_id = extract_pair_id_from_slash_command_markdown(
        source.read_text(encoding="utf-8")
    )
    assert pair_id is not None
    assert (syncer.tool_root("codex", "slash_command") / "plan.md").exists()
    assert not (syncer.tool_root("opencode", "slash_command") / "plan.md").exists()
    assert "Reserved slash_command name skipped" in caplog.text

    state = load_state(syncer.state_dir)
    assert set(state[pair_id].agentic_tools) == {"claude", "codex", "cursor"}


def test_namespaced_reserved_slash_command_skips_opencode_by_leaf_name(
    syncer: Syncer,
    caplog,
):
    source = syncer.tool_root("claude", "slash_command") / "team" / "plan.md"
    source.parent.mkdir(parents=True)
    source.write_text(_slash_command_md("Plan for $ARGUMENTS.\n"), encoding="utf-8")

    with caplog.at_level("WARNING"):
        assert syncer.sync_once() == 1

    pair_id = extract_pair_id_from_slash_command_markdown(
        source.read_text(encoding="utf-8")
    )
    assert pair_id is not None
    assert (syncer.tool_root("codex", "slash_command") / "team" / "plan.md").exists()
    assert not (
        syncer.tool_root("opencode", "slash_command") / "team" / "plan.md"
    ).exists()
    assert "Reserved slash_command name skipped" in caplog.text

    state = load_state(syncer.state_dir)
    assert set(state[pair_id].agentic_tools) == {"claude", "codex", "cursor"}

