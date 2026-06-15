"""Unit tests for the tools-as-data registry (rebuild S20 increment 1, NFR-11/18).

Each tool is one DATA module: a ``ToolDefinition`` of per-kind surface recipes
(config key + layout + ``SurfaceFormat``). The registry resolves names and turns a
definition plus resolved paths into the read phase's ``SurfaceSpec``s; a kind
whose config key has no resolved path is skipped (the tool or kind is absent —
US-11). The cross-adapter matrix proves an agent and an mcp slot round-trip
through every supporting tool's REAL dialect (NFR-11/18). Adding a tool is one
data module plus a registry entry — no sync-mechanism change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.read_tool_surfaces import (
    DirectorySurfaceSpec,
    KeyedMapSurfaceSpec,
    RulesFileSurfaceSpec,
    read_tool_surfaces,
)
from agents_sync.tools.agentic_tools_registry import (
    ALL_TOOL_DEFINITIONS,
    surface_specs_for,
    tool_definition,
)
from agents_sync.translation import canonical_to_file, file_to_canonical

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"

_EXPECTED_TOOL_NAMES = {
    "claude",
    "codex",
    "cursor",
    "copilot",
    "gemini_cli",
    "opencode",
    "antigravity",
}

# Tools whose agent surfaces are markdown front-matter files (codex agents are
# whole-file TOML; antigravity has no supported kinds until the skill dialect).
_MARKDOWN_AGENT_TOOLS = ("claude", "cursor", "copilot", "gemini_cli", "opencode")
_MCP_TOOLS = ("claude", "codex", "cursor", "copilot", "gemini_cli", "opencode")


def _recipe_for(tool_name: str, kind: str):  # noqa: ANN202 — test helper
    definition = tool_definition(tool_name)
    [recipe] = [r for r in definition.surface_recipes if r.kind == kind]
    return recipe


# --- registry shape -----------------------------------------------------------------


def test_the_registry_lists_every_supported_tool() -> None:
    assert {definition.name for definition in ALL_TOOL_DEFINITIONS} == _EXPECTED_TOOL_NAMES
    assert len(ALL_TOOL_DEFINITIONS) == len(_EXPECTED_TOOL_NAMES)  # no duplicates


def test_an_unknown_tool_name_is_a_recipe_error() -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        tool_definition("emacs")


def test_definitions_are_pure_data() -> None:
    # Tools are DATA (proposal §13): every recipe field is a value, no callables.
    for definition in ALL_TOOL_DEFINITIONS:
        for recipe in definition.surface_recipes:
            assert not any(callable(value) for value in vars(recipe).values())


# --- surface_specs_for ----------------------------------------------------------------


def test_specs_resolve_against_the_provided_paths(tmp_path: Path) -> None:
    paths = {
        "claude_agents_dir": tmp_path / "agents",
        "claude_commands_dir": tmp_path / "commands",
        "claude_rules_dir": tmp_path,
        "claude_mcp_servers_file": tmp_path / ".claude.json",
    }

    specs = surface_specs_for(tool_definition("claude"), paths)

    by_kind = {spec.kind: spec for spec in specs}
    assert isinstance(by_kind["agent"], DirectorySurfaceSpec), "agent resolves to a directory spec"
    assert by_kind["agent"].directory == tmp_path / "agents", "agent directory resolved from paths"
    assert isinstance(
        by_kind["slash_command"], DirectorySurfaceSpec
    ), "slash_command resolves to a directory spec"
    assert isinstance(by_kind["rules"], RulesFileSurfaceSpec), "rules resolves to a rules-file spec"
    assert by_kind["rules"].candidate_filenames == (
        "AGENTS.md",
        "CLAUDE.md",
    ), "rules candidate filenames in precedence order"
    assert isinstance(
        by_kind["mcp_server"], KeyedMapSurfaceSpec
    ), "mcp_server resolves to a keyed-map spec"
    assert by_kind["mcp_server"].file == tmp_path / ".claude.json", "mcp_server file resolved"


def test_a_kind_without_a_resolved_path_is_skipped(tmp_path: Path) -> None:
    # US-11: an absent tool/kind contributes no surfaces and blocks nothing.
    specs = surface_specs_for(tool_definition("claude"), {"claude_agents_dir": tmp_path / "agents"})

    assert {spec.kind for spec in specs} == {"agent"}


def test_gemini_rules_resolve_to_gemini_md_through_the_read_phase(tmp_path: Path) -> None:
    # FR-10: the read phase resolves gemini's single rules surface to GEMINI.md from the
    # recipe's candidate_filenames — a behaviour the shape of the recipe alone does not prove.
    (tmp_path / "GEMINI.md").write_text("Be terse.\n")
    specs = surface_specs_for(tool_definition("gemini_cli"), {"gemini_cli_rules_dir": tmp_path})

    observations = read_tool_surfaces(specs)

    [rules] = [obs for obs in observations if obs.tool_surface.kind == "rules"]
    assert rules.tool_surface.location == tmp_path / "GEMINI.md"


# codex's mcp_server TOML / [mcp_servers] resolution is exercised end-to-end by the
# parametrized round-trip below (test_an_mcp_slot_round_trips_through_every_tool_recipe drives
# codex's REAL recipe), so a separate recipe-shape assertion would only duplicate it.


# --- cross-adapter matrix (NFR-11/18) ---------------------------------------------------


def _agent_canonical() -> CanonicalDocument:
    return CanonicalDocument(
        artifact_id=_ARTIFACT_ID,
        kind="agent",
        name="code reviewer",
        description="reviews diffs",
        body="Be terse.\n",
    )


@pytest.mark.parametrize("source_tool", _MARKDOWN_AGENT_TOOLS)
@pytest.mark.parametrize("target_tool", _MARKDOWN_AGENT_TOOLS)
def test_an_agent_round_trips_between_every_markdown_tool_pair(
    source_tool: str, target_tool: str, tmp_path: Path
) -> None:
    # NFR-18: project the canonical onto the source tool, parse it back, project
    # that onto the target tool, parse again — the content survives both hops.
    source_recipe = _recipe_for(source_tool, "agent")
    target_recipe = _recipe_for(target_tool, "agent")
    from agents_sync.domain_model.tool_surface import ToolSurface

    source_surface = ToolSurface(
        source_tool, "agent", tmp_path / "reviewer.md", source_recipe.surface_format
    )
    target_surface = ToolSurface(
        target_tool, "agent", tmp_path / "reviewer2.md", target_recipe.surface_format
    )

    source_text = canonical_to_file(_agent_canonical(), source_surface, None)
    via_source = file_to_canonical(source_text, source_surface, None)
    target_text = canonical_to_file(via_source, target_surface, None)
    via_target = file_to_canonical(target_text, target_surface, None)

    assert via_target.name == "code reviewer"
    assert via_target.description == "reviews diffs"
    assert via_target.body.strip() == "Be terse."
    assert via_target.artifact_id == _ARTIFACT_ID


@pytest.mark.parametrize("tool_name", _MCP_TOOLS)
def test_an_mcp_slot_round_trips_through_every_tool_recipe(tool_name: str, tmp_path: Path) -> None:
    from agents_sync.domain_model.tool_surface import KeyedMapSlot, ToolSurface

    recipe = _recipe_for(tool_name, "mcp_server")
    file = tmp_path / "config"
    surface = ToolSurface(
        tool_name,
        "mcp_server",
        KeyedMapSlot(file=file, slot="github"),
        recipe.surface_format,
    )
    canonical = CanonicalDocument(
        artifact_id=_ARTIFACT_ID,
        kind="mcp_server",
        name="github",
        transport="stdio",
        command="npx",
        args=("-y", "gh-mcp"),
        env={"GH": "${TOKEN}"},
    )

    rendered = canonical_to_file(canonical, surface, None)
    reparsed = file_to_canonical(rendered, surface, None)

    assert reparsed.command == "npx"
    assert reparsed.args == ("-y", "gh-mcp")
    # round-trips through every tool's native env-reference style back to the canonical
    # ${env:NAME} form, regardless of how each tool spells it on the wire (S20 increment 7).
    assert reparsed.env == {"GH": "${env:TOKEN}"}
    assert reparsed.artifact_id == _ARTIFACT_ID


def test_registry_specs_feed_the_read_phase_end_to_end(tmp_path: Path) -> None:
    # The integration seam: definition -> specs -> observations through real files.
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "reviewer.md").write_text(
        f"---\npair_id: {_ARTIFACT_ID}\nname: reviewer\n---\nBe terse.\n"
    )
    mcp_file = tmp_path / ".claude.json"
    mcp_file.write_text(json.dumps({"mcpServers": {"github": {"command": "npx"}}}))
    specs = surface_specs_for(
        tool_definition("claude"),
        {"claude_agents_dir": agents_dir, "claude_mcp_servers_file": mcp_file},
    )

    observations = read_tool_surfaces(specs)

    kinds = {obs.tool_surface.kind for obs in observations}
    assert kinds == {"agent", "mcp_server"}
    assert all(isinstance(obs.parsed, CanonicalDocument) for obs in observations)
