"""Integration tests for real Claude/Codex/opencode slash_command adapters."""
from __future__ import annotations

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
    assert set(state[pair_id].agentic_tools) == {"claude", "codex", "opencode"}


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
    assert set(state[pair_id].agentic_tools) == {"claude", "codex"}

