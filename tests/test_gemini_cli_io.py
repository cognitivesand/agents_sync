"""Unit tests for the Gemini CLI adapter helpers."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from agents_sync.canonical import empty_canonical
from agents_sync.gemini_cli_io import (
    KNOWN_GEMINI_AGENT_FIELDS,
    KNOWN_GEMINI_SKILL_FIELDS,
    extract_pair_id_from_gemini_agent_md,
    extract_pair_id_from_gemini_command_toml,
    extract_pair_id_from_gemini_rules_md,
    parse_gemini_agent_md,
    parse_gemini_command_toml,
    parse_gemini_rules_md,
    parse_gemini_skill_md,
    render_gemini_agent_md,
    render_gemini_command_toml,
    render_gemini_rules_md,
    render_gemini_skill_md,
)


PAIR_ID = "00000000-0000-4000-8000-000000000501"


def test_known_gemini_fields_match_adapter_scope():
    assert KNOWN_GEMINI_AGENT_FIELDS == frozenset({
        "pair_id",
        "name",
        "description",
        "kind",
        "tools",
        "mcpServers",
        "model",
        "temperature",
        "max_turns",
    })
    assert KNOWN_GEMINI_SKILL_FIELDS == frozenset({
        "pair_id",
        "name",
        "description",
        "license",
        "compatibility",
        "metadata",
    })


def test_parse_gemini_agent_preserves_native_frontmatter(tmp_path: Path):
    text = textwrap.dedent(
        f"""\
        ---
        pair_id: {PAIR_ID}
        name: reviewer
        description: Reviews code
        kind: local
        model: gemini-2.5-pro
        tools:
          - read_file
          - grep_search
        temperature: 0.2
        max_turns: 6
        mcpServers:
          docs:
            command: uvx
        vendor-field: keep
        ---
        Review with care.
        """
    )

    canonical = parse_gemini_agent_md(
        text,
        artifact_path=tmp_path / "reviewer.md",
    )

    assert canonical["pair_id"] == PAIR_ID
    assert canonical["name"] == "reviewer"
    assert canonical["description"] == "Reviews code"
    assert canonical["model"] == "gemini-2.5-pro"
    assert canonical["tools"] == []
    assert canonical["body"] == "Review with care."
    gemini_only = canonical["per_agentic_tool_only"]["gemini_cli"]
    assert gemini_only["kind"] == "local"
    assert gemini_only["tools"] == ["read_file", "grep_search"]
    assert gemini_only["temperature"] == 0.2
    assert gemini_only["max_turns"] == 6
    assert dict(gemini_only["mcpServers"]["docs"]) == {"command": "uvx"}
    assert canonical["per_agentic_tool_extra"]["gemini_cli"] == {
        "vendor-field": "keep"
    }
    assert extract_pair_id_from_gemini_agent_md(text) == PAIR_ID


def test_gemini_agent_uses_filename_when_name_is_missing(tmp_path: Path):
    canonical = parse_gemini_agent_md(
        "---\ndescription: x\n---\nbody\n",
        artifact_path=tmp_path / "debugger.md",
    )

    assert canonical["name"] == "debugger"
    assert canonical["body"] == "body"


def test_gemini_agent_frontmatter_name_wins_over_path(tmp_path: Path):
    canonical = parse_gemini_agent_md(
        f"---\npair_id: {PAIR_ID}\nname: reviewer\n---\nbody\n",
        artifact_path=tmp_path / "renamed.md",
    )

    assert canonical["name"] == "reviewer"


def test_render_gemini_agent_does_not_leak_antigravity_or_claude_fields():
    canonical = empty_canonical("agent")
    canonical["pair_id"] = PAIR_ID
    canonical["name"] = "reviewer"
    canonical["description"] = "x"
    canonical["body"] = "body"
    canonical["model"] = "gemini-2.5-pro"
    canonical["tools"] = ["Read", "Grep"]
    canonical["permission_mode"] = "ask"
    canonical["per_agentic_tool_only"]["gemini_cli"] = {
        "kind": "local",
        "tools": ["read_file"],
        "temperature": 0.1,
    }
    canonical["per_agentic_tool_only"]["antigravity"] = {
        "allowed-tools": ["Read"],
    }
    canonical["per_agentic_tool_only"]["claude"] = {
        "hooks": {"on-save": "fmt"},
    }

    rendered = render_gemini_agent_md(canonical)

    assert "kind: local" in rendered
    assert "read_file" in rendered
    assert "Read" not in rendered
    assert "Grep" not in rendered
    assert "temperature: 0.1" in rendered
    assert "allowed-tools:" not in rendered
    assert "permissionMode:" not in rendered
    assert "hooks:" not in rendered


def test_gemini_agent_render_drops_empty_tools_list():
    canonical = empty_canonical("agent")
    canonical["pair_id"] = PAIR_ID
    canonical["name"] = "reviewer"
    canonical["body"] = "Review with care."
    canonical["per_agentic_tool_only"]["gemini_cli"] = {
        "kind": "local",
        "tools": [],
    }

    rendered = render_gemini_agent_md(canonical)

    assert "tools:" not in rendered


def test_gemini_skill_round_trips_open_skill_fields_and_extras():
    text = textwrap.dedent(
        f"""\
        ---
        pair_id: {PAIR_ID}
        name: release-checklist
        description: Prepare a release
        license: MIT
        compatibility: gemini-cli
        metadata:
          owner: release
        vendor-key: keep
        ---
        Check the changelog.
        """
    )

    canonical = parse_gemini_skill_md(text)
    rendered = render_gemini_skill_md(canonical, text)
    parsed = parse_gemini_skill_md(rendered, canonical)

    assert parsed["pair_id"] == PAIR_ID
    assert parsed["name"] == "release-checklist"
    assert parsed["per_agentic_tool_only"]["gemini_cli"]["license"] == "MIT"
    assert parsed["per_agentic_tool_extra"]["gemini_cli"] == {"vendor-key": "keep"}


def test_gemini_skill_render_keeps_antigravity_fields_out():
    canonical = empty_canonical("skill")
    canonical["pair_id"] = PAIR_ID
    canonical["name"] = "formatter"
    canonical["description"] = "x"
    canonical["per_agentic_tool_only"]["antigravity"] = {
        "allowed-tools": ["Read", "Write"],
    }
    canonical["per_agentic_tool_only"]["gemini_cli"] = {"license": "MIT"}

    rendered = render_gemini_skill_md(canonical)

    assert "license: MIT" in rendered
    assert "allowed-tools:" not in rendered


def test_gemini_rules_wrapper_uses_global_name():
    text = "---\ndescription: Global Gemini context\n---\nPrefer concise answers.\n"

    canonical = parse_gemini_rules_md(text)
    rendered = render_gemini_rules_md(canonical)

    assert canonical["kind"] == "rules"
    assert canonical["name"] == "global"
    assert "name: global" in rendered
    assert extract_pair_id_from_gemini_rules_md(rendered) == canonical["pair_id"]


def test_gemini_command_toml_maps_prompt_and_namespaces(tmp_path: Path):
    body = "Commit {{args}}.\n!{git status}\n"
    text = "\n".join([
        f'pair_id = "{PAIR_ID}"',
        'description = "Commit helper"',
        'mode = "execute"',
        'vendor_field = "keep"',
        f"prompt = {json.dumps(body)}",
        "",
    ])
    root = tmp_path / "commands"
    path = root / "git" / "commit.toml"

    canonical = parse_gemini_command_toml(
        text,
        None,
        artifact_path=path,
        artifact_root=root,
    )
    rendered = render_gemini_command_toml(canonical)
    parsed = parse_gemini_command_toml(
        rendered,
        canonical,
        artifact_path=path,
        artifact_root=root,
    )

    assert canonical["name"] == "git:commit"
    assert parsed["body"] == body
    assert parsed["per_agentic_tool_only"]["gemini_cli"] == {"mode": "execute"}
    assert parsed["per_agentic_tool_extra"]["gemini_cli"] == {
        "vendor_field": "keep"
    }
    assert extract_pair_id_from_gemini_command_toml(rendered) == PAIR_ID
