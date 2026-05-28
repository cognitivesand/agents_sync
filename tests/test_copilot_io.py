from __future__ import annotations

import textwrap
from pathlib import Path

from agents_sync.copilot_io import (
    copilot_skill_slug,
    extract_pair_id_from_copilot_agent_md,
    parse_copilot_agent_md,
    parse_copilot_instruction_md,
    parse_copilot_prompt_md,
    parse_copilot_skill_md,
    render_copilot_agent_md,
    render_copilot_instruction_md,
    render_copilot_prompt_md,
    render_copilot_skill_md,
)


PAIR_ID = "11111111-2222-4333-8444-555555555555"


def test_copilot_agent_round_trips_known_and_unknown_frontmatter(tmp_path: Path):
    path = tmp_path / "reviewer.agent.md"
    text = textwrap.dedent(
        f"""\
        ---
        pair_id: {PAIR_ID}
        name: reviewer
        description: Reviews pull requests
        model: gpt-5
        tools:
          - code_search
        argument-hint: "[diff]"
        mcp-servers:
          - github
        x-preview: keep-me
        ---
        Review the change.
        """
    )

    canonical = parse_copilot_agent_md(text, None, artifact_path=path)

    assert canonical["pair_id"] == PAIR_ID
    assert canonical["name"] == "reviewer"
    assert canonical["tools"] == ["code_search"]
    assert canonical["per_agentic_tool_only"]["copilot"]["argument-hint"] == "[diff]"
    assert canonical["per_agentic_tool_only"]["copilot"]["mcp-servers"] == ["github"]
    assert canonical["per_agentic_tool_extra"]["copilot"] == {"x-preview": "keep-me"}

    rendered = render_copilot_agent_md(canonical)
    assert extract_pair_id_from_copilot_agent_md(rendered) == PAIR_ID
    assert "x-preview: keep-me" in rendered
    assert "mcp-servers:" in rendered


def test_copilot_agent_render_drops_empty_tools_list():
    canonical = {
        "pair_id": PAIR_ID,
        "name": "reviewer",
        "body": "Review the change.",
        "tools": [],
        "per_agentic_tool_only": {"copilot": {}},
        "per_agentic_tool_extra": {"copilot": {}},
    }

    rendered = render_copilot_agent_md(canonical)

    assert "tools:" not in rendered


def test_copilot_legacy_chatmode_uses_clean_agent_name(tmp_path: Path):
    path = tmp_path / "planner.chatmode.md"

    canonical = parse_copilot_agent_md("Plan carefully.\n", None, artifact_path=path)

    assert canonical["name"] == "planner"


def test_copilot_agent_frontmatter_name_wins_over_path(tmp_path: Path):
    path = tmp_path / "renamed.agent.md"
    text = f"---\npair_id: {PAIR_ID}\nname: reviewer\n---\nReview.\n"

    canonical = parse_copilot_agent_md(text, None, artifact_path=path)

    assert canonical["name"] == "reviewer"


def test_copilot_skill_round_trips_open_skill_shape(tmp_path: Path):
    skill_dir = tmp_path / "release-checklist"
    text = textwrap.dedent(
        f"""\
        ---
        pair_id: {PAIR_ID}
        name: release-checklist
        description: Prepare releases
        argument-hint: "[version]"
        context:
          - changelog
        ---
        Check every release gate.
        """
    )

    canonical = parse_copilot_skill_md(text, None, artifact_path=skill_dir)
    rendered = render_copilot_skill_md(canonical)

    assert canonical["name"] == "release-checklist"
    assert copilot_skill_slug("Release Checklist!") == "release-checklist"
    assert "argument-hint: '[version]'" in rendered or 'argument-hint: "[version]"' in rendered
    assert "context:" in rendered


def test_copilot_instruction_maps_to_rules_and_preserves_extra(tmp_path: Path):
    path = tmp_path / "typescript.instructions.md"
    text = textwrap.dedent(
        f"""\
        ---
        pair_id: {PAIR_ID}
        description: TS rules
        applyTo: "**/*.ts"
        mode: ask
        custom-field: kept
        ---
        Prefer explicit return types.
        """
    )

    canonical = parse_copilot_instruction_md(text, None, artifact_path=path)
    rendered = render_copilot_instruction_md(canonical)

    assert canonical["kind"] == "rules"
    assert canonical["name"] == "typescript"
    assert canonical["applyTo"] == "**/*.ts"
    assert canonical["mode"] == "ask"
    assert canonical["per_agentic_tool_extra"]["copilot"] == {"custom-field": "kept"}
    assert "custom-field: kept" in rendered


def test_copilot_instruction_path_identity_wins_over_rendered_name(tmp_path: Path):
    path = tmp_path / "typescript.instructions.md"
    text = textwrap.dedent(
        f"""\
        ---
        pair_id: {PAIR_ID}
        name: stale-name
        private: "false"
        ---
        Prefer explicit return types.
        """
    )

    canonical = parse_copilot_instruction_md(text, None, artifact_path=path)

    assert canonical["name"] == "typescript"
    assert canonical["private"] is False


def test_copilot_prompt_maps_namespace_and_tools(tmp_path: Path):
    root = tmp_path / "prompts"
    path = root / "git" / "commit.prompt.md"
    text = textwrap.dedent(
        f"""\
        ---
        pair_id: {PAIR_ID}
        description: Commit message
        argument-hint: "[scope]"
        agent: planner
        tools:
          - terminal
        ---
        Write a commit message.
        """
    )

    canonical = parse_copilot_prompt_md(
        text,
        None,
        artifact_path=path,
        artifact_root=root,
    )
    rendered = render_copilot_prompt_md(canonical)

    assert canonical["kind"] == "slash_command"
    assert canonical["name"] == "git:commit"
    assert canonical["argument_hint"] == "[scope]"
    assert canonical["allowed_tools"] == ["terminal"]
    assert canonical["per_agentic_tool_only"]["copilot"] == {"agent": "planner"}
    assert "name: git:commit" in rendered
    assert "tools:" in rendered


def test_copilot_prompt_path_identity_wins_over_rendered_name(tmp_path: Path):
    root = tmp_path / "prompts"
    path = root / "git" / "amend.prompt.md"
    text = textwrap.dedent(
        f"""\
        ---
        pair_id: {PAIR_ID}
        name: git:commit
        tools:
          - terminal
        ---
        Update the last commit message.
        """
    )

    canonical = parse_copilot_prompt_md(
        text,
        None,
        artifact_path=path,
        artifact_root=root,
    )
    rendered = render_copilot_prompt_md(canonical)

    assert canonical["name"] == "git:amend"
    assert canonical["allowed_tools"] == ["terminal"]
    assert "name: git:amend" in rendered
