"""Round-trip property tests for the Claude side parse/render pair (NFR-06)."""
from __future__ import annotations

import textwrap

from agents_sync.claude_io import parse_claude_md, render_claude_md


def test_parse_then_render_then_parse_is_a_fixed_point_for_basic_agent():
    text = textwrap.dedent(
        """\
        ---
        name: my-agent
        description: a test agent
        tools:
          - Read
          - Grep
        model: sonnet
        ---
        This is the body.
        """
    )

    canonical1 = parse_claude_md(text, kind="agent")
    rendered = render_claude_md(canonical1, prior_text=text)
    canonical2 = parse_claude_md(rendered, prior_canonical=canonical1, kind="agent")

    assert canonical1["pair_id"] == canonical2["pair_id"]
    assert canonical1["name"] == canonical2["name"]
    assert canonical1["description"] == canonical2["description"]
    assert canonical1["tools"] == canonical2["tools"]
    assert canonical1["model"] == canonical2["model"]
    assert canonical1["body"] == canonical2["body"]


def test_parse_assigns_a_pair_id_when_missing():
    text = "---\nname: foo\ndescription: bar\n---\nbody"
    canonical = parse_claude_md(text, kind="agent")
    assert canonical["pair_id"]
    assert canonical["name"] == "foo"


def test_parse_preserves_existing_pair_id():
    text = "---\npair_id: 11111111-2222-3333-4444-555555555555\nname: foo\ndescription: bar\n---\nbody"
    canonical = parse_claude_md(text, kind="agent")
    assert canonical["pair_id"] == "11111111-2222-3333-4444-555555555555"


def test_parse_passthrough_routes_unmapped_fields_into_per_agentic_tool_extra():
    text = "---\nname: foo\ndescription: bar\nweird_field: something\n---\nbody"
    canonical = parse_claude_md(text, kind="agent")
    assert canonical["per_agentic_tool_extra"]["claude"] == {"weird_field": "something"}


def test_render_preserves_pair_id_after_injection():
    """Adoption flow: input has no pair_id; render then re-parse round-trips it."""
    text = "---\nname: foo\ndescription: bar\n---\nthe body\n"
    canonical = parse_claude_md(text, kind="agent")
    rendered = render_claude_md(canonical, prior_text=text)
    parsed_back = parse_claude_md(rendered, prior_canonical=canonical, kind="agent")
    assert parsed_back["pair_id"] == canonical["pair_id"]
    assert parsed_back["body"] == "the body"


def test_render_with_no_prior_text_produces_valid_frontmatter():
    text = "---\nname: foo\ndescription: bar\n---\nbody"
    canonical = parse_claude_md(text, kind="agent")
    rendered = render_claude_md(canonical, prior_text=None)
    assert rendered.startswith("---\n")
    assert "name: foo" in rendered
    assert f"pair_id: {canonical['pair_id']}" in rendered


def test_parse_tolerates_utf8_bom_prefixed_frontmatter():
    text = "\ufeff---\nname: demo\ndescription: from-bom\n---\nbody\n"
    canonical = parse_claude_md(text, kind="agent")
    assert canonical["name"] == "demo"
    assert canonical["description"] == "from-bom"
    assert canonical["body"] == "body"
