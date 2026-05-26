"""Unit tests for opencode_io: parse / render / extract_pair_id."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agents_sync.canonical import empty_canonical
from agents_sync.opencode_io import (
    KNOWN_OPENCODE_AGENT_FIELDS,
    KNOWN_OPENCODE_SKILL_FIELDS,
    extract_pair_id_from_md,
    opencode_skill_slug,
    parse_opencode_agent_md,
    parse_opencode_skill_md,
    render_opencode_agent_md,
    render_opencode_skill_md,
)


def test_known_opencode_fields_match_v0_4_1_plan():
    assert KNOWN_OPENCODE_AGENT_FIELDS == frozenset({
        "pair_id",
        "description",
        "mode",
        "model",
        "temperature",
        "top_p",
        "steps",
        "maxSteps",
        "permission",
        "tools",
        "color",
        "hidden",
        "disable",
        "options",
    })
    assert KNOWN_OPENCODE_SKILL_FIELDS == frozenset({
        "pair_id",
        "name",
        "description",
        "license",
        "compatibility",
        "metadata",
    })


def test_parse_opencode_agent_uses_filename_and_preserves_known_fields(tmp_path: Path):
    text = textwrap.dedent(
        """\
        ---
        pair_id: 00000000-0000-4000-8000-000000000001
        description: Reviews code
        mode: subagent
        model: anthropic/claude-sonnet-4-5
        temperature: 0.2
        maxSteps: 8
        permission:
          edit: deny
        vendor-field: keep
        ---
        Review carefully.
        """
    )
    path = tmp_path / "reviewer.md"

    canonical = parse_opencode_agent_md(text, artifact_path=path)

    assert canonical["pair_id"] == "00000000-0000-4000-8000-000000000001"
    assert canonical["name"] == "reviewer"
    assert canonical["description"] == "Reviews code"
    assert canonical["model"] == "claude-sonnet-4-5"
    assert canonical["body"] == "Review carefully."
    opencode_only = canonical["per_agentic_tool_only"]["opencode"]
    assert opencode_only["mode"] == "subagent"
    assert opencode_only["model_provider"] == "anthropic"
    assert opencode_only["steps"] == 8
    assert dict(opencode_only["permission"]) == {"edit": "deny"}
    assert canonical["per_agentic_tool_extra"]["opencode"] == {"vendor-field": "keep"}


def test_opencode_agent_render_reattaches_provider_and_does_not_leak_foreign_fields():
    canonical = empty_canonical("agent")
    canonical["pair_id"] = "00000000-0000-4000-8000-000000000002"
    canonical["name"] = "reviewer"
    canonical["description"] = "Reviews code"
    canonical["body"] = "body"
    canonical["model"] = "claude-sonnet-4-5"
    canonical["tools"] = ["Read"]
    canonical["permission_mode"] = "acceptEdits"
    canonical["per_agentic_tool_only"]["claude"] = {"hooks": {"on-save": "fmt"}}
    canonical["per_agentic_tool_only"]["codex"] = {"sandbox_mode": "read-only"}
    canonical["per_agentic_tool_only"]["opencode"] = {
        "model_provider": "anthropic",
        "mode": "subagent",
        "permission": {"edit": "deny"},
    }

    rendered = render_opencode_agent_md(canonical)

    assert "model: anthropic/claude-sonnet-4-5" in rendered
    assert "mode: subagent" in rendered
    assert "permission:" in rendered
    for forbidden in (
        "name:",
        "tools:",
        "permissionMode:",
        "hooks:",
        "sandbox_mode:",
        "developer_instructions:",
    ):
        assert forbidden not in rendered


def test_opencode_agent_render_then_parse_is_fixed_point(tmp_path: Path):
    canonical = empty_canonical("agent")
    canonical["pair_id"] = "00000000-0000-4000-8000-000000000003"
    canonical["name"] = "debugger"
    canonical["description"] = "Debug UI flows"
    canonical["body"] = "body"
    canonical["model"] = "gpt-5.4"
    canonical["per_agentic_tool_only"]["opencode"] = {
        "model_provider": "openai",
        "mode": "subagent",
        "color": "blue",
    }

    rendered = render_opencode_agent_md(canonical)
    parsed = parse_opencode_agent_md(
        rendered,
        prior_canonical=canonical,
        artifact_path=tmp_path / "debugger.md",
    )

    assert parsed["pair_id"] == canonical["pair_id"]
    assert parsed["name"] == "debugger"
    assert parsed["model"] == "gpt-5.4"
    assert parsed["per_agentic_tool_only"]["opencode"]["model_provider"] == "openai"
    assert parsed["per_agentic_tool_only"]["opencode"]["mode"] == "subagent"


def test_opencode_agent_parse_normalises_deprecated_tools_map():
    text = "---\ndescription: x\ntools:\n  write: false\n  read: true\n---\nbody\n"
    canonical = parse_opencode_agent_md(text, artifact_path=Path("reviewer.md"))
    assert canonical["per_agentic_tool_only"]["opencode"]["permission"] == {
        "write": "deny",
        "read": "allow",
    }
    rendered = render_opencode_agent_md(canonical)
    assert "tools:" not in rendered
    assert "permission:" in rendered


def test_opencode_agent_rejects_non_mapping_frontmatter():
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        parse_opencode_agent_md("---\n- bad\n---\nbody", artifact_path=Path("x.md"))


def test_opencode_skill_preserves_open_spec_fields_and_extras():
    text = textwrap.dedent(
        """\
        ---
        pair_id: 00000000-0000-4000-8000-000000000004
        name: formatter
        description: Format things
        license: MIT
        compatibility: opencode
        metadata:
          owner: docs
        vendor-field: keep
        ---
        Skill body.
        """
    )
    canonical = parse_opencode_skill_md(text)
    assert canonical["name"] == "formatter"
    assert canonical["per_agentic_tool_only"]["opencode"]["license"] == "MIT"
    assert canonical["per_agentic_tool_extra"]["opencode"] == {"vendor-field": "keep"}

    rendered = render_opencode_skill_md(canonical)
    assert "license: MIT" in rendered
    assert "compatibility: opencode" in rendered
    assert "vendor-field: keep" in rendered


def test_opencode_skill_does_not_stash_foreign_fields_as_extras():
    text = textwrap.dedent(
        """\
        ---
        pair_id: 00000000-0000-4000-8000-000000000007
        name: formatter
        model: gpt-5.4
        hooks:
          on-save: fmt
        vendor-field: keep
        ---
        Skill body.
        """
    )

    canonical = parse_opencode_skill_md(text)

    assert canonical["per_agentic_tool_extra"]["opencode"] == {
        "vendor-field": "keep"
    }


def test_opencode_skill_slug_normalises_underscores_for_render():
    canonical = empty_canonical("skill")
    canonical["pair_id"] = "00000000-0000-4000-8000-000000000005"
    canonical["name"] = "my_skill"
    canonical["description"] = "x"
    rendered = render_opencode_skill_md(canonical)
    assert "name: my-skill" in rendered
    assert opencode_skill_slug("My_Skill") == "my-skill"


def test_extract_pair_id_from_md():
    text = "---\npair_id: 00000000-0000-4000-8000-000000000006\n---\nbody"
    assert extract_pair_id_from_md(text) == "00000000-0000-4000-8000-000000000006"


def test_parse_opencode_agent_md_raises_when_no_name_source():
    """Audit slice 07 · CQ-01 (Liskov fix): when artifact_path is omitted and
    neither prior canonical nor frontmatter carries a name, the parser must
    raise instead of silently minting name=''."""
    text = "---\ndescription: nameless\n---\nbody"
    with pytest.raises(ValueError, match="needs either artifact_path"):
        parse_opencode_agent_md(text)


def test_parse_opencode_agent_md_accepts_frontmatter_name_without_artifact_path():
    """Fallback path: prior_canonical None, no artifact_path, but frontmatter
    explicitly carries name."""
    text = "---\nname: explicit\ndescription: x\n---\nbody"
    canonical = parse_opencode_agent_md(text)
    assert canonical["name"] == "explicit"


def test_parse_opencode_agent_md_accepts_prior_canonical_name():
    """Fallback path: artifact_path omitted but prior canonical knows the name."""
    text = "---\ndescription: updated\n---\nbody"
    prior = empty_canonical("agent")
    prior["name"] = "from-prior"
    canonical = parse_opencode_agent_md(text, prior)
    assert canonical["name"] == "from-prior"
