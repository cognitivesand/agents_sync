"""Per-tool inline env-reference style, data-driven (rebuild S20 increment 7; FR-09, NFR-16/11/18).

The canonical stores every env-reference in one FIXED form, ``${env:NAME}`` — so two
semantically-equal references never differ textually and the content digest stays stable
(NFR-16). Each tool's wire uses its own native inline style: claude and gemini write
``${NAME}``, opencode writes ``{env:NAME}``, and cursor/codex/copilot keep the canonical
``${env:NAME}``. The dialect canonicalizes any recognized form on parse and restyles to the
tool's ``env_reference_style`` (a ``(prefix, suffix)`` recipe data knob — no tool-name branch)
on render, across the ``env`` / ``auth`` / ``headers`` value maps. The tests drive each tool's
REAL recipe through the registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents_sync.dialects import structured_text
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import KeyedMapSlot, ToolSurface
from agents_sync.tools.agentic_tools_registry import tool_definition
from agents_sync.translation import canonical_to_file, file_to_canonical

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
_URL = "https://mcp.example.com"


def _mcp_surface(tool: str, slot: str = "github") -> ToolSurface:
    [recipe] = [r for r in tool_definition(tool).surface_recipes if r.kind == "mcp_server"]
    location = KeyedMapSlot(file=Path(f"/u/{tool}.cfg"), slot=slot)
    return ToolSurface(tool, "mcp_server", location, recipe.surface_format)


def _file_for(surface: ToolSurface, slots: dict[str, Any]) -> str:
    fmt = surface.surface_format
    return structured_text.serialize({fmt.map_key_path[0]: slots}, fmt.file_format)


def _rendered_slot(
    canonical: CanonicalDocument, surface: ToolSurface, slot: str = "github"
) -> dict[str, Any]:
    fmt = surface.surface_format
    text = canonical_to_file(canonical, surface, None)
    return structured_text.deserialize(text, fmt.file_format)[fmt.map_key_path[0]][slot]


def _http_doc(**fields: Any) -> CanonicalDocument:
    return CanonicalDocument(
        artifact_id=_ARTIFACT_ID, kind="mcp_server", name="github",
        transport="http", url=_URL, **fields
    )


def _stdio_doc(**fields: Any) -> CanonicalDocument:
    return CanonicalDocument(
        artifact_id=_ARTIFACT_ID, kind="mcp_server", name="github",
        transport="stdio", command="npx", **fields
    )


# --- render: the canonical ${env:NAME} restyles to each tool's native inline form -----


def test_claude_renders_a_header_env_ref_in_its_dollar_brace_style() -> None:
    canonical = _http_doc(headers={"Authorization": "Bearer ${env:TOK}"})
    slot = _rendered_slot(canonical, _mcp_surface("claude"))

    assert slot["headers"]["Authorization"] == "Bearer ${TOK}"


def test_gemini_renders_a_header_env_ref_in_its_dollar_brace_style() -> None:
    slot = _rendered_slot(_http_doc(headers={"X-Key": "${env:KEY}"}), _mcp_surface("gemini_cli"))

    assert slot["headers"]["X-Key"] == "${KEY}"


def test_opencode_renders_an_env_value_in_its_brace_env_style() -> None:
    slot = _rendered_slot(_stdio_doc(env={"GH": "${env:TOKEN}"}), _mcp_surface("opencode"))

    assert slot["environment"]["GH"] == "{env:TOKEN}"


def test_a_canonical_style_tool_emits_env_refs_unchanged() -> None:
    # cursor declares no style override, so the canonical ${env:NAME} form is emitted verbatim.
    slot = _rendered_slot(_http_doc(headers={"X-Key": "${env:KEY}"}), _mcp_surface("cursor"))

    assert slot["headers"]["X-Key"] == "${env:KEY}"


def test_an_auth_env_ref_is_restyled_too_not_only_headers() -> None:
    slot = _rendered_slot(_http_doc(auth={"token": "${env:TOK}"}), _mcp_surface("claude"))

    assert slot["oauth"]["token"] == "${TOK}"


# --- parse: each tool's native inline form canonicalizes to ${env:NAME} ---------------


def test_claude_inline_header_env_ref_canonicalizes_on_parse() -> None:
    surface = _mcp_surface("claude")
    text = _file_for(
        surface,
        {"github": {"type": "http", "url": _URL, "headers": {"Authorization": "Bearer ${TOK}"}}},
    )

    assert file_to_canonical(text, surface, None).headers == {"Authorization": "Bearer ${env:TOK}"}


def test_opencode_inline_env_value_canonicalizes_on_parse() -> None:
    surface = _mcp_surface("opencode")
    text = _file_for(surface, {"github": {"command": "npx", "environment": {"GH": "{env:TOKEN}"}}})

    assert file_to_canonical(text, surface, None).env == {"GH": "${env:TOKEN}"}


# --- cross-tool: an env ref propagates through the canonical hub in each tool's style --


def test_an_env_ref_propagates_from_claude_to_opencode_in_each_native_style() -> None:
    claude = _mcp_surface("claude")
    claude_text = _file_for(claude, {"github": {"command": "npx", "env": {"GH": "${TOKEN}"}}})

    canonical = file_to_canonical(claude_text, claude, None)
    opencode_slot = _rendered_slot(canonical, _mcp_surface("opencode"))

    assert canonical.env == {"GH": "${env:TOKEN}"}  # hub stores the canonical form
    assert opencode_slot["environment"]["GH"] == "{env:TOKEN}"  # emitted in opencode's form
