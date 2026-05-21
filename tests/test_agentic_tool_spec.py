"""Smoke tests for the AgenticToolSpec registry."""
from __future__ import annotations

import textwrap

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    default_agentic_tools,
)
from agents_sync.canonical import empty_canonical


def test_default_registry_has_claude_codex_antigravity_and_opencode():
    registry = default_agentic_tools()
    assert set(registry.keys()) == {"claude", "codex", "antigravity", "opencode"}
    for spec in registry.values():
        assert isinstance(spec, AgenticToolSpec)


def test_antigravity_spec_is_skill_only_with_disable_key():
    spec = default_agentic_tools()["antigravity"]
    assert spec.supported_customization_types == frozenset({"skill"})
    assert spec.config_dir_keys == {"skill": "antigravity_skills_dir"}
    assert spec.disable_config_key == "antigravity_enabled"
    io = spec.io["skill"]
    assert io.storage == "directory_skill"
    assert io.file_suffix == ""


def test_claude_and_codex_have_no_disable_key():
    """claude and codex are always enabled; optional tools can be opted out."""
    registry = default_agentic_tools()
    assert registry["claude"].disable_config_key is None
    assert registry["codex"].disable_config_key is None


def test_claude_spec_supports_both_customization_types():
    spec = default_agentic_tools()["claude"]
    assert spec.supported_customization_types == frozenset({
        "agent",
        "skill",
        "slash_command",
        "rules",
        "mcp_server",
    })
    assert spec.config_dir_keys == {
        "agent": "claude_agents_dir",
        "slash_command": "claude_commands_dir",
        "skill": "claude_skills_dir",
        "rules": "claude_rules_dir",
        "mcp_server": "claude_mcp_servers_file",
    }
    for ct in ("agent", "skill", "slash_command", "rules", "mcp_server"):
        io = spec.io[ct]
        assert isinstance(io, CustomizationTypeIO)
    assert spec.io["agent"].storage == "single_file"
    assert spec.io["agent"].file_suffix == ".md"
    assert spec.io["skill"].storage == "directory_skill"
    assert spec.io["slash_command"].storage == "single_file"
    assert spec.io["slash_command"].file_suffix == ".md"
    assert spec.io["slash_command"].recursive is True
    assert spec.io["rules"].storage == "single_file"
    assert spec.io["rules"].fixed_file_name == "CLAUDE.md"


def test_codex_spec_supports_agents_and_skills():
    spec = default_agentic_tools()["codex"]
    assert spec.supported_customization_types == frozenset({
        "agent",
        "skill",
        "slash_command",
        "rules",
        "mcp_server",
    })
    assert spec.config_dir_keys == {
        "agent": "codex_agents_dir",
        "slash_command": "codex_prompts_dir",
        "skill": "codex_skills_dir",
        "rules": "codex_rules_dir",
        "mcp_server": "codex_config_file",
    }
    assert spec.io["agent"].storage == "single_file"
    assert spec.io["agent"].file_suffix == ".toml"
    assert spec.io["skill"].storage == "directory_skill"
    assert spec.io["slash_command"].storage == "single_file"
    assert spec.io["slash_command"].file_suffix == ".md"
    assert spec.io["slash_command"].recursive is True
    assert spec.io["rules"].fixed_file_name == "AGENTS.md"
    assert spec.io["mcp_server"].storage == "shared_keyed_map"


def test_opencode_spec_supports_agents_and_skills_with_disable_key():
    spec = default_agentic_tools()["opencode"]
    assert spec.supported_customization_types == frozenset({
        "agent",
        "skill",
        "slash_command",
        "rules",
        "mcp_server",
    })
    assert spec.config_dir_keys == {
        "agent": "opencode_agents_dir",
        "slash_command": "opencode_commands_dir",
        "skill": "opencode_skills_dir",
        "rules": "opencode_rules_dir",
        "mcp_server": "opencode_config_file",
    }
    assert spec.disable_config_key == "opencode_enabled"
    assert spec.io["agent"].storage == "single_file"
    assert spec.io["agent"].file_suffix == ".md"
    assert spec.io["skill"].storage == "directory_skill"
    assert spec.io["slash_command"].storage == "single_file"
    assert spec.io["slash_command"].file_suffix == ".md"
    assert spec.io["slash_command"].recursive is True
    assert spec.io["slash_command"].reserved_names == frozenset({
        "build",
        "plan",
        "general",
        "explore",
        "scout",
    })
    assert spec.io["rules"].fixed_file_name == "AGENTS.md"
    assert spec.io["mcp_server"].storage == "shared_keyed_map"


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


def test_codex_skill_io_dispatches_to_skill_md_renderer():
    c = empty_canonical("skill")
    c["pair_id"] = "00000000-0000-4000-8000-000000000001"
    c["name"] = "demo-skill"
    c["description"] = "registry-driven render"
    c["body"] = "instructions go here"
    io = default_agentic_tools()["codex"].io["skill"]
    rendered = io.render(c, None)
    assert "name: demo-skill" in rendered
    assert "pair_id: 00000000-0000-4000-8000-000000000001" in rendered
    assert io.extract_pair_id(rendered) == "00000000-0000-4000-8000-000000000001"
