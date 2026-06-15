"""Per-tool agent field maps (rebuild S20 increment 2, NFR-16 / NFR-11/18).

Each tool's native agent-config spellings for model / reasoning-effort / tools
(plus claude's ``disallowedTools`` / ``permissionMode`` and codex's
``model_reasoning_effort``) fold onto the EXISTING canonical attributes via the
tool's ``known_fields`` recipe data — no dialect change. A field a tool does not
declare stays verbatim in ``per_tool_extra`` (no-foreign-leak); only declared
fields canonicalise, so the content rule can project them across surfaces (US-06).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import ToolSurface
from agents_sync.tools.agentic_tools_registry import tool_definition
from agents_sync.translation import canonical_to_file, file_to_canonical

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"


def _agent_surface(tool_name: str, path: Path) -> ToolSurface:
    """The tool's ``agent`` recipe as a ``ToolSurface`` at ``path``."""
    [recipe] = [r for r in tool_definition(tool_name).surface_recipes if r.kind == "agent"]
    return ToolSurface(tool_name, "agent", path, recipe.surface_format)


def test_claude_agent_field_map_round_trips_its_native_spellings(tmp_path: Path) -> None:
    surface = _agent_surface("claude", tmp_path / "agent.md")
    canonical = CanonicalDocument(
        artifact_id=_ARTIFACT_ID,
        kind="agent",
        name="reviewer",
        model="opus",
        effort="high",
        tools=("Read",),
        disallowed_tools=("Bash",),
        permission_mode="ask",
    )

    rendered = canonical_to_file(canonical, surface, None)
    reparsed = file_to_canonical(rendered, surface, None)

    # The native front-matter spellings are emitted — never the canonical names.
    assert "disallowedTools:" in rendered
    assert "permissionMode:" in rendered
    assert "disallowed_tools" not in rendered
    assert "permission_mode" not in rendered
    # And every mapped field folds back onto its canonical attribute.
    assert reparsed.model == "opus"
    assert reparsed.effort == "high"
    assert reparsed.tools == ("Read",)
    assert reparsed.disallowed_tools == ("Bash",)
    assert reparsed.permission_mode == "ask"
    assert reparsed.per_tool_extra.get("claude", {}) == {}


def test_codex_agent_field_map_round_trips_its_toml_effort_spelling(tmp_path: Path) -> None:
    surface = _agent_surface("codex", tmp_path / "agent.toml")
    canonical = CanonicalDocument(
        artifact_id=_ARTIFACT_ID,
        kind="agent",
        name="reviewer",
        model="gpt-5-codex",
        effort="high",
    )

    rendered = canonical_to_file(canonical, surface, None)
    reparsed = file_to_canonical(rendered, surface, None)

    assert 'model = "gpt-5-codex"' in rendered
    assert "model_reasoning_effort" in rendered  # codex's native effort spelling
    assert reparsed.model == "gpt-5-codex"
    assert reparsed.effort == "high"


@pytest.mark.parametrize("tool_name", ("cursor", "copilot"))
def test_a_tool_folds_model_and_tools(tool_name: str, tmp_path: Path) -> None:
    surface = _agent_surface(tool_name, tmp_path / "agent.md")
    canonical = CanonicalDocument(
        artifact_id=_ARTIFACT_ID,
        kind="agent",
        name="reviewer",
        model="opus",
        tools=("Read", "Edit"),
    )

    rendered = canonical_to_file(canonical, surface, None)
    reparsed = file_to_canonical(rendered, surface, None)

    assert "model: opus" in rendered
    assert reparsed.model == "opus"
    assert reparsed.tools == ("Read", "Edit")


def test_gemini_folds_its_model_field(tmp_path: Path) -> None:
    surface = _agent_surface("gemini_cli", tmp_path / "agent.md")
    canonical = CanonicalDocument(
        artifact_id=_ARTIFACT_ID, kind="agent", name="reviewer", model="gemini-2.5-pro"
    )

    rendered = canonical_to_file(canonical, surface, None)
    reparsed = file_to_canonical(rendered, surface, None)

    assert "model: gemini-2.5-pro" in rendered
    assert reparsed.model == "gemini-2.5-pro"


def test_model_propagates_from_claude_to_cursor(tmp_path: Path) -> None:
    # The point of canonicalising a shared field: an edit to one tool's model
    # surfaces on another tool that maps the same canonical attribute (US-06).
    claude_surface = _agent_surface("claude", tmp_path / "claude.md")
    cursor_surface = _agent_surface("cursor", tmp_path / "cursor.md")
    canonical = CanonicalDocument(
        artifact_id=_ARTIFACT_ID, kind="agent", name="reviewer", model="opus"
    )

    claude_text = canonical_to_file(canonical, claude_surface, None)
    via_claude = file_to_canonical(claude_text, claude_surface, None)
    cursor_text = canonical_to_file(via_claude, cursor_surface, None)
    via_cursor = file_to_canonical(cursor_text, cursor_surface, None)

    assert "model: opus" in cursor_text
    assert via_cursor.model == "opus"


def test_an_unmapped_field_is_preserved_verbatim_not_canonicalised(tmp_path: Path) -> None:
    # opencode declares no agent field map this increment (its model carries a
    # provider prefix the old codec splits): the value must round-trip verbatim in
    # per_tool_extra, never be silently promoted to the canonical attr.
    surface = _agent_surface("opencode", tmp_path / "agent.md")
    text = (
        f"---\npair_id: {_ARTIFACT_ID}\nname: reviewer\n"
        "model: anthropic/claude-opus\n---\nBody.\n"
    )

    canonical = file_to_canonical(text, surface, None)

    assert canonical.model is None
    assert canonical.per_tool_extra["opencode"]["model"] == "anthropic/claude-opus"
