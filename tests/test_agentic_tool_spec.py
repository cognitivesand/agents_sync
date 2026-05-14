"""Smoke tests for the AgenticToolSpec registry."""
from __future__ import annotations

import textwrap

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    default_agentic_tools,
)
from agents_sync.canonical import empty_canonical


def test_default_registry_has_claude_and_codex():
    registry = default_agentic_tools()
    assert set(registry.keys()) == {"claude", "codex"}
    for spec in registry.values():
        assert isinstance(spec, AgenticToolSpec)


def test_claude_spec_supports_both_customization_types():
    spec = default_agentic_tools()["claude"]
    assert spec.supported_customization_types == frozenset({"agent", "skill"})
    assert spec.config_dir_keys == {
        "agent": "claude_agents_dir",
        "skill": "claude_skills_dir",
    }
    for ct in ("agent", "skill"):
        io = spec.io[ct]
        assert isinstance(io, CustomizationTypeIO)
    assert spec.io["agent"].storage == "single_file"
    assert spec.io["agent"].file_suffix == ".md"
    assert spec.io["skill"].storage == "directory_skill"


def test_codex_spec_supports_both_customization_types():
    spec = default_agentic_tools()["codex"]
    assert spec.supported_customization_types == frozenset({"agent", "skill"})
    assert spec.config_dir_keys == {
        "agent": "codex_agents_dir",
        "skill": "codex_skills_dir",
    }
    assert spec.io["agent"].storage == "single_file"
    assert spec.io["agent"].file_suffix == ".toml"
    assert spec.io["skill"].storage == "directory_skill"


def test_claude_agent_io_round_trips_through_registry():
    text = textwrap.dedent(
        """\
        ---
        pair_id: 11111111-2222-3333-4444-555555555555
        name: demo-agent
        description: registry-driven round trip
        ---
        body content
        """
    )
    io = default_agentic_tools()["claude"].io["agent"]
    canonical = io.parse(text, None)
    assert canonical["name"] == "demo-agent"
    assert io.extract_pair_id(text) == "11111111-2222-3333-4444-555555555555"
    rendered = io.render(canonical, text)
    canonical_again = io.parse(rendered, canonical)
    assert canonical_again["name"] == canonical["name"]
    assert canonical_again["body"] == canonical["body"]


def test_codex_agent_io_dispatches_to_toml_renderer():
    c = empty_canonical("agent")
    c["pair_id"] = "abc-123"
    c["name"] = "demo-agent"
    c["description"] = "registry-driven render"
    c["body"] = "instructions go here"
    io = default_agentic_tools()["codex"].io["agent"]
    rendered = io.render(c, None)
    assert 'pair_id = "abc-123"' in rendered
    assert 'name = "demo-agent"' in rendered
    assert io.extract_pair_id(rendered) == "abc-123"
