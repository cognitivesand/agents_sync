"""Round-trip property tests for the Codex side parse/render pair (NFR-06)."""
from __future__ import annotations

from agents_sync.canonical import empty_canonical
from agents_sync.codex_io import (
    parse_codex_agent_toml,
    parse_codex_skill_md,
    render_codex_agent_toml,
    render_codex_skill_md,
)


def _agent_canonical() -> dict:
    c = empty_canonical("agent")
    c["pair_id"] = "abc-123"
    c["name"] = "my-agent"
    c["description"] = "a test agent"
    c["body"] = "the body"
    c["model"] = "gpt-4"
    c["effort"] = "high"
    c["per_agentic_tool_only"]["codex"] = {
        "sandbox_mode": "read-only",
        "nickname_candidates": ["Atlas", "Delta"],
        "mcp_servers": {"docs": {"url": "https://developers.openai.com/mcp"}},
        "skills": {"config": [{"path": "/tmp/SKILL.md", "enabled": False}]},
    }
    return c


def test_codex_agent_render_then_parse_is_a_fixed_point():
    c1 = _agent_canonical()
    rendered = render_codex_agent_toml(c1)
    c2 = parse_codex_agent_toml(rendered, prior_canonical=c1)

    assert c2["pair_id"] == c1["pair_id"]
    assert c2["name"] == c1["name"]
    assert c2["description"] == c1["description"]
    assert c2["body"] == c1["body"]
    assert c2["model"] == c1["model"]
    assert c2["effort"] == c1["effort"]
    assert c2["per_agentic_tool_only"]["codex"]["sandbox_mode"] == "read-only"
    assert c2["per_agentic_tool_only"]["codex"]["nickname_candidates"] == [
        "Atlas",
        "Delta",
    ]
    assert c2["per_agentic_tool_only"]["codex"]["mcp_servers"]["docs"]["url"] == (
        "https://developers.openai.com/mcp"
    )
    assert (
        c2["per_agentic_tool_only"]["codex"]["skills"]["config"][0]["enabled"]
        is False
    )


def test_codex_agent_render_is_byte_deterministic():
    c = _agent_canonical()
    assert render_codex_agent_toml(c) == render_codex_agent_toml(c)


def test_codex_agent_render_emits_current_nested_config_fields():
    rendered = render_codex_agent_toml(_agent_canonical())
    assert 'nickname_candidates = ["Atlas", "Delta"]' in rendered
    assert "[mcp_servers.docs]" in rendered
    assert 'url = "https://developers.openai.com/mcp"' in rendered
    assert "[[skills.config]]" in rendered
    assert 'path = "/tmp/SKILL.md"' in rendered
    assert "enabled = false" in rendered


def test_codex_agent_parse_drops_removed_codex_only_fields():
    prior = _agent_canonical()
    text = (
        'pair_id = "abc-123"\n'
        'name = "codexer"\n'
        'developer_instructions = "body"\n'
    )

    parsed = parse_codex_agent_toml(text, prior)

    assert parsed["per_agentic_tool_only"]["codex"] == {}


def test_codex_skill_render_then_parse_is_a_fixed_point():
    c1 = empty_canonical("skill")
    c1["pair_id"] = "abc-123"
    c1["name"] = "my-skill"
    c1["description"] = "skill desc"
    c1["body"] = "the body"

    rendered = render_codex_skill_md(c1)
    c2 = parse_codex_skill_md(rendered, prior_canonical=c1)

    assert c2["pair_id"] == c1["pair_id"]
    assert c2["name"] == c1["name"]
    assert c2["description"] == c1["description"]
    assert c2["body"] == c1["body"]


def test_codex_agent_parse_strips_legacy_review_metadata():
    """A v0.1-style developer_instructions value with the review-metadata tail
    parses into canonical.body without the tail."""
    text = (
        'pair_id = "abc"\n'
        'name = "x"\n'
        'description = "y"\n'
        'developer_instructions = "real body\\n\\n---\\nConverted Claude-specific metadata for manual review:\\n{}"\n'
    )
    c = parse_codex_agent_toml(text)
    assert c["body"] == "real body"


def test_codex_agent_parse_preserves_marker_when_prior_canonical_is_modern():
    """A v0.4+ prior canonical (schema_version >= 4) means the marker is user-
    authored content, not v0.1 conversion fallout — preserve it verbatim
    (audit slice 07 · CQ-16)."""
    text = (
        'pair_id = "abc"\n'
        'name = "x"\n'
        'description = "y"\n'
        'developer_instructions = "real body\\n\\n---\\nConverted Claude-specific metadata for manual review:\\n{}"\n'
    )
    prior = {"pair_id": "abc", "kind": "agent", "schema_version": 4}
    c = parse_codex_agent_toml(text, prior_canonical=prior)
    # Marker tail preserved because prior is at modern schema.
    assert "Converted Claude-specific metadata" in c["body"]


def test_codex_agent_parse_preserves_unknown_fields_in_per_agentic_tool_extra():
    text = (
        'pair_id = "abc"\n'
        'name = "x"\n'
        'description = "y"\n'
        'developer_instructions = "body"\n'
        'unknown_codex_field = "value"\n'
    )
    c = parse_codex_agent_toml(text)
    assert c["per_agentic_tool_extra"]["codex"] == {"unknown_codex_field": "value"}


def test_codex_agent_parse_tolerates_utf8_bom():
    text = (
        '\ufeffpair_id = "abc"\n'
        'name = "x"\n'
        'description = "y"\n'
        'developer_instructions = "body"\n'
    )
    c = parse_codex_agent_toml(text)
    assert c["pair_id"] == "abc"
    assert c["name"] == "x"
    assert c["description"] == "y"
    assert c["body"] == "body"
