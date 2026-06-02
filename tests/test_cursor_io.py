"""Unit tests for Cursor adapter IO helpers."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from agents_sync.cursor_io import (
    extract_pair_id_from_cursor_agent_md,
    extract_pair_id_from_cursor_command_md,
    extract_pair_id_from_cursor_mcp_server_json,
    extract_pair_id_from_cursor_rule_mdc,
    extract_pair_id_from_cursor_skill_md,
    parse_cursor_agent_md,
    parse_cursor_command_md,
    parse_cursor_mcp_server_json,
    parse_cursor_rule_mdc,
    parse_cursor_skill_md,
    render_cursor_agent_md,
    render_cursor_command_md,
    render_cursor_mcp_server_json,
    render_cursor_rule_mdc,
    render_cursor_skill_md,
)

PAIR_ID = "11111111-2222-4333-8444-555555555555"


def test_cursor_agent_round_trips_frontmatter_body_and_unknown_keys(tmp_path: Path):
    source = tmp_path / "agents" / "reviewer.md"
    source.parent.mkdir()
    text = textwrap.dedent(
        f"""\
        ---
        pair_id: {PAIR_ID}
        name: ignored-name
        description: Reviews diffs
        model: claude-4-sonnet
        tools:
          - Read
          - Grep
        cursor_knob: keep-me
        ---
        Review the current diff.
        """
    )

    canonical = parse_cursor_agent_md(text, None, artifact_path=source)

    assert canonical["kind"] == "agent"
    assert canonical["name"] == "ignored-name"
    assert canonical["description"] == "Reviews diffs"
    assert canonical["model"] == "claude-4-sonnet"
    assert canonical["tools"] == ["Read", "Grep"]
    assert canonical["body"] == "Review the current diff."
    assert canonical["per_agentic_tool_extra"]["cursor"] == {
        "cursor_knob": "keep-me",
    }
    assert extract_pair_id_from_cursor_agent_md(text) == PAIR_ID

    rendered = render_cursor_agent_md(canonical, text)
    assert "cursor_knob: keep-me" in rendered
    assert extract_pair_id_from_cursor_agent_md(rendered) == PAIR_ID


def test_cursor_agent_uses_filename_when_name_is_missing(tmp_path: Path):
    source = tmp_path / "agents" / "reviewer.md"
    source.parent.mkdir()

    canonical = parse_cursor_agent_md(
        f"---\npair_id: {PAIR_ID}\n---\nReview.",
        None,
        artifact_path=source,
    )

    assert canonical["name"] == "reviewer"


def test_cursor_agent_render_drops_empty_tools_list():
    canonical = {
        "pair_id": PAIR_ID,
        "name": "reviewer",
        "body": "Review the current diff.",
        "tools": [],
    }

    rendered = render_cursor_agent_md(canonical)

    assert "tools:" not in rendered


def test_cursor_skill_round_trips_open_skill_fields(tmp_path: Path):
    source = tmp_path / "skills" / "release-checklist"
    source.mkdir(parents=True)
    text = textwrap.dedent(
        f"""\
        ---
        pair_id: {PAIR_ID}
        name: release-checklist
        description: Release helper
        license: MIT
        metadata:
          owner: platform
        cursor_extra: preserved
        ---
        Run the checklist.
        """
    )

    canonical = parse_cursor_skill_md(text, None, artifact_path=source)

    assert canonical["kind"] == "skill"
    assert canonical["name"] == "release-checklist"
    assert canonical["per_agentic_tool_only"]["cursor"]["license"] == "MIT"
    assert canonical["per_agentic_tool_only"]["cursor"]["metadata"] == {
        "owner": "platform",
    }
    assert canonical["per_agentic_tool_extra"]["cursor"] == {
        "cursor_extra": "preserved",
    }
    assert extract_pair_id_from_cursor_skill_md(text) == PAIR_ID

    rendered = render_cursor_skill_md(canonical, text)
    assert "license: MIT" in rendered
    assert "cursor_extra: preserved" in rendered


def test_cursor_rule_mdc_uses_rules_canonical_fields(tmp_path: Path):
    rule_path = tmp_path / "rules" / "typescript.mdc"
    rule_path.parent.mkdir()
    text = textwrap.dedent(
        f"""\
        ---
        pair_id: {PAIR_ID}
        description: TypeScript conventions
        globs:
          - "**/*.ts"
        alwaysApply: true
        cursor_meta: yes
        ---
        Prefer strict types.
        """
    )

    canonical = parse_cursor_rule_mdc(text, None, artifact_path=rule_path)

    assert canonical["kind"] == "rules"
    assert canonical["name"] == "typescript"
    assert canonical["globs"] == ["**/*.ts"]
    assert canonical["alwaysApply"] is True
    assert canonical["per_agentic_tool_extra"]["cursor"] == {"cursor_meta": "yes"}
    assert extract_pair_id_from_cursor_rule_mdc(text) == PAIR_ID

    rendered = render_cursor_rule_mdc(canonical, text)
    assert "alwaysApply: true" in rendered
    assert extract_pair_id_from_cursor_rule_mdc(rendered) == PAIR_ID


def test_cursor_command_uses_html_identity_comment_and_preserves_body(
    tmp_path: Path,
):
    root = tmp_path / "commands"
    command_path = root / "git" / "commit.md"
    command_path.parent.mkdir(parents=True)
    body = "---\nThis is command text, not YAML frontmatter.\n---\nUse $ARGUMENTS.\n"
    text = f"<!-- agents_sync:pair_id={PAIR_ID} -->\n{body}"

    canonical = parse_cursor_command_md(
        text,
        None,
        artifact_path=command_path,
        artifact_root=root,
    )

    assert canonical["kind"] == "slash_command"
    assert canonical["name"] == "git:commit"
    assert canonical["body"] == body
    assert extract_pair_id_from_cursor_command_md(text) == PAIR_ID

    rendered = render_cursor_command_md(canonical, None)
    assert rendered.startswith(f"<!-- agents_sync:pair_id={PAIR_ID} -->\n")
    assert "\n---\nThis is command text" in rendered
    assert "pair_id:" not in canonical["body"]


def test_cursor_command_render_uses_prior_text_newline_style():
    canonical = {
        "pair_id": PAIR_ID,
        "kind": "slash_command",
        "name": "deploy",
        "body": "Run $ARGUMENTS\r\n",
    }
    prior = f"<!-- agents_sync:pair_id={PAIR_ID} -->\r\nold\r\n"

    rendered = render_cursor_command_md(canonical, prior)

    assert rendered.startswith(f"<!-- agents_sync:pair_id={PAIR_ID} -->\r\n")


def test_cursor_mcp_defaults_bare_url_slots_to_streamable_http():
    slot = json.dumps({
        "pair_id": PAIR_ID,
        "name": "docs",
        "url": "https://docs.example.com/mcp",
        "x-cursor": "keep",
    })

    canonical = parse_cursor_mcp_server_json(slot, None)

    assert canonical["kind"] == "mcp_server"
    assert canonical["name"] == "docs"
    assert canonical["transport"] == "streamable-http"
    assert canonical["url"] == "https://docs.example.com/mcp"
    assert canonical["per_agentic_tool_extra"]["cursor"] == {"x-cursor": "keep"}
    assert extract_pair_id_from_cursor_mcp_server_json(slot) == PAIR_ID

    rendered = render_cursor_mcp_server_json(canonical, None)
    rendered_obj = json.loads(rendered)
    assert rendered_obj["pair_id"] == PAIR_ID
    assert rendered_obj["type"] == "streamable-http"
    assert rendered_obj["url"] == "https://docs.example.com/mcp"
    assert "name" not in rendered_obj
