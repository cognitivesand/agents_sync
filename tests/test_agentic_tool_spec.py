"""Smoke tests for the AgenticToolSpec registry."""
from __future__ import annotations

import textwrap

import pytest

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    SingleFileLayout,
    default_agentic_tools,
)
from agents_sync.canonical import empty_canonical


def test_agentic_tool_spec_rejects_drift_between_config_keys_and_io():
    """Audit slice 05 · CQ-03: a missing key in either dict is a clear ValueError."""
    io = CustomizationTypeIO(
        parse=lambda *a, **k: {},
        render=lambda *a, **k: "",
        extract_pair_id=lambda *a, **k: None,
        file_layout=SingleFileLayout(extension=".md"),
    )
    with pytest.raises(ValueError, match="capability matrix drift"):
        AgenticToolSpec(
            name="example",
            config_dir_keys={"agent": "example_agents_dir"},
            io={"agent": io, "skill": io},  # skill listed in io but not config
        )

    with pytest.raises(ValueError, match="capability matrix drift"):
        AgenticToolSpec(
            name="example",
            config_dir_keys={"agent": "example_agents_dir", "skill": "example_skills_dir"},
            io={"agent": io},  # skill listed in config but not io
        )


def test_customization_type_io_uses_file_layout_as_single_source():
    layout = SingleFileLayout(extension=".md", fixed_file_name="AGENTS.md")
    io = CustomizationTypeIO(
        parse=lambda *a, **k: {},
        render=lambda *a, **k: "",
        extract_pair_id=lambda *a, **k: None,
        file_layout=layout,
    )

    assert "storage" not in CustomizationTypeIO.__dataclass_fields__
    assert "file_suffix" not in CustomizationTypeIO.__dataclass_fields__
    assert io.file_layout is layout
    assert io.storage == "single_file"
    assert io.file_suffix == ".md"
    assert io.fixed_file_name == "AGENTS.md"


def test_default_registry_has_all_supported_tools():
    registry = default_agentic_tools()
    assert set(registry.keys()) == {
        "claude",
        "codex",
        "copilot",
        "cursor",
        "gemini_cli",
        "antigravity",
        "opencode",
    }
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


def test_cursor_spec_supports_all_file_backed_cursor_types():
    spec = default_agentic_tools()["cursor"]
    assert spec.supported_customization_types == frozenset({
        "agent",
        "skill",
        "slash_command",
        "rules",
        "mcp_server",
    })
    assert spec.config_dir_keys == {
        "agent": "cursor_agents_dir",
        "slash_command": "cursor_commands_dir",
        "skill": "cursor_skills_dir",
        "rules": "cursor_rules_dir",
        "mcp_server": "cursor_mcp_servers_file",
    }
    assert spec.disable_config_key == "cursor_enabled"
    assert spec.io["agent"].storage == "single_file"
    assert spec.io["agent"].file_suffix == ".md"
    assert spec.io["skill"].storage == "directory_skill"
    assert spec.io["slash_command"].storage == "single_file"
    assert spec.io["slash_command"].file_suffix == ".md"
    assert spec.io["slash_command"].recursive is True
    assert spec.io["rules"].file_suffix == ".mdc"
    assert spec.io["rules"].recursive is True
    assert spec.io["mcp_server"].storage == "shared_keyed_map"


def test_gemini_cli_spec_supports_file_backed_user_surfaces():
    spec = default_agentic_tools()["gemini_cli"]
    assert spec.supported_customization_types == frozenset({
        "agent",
        "skill",
        "slash_command",
        "rules",
        "mcp_server",
    })
    assert spec.config_dir_keys == {
        "agent": "gemini_cli_agents_dir",
        "slash_command": "gemini_cli_commands_dir",
        "skill": "gemini_cli_skills_dir",
        "rules": "gemini_cli_rules_dir",
        "mcp_server": "gemini_cli_settings_file",
    }
    assert spec.disable_config_key == "gemini_cli_enabled"
    assert spec.io["agent"].storage == "single_file"
    assert spec.io["agent"].file_suffix == ".md"
    assert spec.io["skill"].storage == "directory_skill"
    assert spec.io["slash_command"].storage == "single_file"
    assert spec.io["slash_command"].file_suffix == ".toml"
    assert spec.io["slash_command"].recursive is True
    assert spec.io["rules"].fixed_file_name == "GEMINI.md"
    assert spec.io["mcp_server"].storage == "shared_keyed_map"


def test_copilot_spec_supports_cli_and_vscode_user_surfaces():
    spec = default_agentic_tools()["copilot"]
    assert spec.supported_customization_types == frozenset({
        "agent",
        "skill",
        "rules",
        "slash_command",
        "mcp_server",
    })
    assert spec.config_dir_keys == {
        "agent": "copilot_cli_agents_dir",
        "skill": "copilot_cli_skills_dir",
        "rules": "copilot_vscode_user_instructions_dir",
        "slash_command": "copilot_vscode_user_prompts_dir",
        "mcp_server": "copilot_cli_mcp_config_file",
    }
    assert spec.disable_config_key == "copilot_enabled"
    assert spec.partial_availability is True
    assert spec.kind_disable_config_keys == {
        "agent": "copilot_cli_enabled",
        "skill": "copilot_cli_enabled",
        "mcp_server": "copilot_cli_enabled",
        "rules": "copilot_vscode_user_profile_enabled",
        "slash_command": "copilot_vscode_user_profile_enabled",
    }
    assert spec.io["agent"].storage == "single_file"
    assert spec.io["agent"].file_suffix == ".agent.md"
    assert spec.io["agent"].accepted_file_suffixes == (
        ".agent.md",
        ".chatmode.md",
        ".md",
    )
    assert spec.io["skill"].storage == "directory_skill"
    assert spec.io["rules"].file_suffix == ".instructions.md"
    assert spec.io["slash_command"].file_suffix == ".prompt.md"
    assert spec.io["slash_command"].recursive is True
    assert spec.io["mcp_server"].storage == "shared_keyed_map"
    assert spec.io["mcp_server"].file_layout is not None
    assert spec.io["mcp_server"].file_layout.shared_path_config_key == (
        "copilot_cli_mcp_config_file"
    )
    assert spec.io["mcp_server"].file_layout.map_key_path == ("servers",)


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


# ---------------- per-tool mcp_server capability assertions ----------------
# Audit slice 05 · CQ-09: pin map_key_path / file_format / dialect-driven
# behavior on each tool so adapter PRs cannot silently regress the shape of
# the shared file (e.g. by swapping mcpServers ↔ mcp without noticing).

from agents_sync.agentic_tool_spec import SharedKeyedMapLayout


@pytest.mark.parametrize(
    "tool_name, expected_map_key_path, expected_file_format",
    [
        ("claude", ("mcpServers",), "json"),
        ("codex", ("mcp_servers",), "toml"),
        ("gemini_cli", ("mcpServers",), "json"),
        ("opencode", ("mcp",), "json"),
    ],
)
def test_mcp_server_layout_per_tool(
    tool_name: str,
    expected_map_key_path: tuple[str, ...],
    expected_file_format: str,
):
    spec = default_agentic_tools()["claude" if tool_name == "claude" else tool_name]
    io = spec.io["mcp_server"]
    assert isinstance(io.file_layout, SharedKeyedMapLayout)
    assert io.file_layout.map_key_path == expected_map_key_path
    assert io.file_layout.file_format == expected_file_format
    assert io.file_layout.key_field == "name"


@pytest.mark.parametrize("tool_name", ["claude", "codex", "gemini_cli", "opencode"])
def test_mcp_server_round_trip_per_tool(tool_name: str):
    """Adapter-dialect smoke test: a stdio entry parses then renders back to
    a shape carrying name + command for that tool, with the per-tool slot
    format honoured (codex serialises TOML, the rest JSON)."""
    spec = default_agentic_tools()[tool_name]
    io = spec.io["mcp_server"]
    canonical = empty_canonical("mcp_server")
    _tool_digit = {"claude": 1, "codex": 2, "gemini_cli": 3, "opencode": 4}[tool_name]
    canonical["pair_id"] = f"00000000-0000-4000-8000-00000000000{_tool_digit}"
    canonical["name"] = "filesystem"
    canonical["transport"] = "stdio"
    canonical["command"] = "fs-mcp"
    canonical["args"] = ["--root", "/tmp"]
    canonical["per_agentic_tool_only"] = {tool_name: {}}
    canonical["per_agentic_tool_extra"] = {tool_name: {}}

    rendered = io.render(canonical, None)
    # The name is carried as the slot key in the shared file's map, so it
    # need not appear in the slot body itself (claude/codex/opencode all set
    # render_name_field=False). The command always lands in-body.
    assert "fs-mcp" in rendered
    # Reparsing requires the name to come from somewhere — pass it via the
    # prior_canonical, which is the same path the sync engine takes after
    # the first adoption (the slot key becomes canonical['name']).
    parsed = io.parse(rendered, canonical)
    assert parsed["name"] == "filesystem"
    assert parsed["command"] == "fs-mcp"
    assert parsed["transport"] == "stdio"
    assert io.extract_pair_id(rendered) == canonical["pair_id"]


@pytest.mark.parametrize("tool_name", ["claude", "codex", "opencode"])
def test_slash_command_round_trip_per_tool(tool_name: str):
    """slash_command must round-trip name and body across every tool."""
    spec = default_agentic_tools()[tool_name]
    io = spec.io["slash_command"]
    pair_id = "11111111-2222-3333-4444-555555555555"
    text = textwrap.dedent(
        f"""\
        ---
        pair_id: {pair_id}
        name: demo
        description: round-trip
        ---
        body for {tool_name}
        """
    )
    canonical = io.parse(text, None)
    assert canonical["name"] == "demo"
    assert "body for" in canonical["body"]
    rendered = io.render(canonical, text)
    canonical_again = io.parse(rendered, canonical)
    assert canonical_again["name"] == canonical["name"]
    assert canonical_again["body"].rstrip() == canonical["body"].rstrip()
    assert io.extract_pair_id(rendered) == pair_id


@pytest.mark.parametrize("tool_name", ["claude", "codex", "opencode"])
def test_rules_round_trip_per_tool(tool_name: str):
    """rules cell must round-trip pair_id and body. The canonical_name is
    fixed to 'global' by the factory, so the parsed name is always 'global'
    regardless of frontmatter (audit slice 05 · CQ-09 + 07 · CQ-04)."""
    spec = default_agentic_tools()[tool_name]
    io = spec.io["rules"]
    pair_id = "22222222-3333-4444-5555-666666666666"
    text = textwrap.dedent(
        f"""\
        ---
        pair_id: {pair_id}
        ---
        rules body for {tool_name}
        """
    )
    canonical = io.parse(text, None)
    assert canonical["name"] == "global"
    assert f"rules body for {tool_name}" in canonical["body"]
    rendered = io.render(canonical, text)
    assert io.extract_pair_id(rendered) == pair_id
    canonical_again = io.parse(rendered, canonical)
    assert canonical_again["body"].rstrip() == canonical["body"].rstrip()
