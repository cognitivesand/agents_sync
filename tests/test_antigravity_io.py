"""Unit tests for antigravity_io: parse / render / extract_pair_id (NFR-06)."""
from __future__ import annotations

import textwrap

import pytest

from agents_sync.antigravity_io import (
    KNOWN_ANTIGRAVITY_FIELDS,
    extract_pair_id_from_md,
    parse_antigravity_skill_md,
    render_antigravity_skill_md,
)
from agents_sync.canonical import empty_canonical


# ---------- parse ----------

def test_parse_required_fields_only():
    text = textwrap.dedent(
        """\
        ---
        name: formatter
        description: format something
        ---
        body content
        """
    )
    canonical = parse_antigravity_skill_md(text)
    assert canonical["name"] == "formatter"
    assert canonical["description"] == "format something"
    assert canonical["body"] == "body content"
    # No optional antigravity-known fields ⇒ empty dict.
    assert canonical["per_agentic_tool_only"]["antigravity"] == {}
    # No unknown fields ⇒ empty extra dict.
    assert canonical["per_agentic_tool_extra"]["antigravity"] == {}
    # No pair_id in frontmatter ⇒ one minted.
    assert canonical["pair_id"]


def test_parse_optional_antigravity_known_fields_route_to_per_only_antigravity():
    text = textwrap.dedent(
        """\
        ---
        name: licensed-skill
        description: with license metadata
        license: MIT
        compatibility: ">=1.0"
        metadata:
          author: jane
        allowed-tools:
          - Read
          - Grep
        ---
        body
        """
    )
    canonical = parse_antigravity_skill_md(text)
    antigravity_only = canonical["per_agentic_tool_only"]["antigravity"]
    assert antigravity_only["license"] == "MIT"
    assert antigravity_only["compatibility"] == ">=1.0"
    assert dict(antigravity_only["metadata"]) == {"author": "jane"}
    assert list(antigravity_only["allowed-tools"]) == ["Read", "Grep"]
    # None of the Antigravity-known optional fields leak into the extras bag.
    assert canonical["per_agentic_tool_extra"]["antigravity"] == {}


def test_parse_unknown_fields_route_to_per_extra_antigravity():
    text = textwrap.dedent(
        """\
        ---
        name: with-extras
        description: bag
        weird-field: something
        custom-vendor-key: 42
        ---
        body
        """
    )
    canonical = parse_antigravity_skill_md(text)
    extras = canonical["per_agentic_tool_extra"]["antigravity"]
    assert extras == {"weird-field": "something", "custom-vendor-key": 42}


def test_parse_preserves_existing_pair_id():
    text = textwrap.dedent(
        """\
        ---
        pair_id: 00000000-0000-4000-8000-000000000001
        name: foo
        description: bar
        ---
        body
        """
    )
    canonical = parse_antigravity_skill_md(text)
    assert canonical["pair_id"] == "00000000-0000-4000-8000-000000000001"


def test_parse_tolerates_utf8_bom_prefix():
    text = "﻿---\nname: bom-skill\ndescription: x\n---\nbody\n"
    canonical = parse_antigravity_skill_md(text)
    assert canonical["name"] == "bom-skill"
    assert canonical["body"] == "body"


def test_parse_rejects_non_mapping_frontmatter():
    text = "---\n- just\n- a\n- list\n---\nbody"
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        parse_antigravity_skill_md(text)


def test_parse_with_no_frontmatter_keeps_body():
    text = "no frontmatter here, just markdown"
    canonical = parse_antigravity_skill_md(text)
    assert canonical["body"] == "no frontmatter here, just markdown"
    assert canonical["name"] == ""


def test_parse_with_prior_canonical_preserves_other_tools_state():
    prior = empty_canonical("skill")
    prior["pair_id"] = "00000000-0000-4000-8000-000000000002"
    prior["per_agentic_tool_only"] = {"claude": {"hooks": {"on-save": "fmt"}}}
    prior["per_agentic_tool_extra"] = {"claude": {"custom-claude-key": "kept"}}

    text = "---\nname: shared\ndescription: x\n---\nbody"
    canonical = parse_antigravity_skill_md(text, prior_canonical=prior)

    # Antigravity bag was written.
    assert canonical["per_agentic_tool_only"]["antigravity"] == {}
    # Claude state is intact.
    assert canonical["per_agentic_tool_only"]["claude"] == {"hooks": {"on-save": "fmt"}}
    assert canonical["per_agentic_tool_extra"]["claude"] == {"custom-claude-key": "kept"}
    assert canonical["pair_id"] == "00000000-0000-4000-8000-000000000002"


# ---------- render ----------

def test_render_emits_required_and_optional_known_fields():
    c = empty_canonical("skill")
    c["pair_id"] = "00000000-0000-4000-8000-000000000003"
    c["name"] = "my-skill"
    c["description"] = "demo"
    c["body"] = "hello body"
    c["per_agentic_tool_only"]["antigravity"] = {
        "license": "Apache-2.0",
        "allowed-tools": ["Read", "Write"],
    }
    rendered = render_antigravity_skill_md(c)
    assert "name: my-skill" in rendered
    assert "description: demo" in rendered
    assert "pair_id: 00000000-0000-4000-8000-000000000003" in rendered
    assert "license: Apache-2.0" in rendered
    assert "allowed-tools:" in rendered
    assert rendered.endswith("hello body\n")


def test_render_does_not_emit_claude_only_fields():
    """Claude-specific keys must stay out of the Antigravity SKILL.md."""
    c = empty_canonical("skill")
    c["pair_id"] = "00000000-0000-4000-8000-000000000004"
    c["name"] = "isolated"
    c["description"] = "x"
    c["body"] = "body"
    # Stuff that lives on the Claude side only:
    c["model"] = "sonnet"
    c["effort"] = "high"
    c["tools"] = ["Read", "Grep"]
    c["disallowed_tools"] = ["Write"]
    c["permission_mode"] = "ask"
    c["per_agentic_tool_only"]["claude"] = {
        "hooks": {"on-save": "fmt"},
        "mcp_servers": {"weather": {"url": "http://example"}},
    }
    c["per_agentic_tool_extra"]["claude"] = {"custom-claude-key": "kept-for-claude"}

    rendered = render_antigravity_skill_md(c)

    # None of the Claude-side keys should appear in Antigravity output.
    for forbidden in (
        "model:",
        "effort:",
        "tools:",
        "disallowedTools:",
        "permissionMode:",
        "hooks:",
        "mcpServers:",
        "custom-claude-key:",
    ):
        assert forbidden not in rendered, f"unexpected key in Antigravity render: {forbidden}"


def test_render_emits_antigravity_extras():
    c = empty_canonical("skill")
    c["pair_id"] = "00000000-0000-4000-8000-000000000005"
    c["name"] = "extras-skill"
    c["description"] = "x"
    c["body"] = "body"
    c["per_agentic_tool_extra"]["antigravity"] = {"vendor-key": "vendor-value"}
    rendered = render_antigravity_skill_md(c)
    assert "vendor-key: vendor-value" in rendered


def test_render_omits_empty_body():
    c = empty_canonical("skill")
    c["pair_id"] = "00000000-0000-4000-8000-000000000006"
    c["name"] = "empty-body"
    c["description"] = "x"
    c["body"] = ""
    rendered = render_antigravity_skill_md(c)
    assert rendered.endswith("---\n")


# ---------- round-trip identity ----------

def test_render_then_parse_is_a_fixed_point_for_basic_skill():
    c1 = empty_canonical("skill")
    c1["pair_id"] = "00000000-0000-4000-8000-000000000007"
    c1["name"] = "roundtrip"
    c1["description"] = "fixed-point check"
    c1["body"] = "the body"
    c1["per_agentic_tool_only"]["antigravity"] = {"license": "MIT"}
    c1["per_agentic_tool_extra"]["antigravity"] = {"vendor-x": "y"}

    rendered = render_antigravity_skill_md(c1)
    c2 = parse_antigravity_skill_md(rendered, prior_canonical=c1)

    assert c2["pair_id"] == c1["pair_id"]
    assert c2["name"] == c1["name"]
    assert c2["description"] == c1["description"]
    assert c2["body"] == c1["body"]
    assert c2["per_agentic_tool_only"]["antigravity"]["license"] == "MIT"
    assert c2["per_agentic_tool_extra"]["antigravity"]["vendor-x"] == "y"


def test_render_is_byte_deterministic():
    c = empty_canonical("skill")
    c["pair_id"] = "00000000-0000-4000-8000-000000000008"
    c["name"] = "deterministic"
    c["description"] = "x"
    c["body"] = "body"
    c["per_agentic_tool_only"]["antigravity"] = {"license": "MIT"}
    assert render_antigravity_skill_md(c) == render_antigravity_skill_md(c)


def test_parse_render_parse_preserves_unknown_passthrough():
    """A user-authored field unknown to v0.4 should survive parse->render->parse."""
    text = textwrap.dedent(
        """\
        ---
        pair_id: 00000000-0000-4000-8000-000000000009
        name: passthrough
        description: x
        unknown-vendor-prop: keep-me
        ---
        body
        """
    )
    c1 = parse_antigravity_skill_md(text)
    rendered = render_antigravity_skill_md(c1, prior_text=text)
    c2 = parse_antigravity_skill_md(rendered, prior_canonical=c1)
    assert c2["per_agentic_tool_extra"]["antigravity"]["unknown-vendor-prop"] == "keep-me"


# ---------- extract_pair_id ----------

def test_extract_pair_id_reuses_claude_helper():
    text = "---\npair_id: 00000000-0000-4000-8000-00000000000a\nname: x\ndescription: y\n---\nbody"
    assert extract_pair_id_from_md(text) == "00000000-0000-4000-8000-00000000000a"


def test_extract_pair_id_returns_none_when_absent():
    text = "---\nname: x\ndescription: y\n---\nbody"
    assert extract_pair_id_from_md(text) is None


# ---------- field allow-list sanity ----------

def test_known_antigravity_fields_match_plan():
    """The plan §2 deliverable enumerates the seven known fields."""
    assert KNOWN_ANTIGRAVITY_FIELDS == frozenset({
        "pair_id",
        "name",
        "description",
        "license",
        "compatibility",
        "metadata",
        "allowed-tools",
    })
