"""Unit tests for v0.5 slash_command parse / render helpers."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from agents_sync.slash_command_io import (
    extract_pair_id_from_slash_command_markdown,
    extract_pair_id_from_slash_command_toml,
    parse_slash_command_markdown,
    parse_slash_command_toml,
    render_slash_command_markdown,
    render_slash_command_toml,
    slash_command_slug,
)

PAIR_ID = "00000000-0000-4000-8000-000000000101"


def test_markdown_slash_command_parse_preserves_body_and_namespaced_path(
    tmp_path: Path,
):
    body = "Use $ARGUMENTS exactly.\n!git status\n@README.md\n"
    text = (
        "---\n"
        f"pair_id: {PAIR_ID}\n"
        "description: Commit staged work\n"
        'argument-hint: "[scope]"\n'
        "allowed-tools:\n"
        "  - Bash(git:*)\n"
        "model: claude-sonnet\n"
        "mode: plan\n"
        "vendor-field: keep\n"
        "---\n"
        f"{body}"
    )
    root = tmp_path / "commands"
    path = root / "git" / "commit.md"

    canonical = parse_slash_command_markdown(
        text,
        None,
        agentic_tool_name="mdtool",
        artifact_path=path,
        artifact_root=root,
    )

    assert canonical["pair_id"] == PAIR_ID
    assert canonical["kind"] == "slash_command"
    assert canonical["name"] == "git:commit"
    assert canonical["description"] == "Commit staged work"
    assert canonical["argument_hint"] == "[scope]"
    assert canonical["allowed_tools"] == ["Bash(git:*)"]
    assert canonical["body"] == body
    assert canonical["per_agentic_tool_only"]["mdtool"] == {"mode": "plan"}
    assert canonical["per_agentic_tool_extra"]["mdtool"] == {"vendor-field": "keep"}
    assert extract_pair_id_from_slash_command_markdown(text) == PAIR_ID

    rendered = render_slash_command_markdown(
        canonical,
        None,
        agentic_tool_name="mdtool",
    )
    reparsed = parse_slash_command_markdown(
        rendered,
        canonical,
        agentic_tool_name="mdtool",
        artifact_path=path,
        artifact_root=root,
    )

    assert reparsed["name"] == "git:commit"
    assert reparsed["body"] == body
    assert reparsed["allowed_tools"] == ["Bash(git:*)"]


def test_markdown_slash_command_rejects_non_mapping_frontmatter():
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        parse_slash_command_markdown(
            "---\n- bad\n---\nbody",
            None,
            agentic_tool_name="mdtool",
        )


def test_markdown_without_frontmatter_generates_identity_from_path(tmp_path: Path):
    body = "Use {{args}} and $ARGUMENTS.\n!{git status}\n@{README.md}\n"
    text = f"\ufeff{body}"
    root = tmp_path / "commands"
    path = root / "ops" / "deploy.md"

    canonical = parse_slash_command_markdown(
        text,
        None,
        agentic_tool_name="mdtool",
        artifact_path=path,
        artifact_root=root,
    )

    assert canonical["kind"] == "slash_command"
    assert canonical["name"] == "ops:deploy"
    assert canonical["body"] == body
    assert extract_pair_id_from_slash_command_markdown(text) is None

    rendered = render_slash_command_markdown(
        canonical,
        None,
        agentic_tool_name="mdtool",
    )
    assert extract_pair_id_from_slash_command_markdown(rendered) == canonical["pair_id"]
    assert rendered.endswith(body)


def test_markdown_render_keeps_tool_specific_fields_isolated():
    canonical = {
        "pair_id": PAIR_ID,
        "kind": "slash_command",
        "name": "review",
        "description": "Review a target",
        "argument_hint": "[target]",
        "allowed_tools": ["Read", "Bash(git:*)"],
        "model": "gpt-5",
        "body": "Review $ARGUMENTS.\n",
        "per_agentic_tool_only": {
            "claude": {"agent": "reviewer", "mode": "plan"},
            "codex": {"mode": "execute"},
        },
        "per_agentic_tool_extra": {
            "claude": {"claude-extra": "private"},
            "codex": {"codex-extra": "retained"},
        },
    }

    rendered = render_slash_command_markdown(
        canonical,
        None,
        agentic_tool_name="codex",
    )
    reparsed = parse_slash_command_markdown(
        rendered,
        None,
        agentic_tool_name="codex",
    )

    assert reparsed["per_agentic_tool_only"]["codex"] == {"mode": "execute"}
    assert reparsed["per_agentic_tool_extra"]["codex"] == {
        "codex-extra": "retained",
    }
    assert "claude-extra" not in rendered
    assert "agent: reviewer" not in rendered


def test_markdown_render_preserves_prior_frontmatter_comments_and_unknowns():
    canonical = {
        "pair_id": PAIR_ID,
        "kind": "slash_command",
        "name": "review",
        "description": "Review a target",
        "argument_hint": "[target]",
        "body": "Review $ARGUMENTS.\n",
        "per_agentic_tool_only": {"codex": {"mode": "execute"}},
        "per_agentic_tool_extra": {"codex": {}},
    }
    prior = (
        "---\n"
        "# user-owned comment\n"
        "name: old-path-fallback\n"
        "description: old\n"
        "vendor-field: keep\n"
        "---\n"
        "old body\n"
    )

    rendered = render_slash_command_markdown(
        canonical,
        prior,
        agentic_tool_name="codex",
    )

    assert "# user-owned comment" in rendered
    assert "vendor-field: keep" in rendered
    assert "name: old-path-fallback" not in rendered
    assert "description: Review a target" in rendered
    assert "mode: execute" in rendered


def test_toml_slash_command_maps_prompt_to_body_and_back(tmp_path: Path):
    body = "Run !{git status}\nOpen @{README.md}\nKeep {{args}}\n"
    text = "\n".join([
        f'pair_id = "{PAIR_ID}"',
        'description = "Gemini command"',
        'argument_hint = "[ticket]"',
        'allowed_tools = ["Shell(git:*)"]',
        'mode = "investigate"',
        'vendor_field = "keep"',
        f"prompt = {json.dumps(body)}",
        "",
    ])
    root = tmp_path / "commands"
    path = root / "git" / "status.toml"

    canonical = parse_slash_command_toml(
        text,
        None,
        agentic_tool_name="tomltool",
        artifact_path=path,
        artifact_root=root,
    )

    assert canonical["pair_id"] == PAIR_ID
    assert canonical["name"] == "git:status"
    assert canonical["description"] == "Gemini command"
    assert canonical["argument_hint"] == "[ticket]"
    assert canonical["allowed_tools"] == ["Shell(git:*)"]
    assert canonical["body"] == body
    assert canonical["per_agentic_tool_only"]["tomltool"] == {"mode": "investigate"}
    assert canonical["per_agentic_tool_extra"]["tomltool"] == {"vendor_field": "keep"}
    assert extract_pair_id_from_slash_command_toml(text) == PAIR_ID

    rendered = render_slash_command_toml(canonical, None, agentic_tool_name="tomltool")
    reparsed = parse_slash_command_toml(
        rendered,
        canonical,
        agentic_tool_name="tomltool",
        artifact_path=path,
        artifact_root=root,
    )

    assert reparsed["name"] == "git:status"
    assert reparsed["body"] == body
    assert reparsed["per_agentic_tool_extra"]["tomltool"] == {"vendor_field": "keep"}


def test_toml_accepts_hyphenated_aliases_and_renders_extra_scalars(tmp_path: Path):
    body = "Summarize {{args}}.\n"
    text = "\n".join([
        f'pair_id = "{PAIR_ID}"',
        '"argument-hint" = "[topic]"',
        '"allowed-tools" = "Read, Shell(git:*)"',
        '"extra key" = true',
        "retry_count = 3",
        f"prompt = {json.dumps(body)}",
        "",
    ])
    root = tmp_path / "commands"
    path = root / "notes" / "summarize.toml"

    canonical = parse_slash_command_toml(
        text,
        None,
        agentic_tool_name="tomltool",
        artifact_path=path,
        artifact_root=root,
    )

    assert canonical["name"] == "notes:summarize"
    assert canonical["argument_hint"] == "[topic]"
    assert canonical["allowed_tools"] == ["Read", "Shell(git:*)"]
    assert canonical["per_agentic_tool_extra"]["tomltool"] == {
        "extra key": True,
        "retry_count": 3,
    }

    rendered = render_slash_command_toml(
        canonical,
        None,
        agentic_tool_name="tomltool",
    )
    rendered_data = tomllib.loads(rendered)
    assert rendered_data["extra key"] is True
    assert rendered_data["retry_count"] == 3
    assert rendered_data["prompt"] == body


def test_slash_command_slug_converts_namespaces_to_directories():
    assert slash_command_slug("Git:Commit PR") == "git/commit-pr"
    assert slash_command_slug("plan") == "plan"
    assert slash_command_slug("COM1:Aux!") == "com1-item/aux-item"
