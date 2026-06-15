"""Transport-field-less mcp tools, data-driven (rebuild S20 increment 6; FR-09, NFR-16, NFR-11/18).

Some tools carry no explicit transport field. gemini encodes the transport in the url-field
SPELLING — ``httpUrl`` means http, ``url`` means sse — and renders it back the same way; codex
infers the transport from ``command``/``url`` presence. Both also omit an inner ``name`` (the
slot key is the name). These behaviours are ``McpSpellingRecipe`` DATA (``transport_by_url_field``
/ ``url_field_by_transport`` and the optional ``transport_render_field`` / ``name_render_field``)
consumed generically by the dialect — no tool-name branches. Suppressing codex's transport field
also closes the increment-5 ``per_tool_only`` transport drift on a sync cycle.

The tests drive each tool's REAL recipe through the registry, so they prove the data wiring
end-to-end across both wire formats (gemini JSON, codex TOML).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agents_sync.dialects import structured_text
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import KeyedMapSlot, ToolSurface
from agents_sync.tools.agentic_tools_registry import tool_definition
from agents_sync.translation import canonical_to_file, file_to_canonical

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
_URL = "https://mcp.example.com"


def _mcp_surface(tool: str, slot: str = "github") -> ToolSurface:
    """The tool's REAL mcp_server recipe as a ToolSurface (drives the data, not a stub)."""
    [recipe] = [r for r in tool_definition(tool).surface_recipes if r.kind == "mcp_server"]
    location = KeyedMapSlot(file=Path(f"/u/{tool}.cfg"), slot=slot)
    return ToolSurface(tool, "mcp_server", location, recipe.surface_format)


def _file_for(surface: ToolSurface, slots: dict[str, Any]) -> str:
    """A shared config file for ``surface`` in its own wire format (gemini JSON, codex TOML)."""
    fmt = surface.surface_format
    return structured_text.serialize({fmt.map_key_path[0]: slots}, fmt.file_format)


def _rendered_slot(
    canonical: CanonicalDocument,
    surface: ToolSurface,
    prior: str | None = None,
    slot: str = "github",
) -> dict[str, Any]:
    fmt = surface.surface_format
    text = canonical_to_file(canonical, surface, prior)
    return structured_text.deserialize(text, fmt.file_format)[fmt.map_key_path[0]][slot]


def _http(transport: str, **fields: Any) -> CanonicalDocument:
    return CanonicalDocument(
        artifact_id=_ARTIFACT_ID, kind="mcp_server", name="github",
        transport=transport, url=_URL, **fields
    )


# --- gemini: the url-field spelling encodes the transport -----------------------------


def test_gemini_httpurl_folds_to_http_transport() -> None:
    surface = _mcp_surface("gemini_cli")
    text = _file_for(surface, {"github": {"httpUrl": _URL}})

    assert file_to_canonical(text, surface, None).transport == "http"


def test_gemini_url_folds_to_sse_transport() -> None:
    # `url` (not `httpUrl`) is gemini's sse spelling — the canonical default would infer http.
    surface = _mcp_surface("gemini_cli")
    text = _file_for(surface, {"github": {"url": _URL}})

    assert file_to_canonical(text, surface, None).transport == "sse"


def test_fresh_http_projection_to_gemini_emits_httpurl() -> None:
    slot = _rendered_slot(_http("http"), _mcp_surface("gemini_cli"))

    assert slot["httpUrl"] == _URL
    assert "url" not in slot


def test_fresh_sse_projection_to_gemini_emits_url() -> None:
    slot = _rendered_slot(_http("sse"), _mcp_surface("gemini_cli"))

    assert slot["url"] == _URL
    assert "httpUrl" not in slot


def test_fresh_streamable_http_projection_to_gemini_emits_httpurl() -> None:
    # gemini's wire cannot distinguish streamable-http from http; both render httpUrl.
    slot = _rendered_slot(_http("streamable-http"), _mcp_surface("gemini_cli"))

    assert slot["httpUrl"] == _URL


# --- gemini + codex: no explicit transport field, no inner name -----------------------


@pytest.mark.parametrize("tool", ("gemini_cli", "codex"))
def test_a_transport_field_less_tool_omits_the_transport_field(tool: str) -> None:
    slot = _rendered_slot(_http("http"), _mcp_surface(tool))

    assert "transport" not in slot
    assert "type" not in slot
    assert "transportType" not in slot


@pytest.mark.parametrize("tool", ("gemini_cli", "codex"))
def test_a_transport_field_less_tool_omits_the_inner_name(tool: str) -> None:
    # the slot key is the server name, so a redundant inner `name` is not emitted.
    slot = _rendered_slot(_http("http"), _mcp_surface(tool))

    assert "name" not in slot


# --- round-trips ----------------------------------------------------------------------


def test_a_gemini_native_http_slot_round_trips_stably() -> None:
    surface = _mcp_surface("gemini_cli")
    text = _file_for(surface, {"github": {"pair_id": _ARTIFACT_ID, "httpUrl": _URL}})

    once = file_to_canonical(text, surface, None)
    twice = file_to_canonical(canonical_to_file(once, surface, text), surface, None)

    assert once == twice
    assert once.transport == "http"


def test_a_codex_stdio_slot_round_trips_without_transport_drift() -> None:
    # increment 5 left codex emitting a transport field that re-parse then recorded in
    # per_tool_only; suppressing it makes a transport-inferred codex slot byte-stable.
    surface = _mcp_surface("codex")
    text = _file_for(
        surface, {"github": {"pair_id": _ARTIFACT_ID, "command": "npx", "args": ["-y", "gh"]}}
    )

    once = file_to_canonical(text, surface, None)
    twice = file_to_canonical(canonical_to_file(once, surface, text), surface, None)

    assert once == twice
    assert once.transport == "stdio"
