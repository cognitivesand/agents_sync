"""opencode's mcp dialect, data-driven (rebuild S20 increment 3, FR-09 / NFR-16 / NFR-11/18).

opencode spells the mcp wire differently from the canonical defaults: ``environment``
for env, an INVERTED ``enabled`` flag (enabled = not disabled), an ``array`` command,
``type`` transport with ``local``/``remote`` values, and ``oauth`` auth. These live as a
``McpSpellingRecipe`` in opencode's tool module and are consumed generically by the dialect
(no tool-name branches). The tests drive opencode's REAL recipe through the registry, so
they prove the data wiring end-to-end. Folding ``environment``/``enabled`` onto the canonical
is the correctness win: today they strand in ``per_tool_extra`` and never sync.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import KeyedMapSlot, ToolSurface
from agents_sync.tools.agentic_tools_registry import tool_definition
from agents_sync.translation import canonical_to_file, file_to_canonical

_EMBEDDED_ID = "11111111-1111-4111-8111-111111111111"


def _mcp_surface(tool: str, slot: str = "github") -> ToolSurface:
    """The tool's REAL mcp_server recipe as a ToolSurface (drives the data, not a stub)."""
    [recipe] = [r for r in tool_definition(tool).surface_recipes if r.kind == "mcp_server"]
    location = KeyedMapSlot(file=Path(f"/u/{tool}.json"), slot=slot)
    return ToolSurface(tool, "mcp_server", location, recipe.surface_format)


def _file_for(surface: ToolSurface, slots: dict[str, Any]) -> str:
    """A shared config file for ``surface``, keyed by its own recipe's map_key_path."""
    return json.dumps({surface.surface_format.map_key_path[0]: slots})


def _rendered_slot(
    canonical: CanonicalDocument,
    surface: ToolSurface,
    prior: str | None = None,
    slot: str = "github",
) -> dict[str, Any]:
    text = canonical_to_file(canonical, surface, prior)
    return json.loads(text)[surface.surface_format.map_key_path[0]][slot]


def _stdio(**fields: Any) -> CanonicalDocument:
    return CanonicalDocument(
        artifact_id=_EMBEDDED_ID, kind="mcp_server", name="github",
        transport="stdio", command="npx", args=("-y", "gh-mcp"), **fields
    )


# --- parse: opencode's native spellings reach the canonical ---------------------------


def test_opencode_environment_folds_to_canonical_env() -> None:
    surface = _mcp_surface("opencode")
    # opencode's native env-reference style is `{env:NAME}`; it canonicalizes on the fold.
    text = _file_for(surface, {"github": {"command": "npx", "environment": {"GH": "{env:TOKEN}"}}})

    canonical = file_to_canonical(text, surface, None)

    assert canonical.env == {"GH": "${env:TOKEN}"}
    assert "environment" not in canonical.per_tool_extra.get("opencode", {})


def test_opencode_enabled_true_folds_to_canonical_disabled_false() -> None:
    # opencode's `enabled` is the inverted `disabled`: enabled=true means disabled=false.
    surface = _mcp_surface("opencode")
    text = _file_for(surface, {"github": {"command": "npx", "enabled": True}})

    assert file_to_canonical(text, surface, None).disabled is False


def test_opencode_enabled_false_folds_to_canonical_disabled_true() -> None:
    surface = _mcp_surface("opencode")
    text = _file_for(surface, {"github": {"command": "npx", "enabled": False}})

    assert file_to_canonical(text, surface, None).disabled is True


# --- render: fresh projection emits opencode's native wire ----------------------------


def test_fresh_projection_to_opencode_emits_environment() -> None:
    # the env value carries a canonical env-reference; opencode emits it in its `{env:NAME}` style.
    slot = _rendered_slot(_stdio(env={"GH": "${env:TOKEN}"}), _mcp_surface("opencode"))

    assert slot["environment"] == {"GH": "{env:TOKEN}"}
    assert "env" not in slot


def test_fresh_projection_to_opencode_emits_inverted_enabled() -> None:
    slot = _rendered_slot(_stdio(disabled=True), _mcp_surface("opencode"))

    assert slot["enabled"] is False
    assert "disabled" not in slot


def test_fresh_projection_to_opencode_emits_array_command() -> None:
    slot = _rendered_slot(_stdio(), _mcp_surface("opencode"))

    assert slot["command"] == ["npx", "-y", "gh-mcp"]
    assert "args" not in slot


def test_fresh_projection_to_opencode_emits_type_local_for_stdio() -> None:
    slot = _rendered_slot(_stdio(), _mcp_surface("opencode"))

    assert slot["type"] == "local"
    assert "transport" not in slot


def test_fresh_projection_to_opencode_emits_type_remote_for_http() -> None:
    canonical = CanonicalDocument(
        artifact_id=_EMBEDDED_ID, kind="mcp_server", name="github",
        transport="http", url="https://mcp.example.com",
    )
    slot = _rendered_slot(canonical, _mcp_surface("opencode"))

    assert slot["type"] == "remote"


def test_fresh_projection_to_opencode_emits_oauth_auth() -> None:
    canonical = CanonicalDocument(
        artifact_id=_EMBEDDED_ID, kind="mcp_server", name="github",
        transport="http", url="https://mcp.example.com", auth={"token": "x"},
    )
    slot = _rendered_slot(canonical, _mcp_surface("opencode"))

    assert slot["oauth"] == {"token": "x"}
    assert "auth" not in slot


# --- integration ----------------------------------------------------------------------


def test_an_opencode_native_stdio_slot_round_trips_stably() -> None:
    # parse -> render -> parse is identical: no opencode field drifts on a sync cycle.
    surface = _mcp_surface("opencode")
    text = _file_for(
        surface,
        {
            "github": {
                "pair_id": _EMBEDDED_ID,
                "name": "github",
                "type": "local",
                "command": ["npx", "-y", "gh-mcp"],
                "environment": {"GH": "${TOKEN}"},
                "enabled": True,
            }
        },
    )

    once = file_to_canonical(text, surface, None)
    twice = file_to_canonical(canonical_to_file(once, surface, text), surface, None)

    assert once == twice


def test_env_propagates_from_cursor_to_opencode() -> None:
    # Cross-tool env-MAP propagation: a plain env map set on cursor reaches opencode under
    # opencode's `environment` spelling. (The env-REFERENCE restyle is covered separately in
    # test_mcp_env_reference_style.py; this value is plain, so no restyle is exercised here.)
    cursor = _mcp_surface("cursor")
    cursor_text = _file_for(cursor, {"github": {"command": "npx", "env": {"K": "v"}}})

    canonical = file_to_canonical(cursor_text, cursor, None)
    opencode_slot = _rendered_slot(canonical, _mcp_surface("opencode"))

    assert opencode_slot["environment"] == {"K": "v"}
