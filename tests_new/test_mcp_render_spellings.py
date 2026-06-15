"""Per-tool mcp render-field spellings for the simple tools (rebuild S20 increment 4).

claude, cursor, and copilot spell the mcp transport field ``type`` (not ``transport``);
claude and copilot render auth under ``oauth``. These are pure ``McpSpellingRecipe`` DATA in
each tool module, reusing the increment-3 knobs — no dialect change. A fresh cross-tool
projection (no observed spelling) must emit each tool's native field spelling. Driven through
the REAL registry recipes (NFR-11/18).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import KeyedMapSlot, ToolSurface
from agents_sync.tools.agentic_tools_registry import tool_definition
from agents_sync.translation import canonical_to_file

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"


def _mcp_surface(tool: str, slot: str = "github") -> ToolSurface:
    [recipe] = [r for r in tool_definition(tool).surface_recipes if r.kind == "mcp_server"]
    location = KeyedMapSlot(file=Path(f"/u/{tool}.json"), slot=slot)
    return ToolSurface(tool, "mcp_server", location, recipe.surface_format)


def _rendered_slot(canonical: CanonicalDocument, surface: ToolSurface) -> dict[str, Any]:
    text = canonical_to_file(canonical, surface, None)
    return json.loads(text)[surface.surface_format.map_key_path[0]]["github"]


@pytest.mark.parametrize("tool", ("claude", "cursor", "copilot"))
def test_fresh_projection_emits_the_type_transport_field(tool: str) -> None:
    canonical = CanonicalDocument(
        artifact_id=_ARTIFACT_ID,
        kind="mcp_server",
        name="github",
        transport="stdio",
        command="npx",
    )
    slot = _rendered_slot(canonical, _mcp_surface(tool))

    assert slot["type"] == "stdio"
    assert "transport" not in slot


@pytest.mark.parametrize("tool", ("claude", "copilot"))
def test_fresh_projection_emits_oauth_auth(tool: str) -> None:
    canonical = CanonicalDocument(
        artifact_id=_ARTIFACT_ID,
        kind="mcp_server",
        name="github",
        transport="http",
        url="https://mcp.example.com",
        auth={"token": "x"},
    )
    slot = _rendered_slot(canonical, _mcp_surface(tool))

    assert slot["oauth"] == {"token": "x"}
    assert "auth" not in slot
