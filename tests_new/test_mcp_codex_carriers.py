"""codex's mcp http auth carriers, data-driven (rebuild S20 increment 5; FR-09, NFR-16, NFR-11/18).

codex spells HTTP authentication across three dedicated carrier fields instead of a generic
``headers``/``auth`` block: ``http_headers`` (literal header values), ``env_http_headers``
(header name → env var NAME), and ``bearer_token_env_var`` (one env var NAME → an
``Authorization: Bearer`` header). This increment folds all three onto the canonical
``headers`` map — using the FIXED canonical ``${env:NAME}`` env-reference representation — so
they actually sync instead of stranding in ``per_tool_extra`` (the correctness win, mirroring
opencode's ``environment``/``enabled`` in increment 3). The per-tool inline env-reference
*style* (``${env:NAME}``↔``${NAME}``↔``{env:NAME}``) is increment 7, NOT here. codex has no
generic auth block, so a canonical ``auth`` map is suppressed on render.

The carrier spellings live as a ``McpSpellingRecipe`` in codex's tool module and are consumed
generically by the dialect (no tool-name branches); the tests drive codex's REAL recipe
through the registry, so they prove the data wiring end-to-end.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from agents_sync.dialects import MalformedSurfaceError, structured_text
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import KeyedMapSlot, ToolSurface
from agents_sync.tools.agentic_tools_registry import tool_definition
from agents_sync.translation import canonical_to_file, file_to_canonical

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
_URL = "https://mcp.figma.com/mcp"


def _mcp_surface(tool: str = "codex", slot: str = "figma") -> ToolSurface:
    """codex's REAL mcp_server recipe as a ToolSurface (drives the data, not a stub)."""
    [recipe] = [r for r in tool_definition(tool).surface_recipes if r.kind == "mcp_server"]
    location = KeyedMapSlot(file=Path(f"/u/{tool}.toml"), slot=slot)
    return ToolSurface(tool, "mcp_server", location, recipe.surface_format)


def _codex_file(surface: ToolSurface, slots: dict[str, Any]) -> str:
    """A codex config file (TOML) keyed by the recipe's own map_key_path."""
    return structured_text.serialize({surface.surface_format.map_key_path[0]: slots}, "toml")


def _rendered_slot(
    canonical: CanonicalDocument,
    surface: ToolSurface,
    prior: str | None = None,
    slot: str = "figma",
) -> dict[str, Any]:
    text = canonical_to_file(canonical, surface, prior)
    return tomllib.loads(text)[surface.surface_format.map_key_path[0]][slot]


def _http(**fields: Any) -> CanonicalDocument:
    return CanonicalDocument(
        artifact_id=_ARTIFACT_ID, kind="mcp_server", name="figma",
        transport="http", url=_URL, **fields
    )


# --- parse: codex's carriers reach the canonical headers map --------------------------


def test_codex_http_headers_fold_to_canonical_headers() -> None:
    surface = _mcp_surface()
    text = _codex_file(surface, {"figma": {"url": _URL, "http_headers": {"X-Region": "us-east-1"}}})

    assert file_to_canonical(text, surface, None).headers == {"X-Region": "us-east-1"}


def test_codex_env_http_headers_folds_to_a_canonical_env_reference() -> None:
    # the carrier holds a header name → env var NAME; it folds to the canonical ${env:NAME} ref.
    surface = _mcp_surface()
    slots = {"figma": {"url": _URL, "env_http_headers": {"X-Trace": "TRACE_TOKEN"}}}
    text = _codex_file(surface, slots)

    assert file_to_canonical(text, surface, None).headers == {"X-Trace": "${env:TRACE_TOKEN}"}


def test_codex_bearer_token_env_var_folds_to_an_authorization_header() -> None:
    surface = _mcp_surface()
    text = _codex_file(surface, {"figma": {"url": _URL, "bearer_token_env_var": "FIGMA_TOKEN"}})

    assert file_to_canonical(text, surface, None).headers == {
        "Authorization": "Bearer ${env:FIGMA_TOKEN}"
    }


def test_the_generic_headers_spelling_folds_on_parse() -> None:
    # `headers` is the canonical-default spelling (shared by every tool), folded for any
    # dialect; codex's distinct carrier spelling `http_headers` is covered above. This pins
    # the generic `headers` fold, not anything codex-specific.
    surface = _mcp_surface()
    text = _codex_file(surface, {"figma": {"url": _URL, "headers": {"X-Region": "eu"}}})

    assert file_to_canonical(text, surface, None).headers == {"X-Region": "eu"}


def test_no_codex_carrier_strands_in_per_tool_extra() -> None:
    # the correctness win: every carrier is owned by the dialect, none leaks back unsynced.
    surface = _mcp_surface()
    text = _codex_file(
        surface,
        {"figma": {
            "url": _URL,
            "http_headers": {"X-Region": "us-east-1"},
            "env_http_headers": {"X-Trace": "TRACE_TOKEN"},
            "bearer_token_env_var": "FIGMA_TOKEN",
        }},
    )

    extra = file_to_canonical(text, surface, None).per_tool_extra.get("codex", {})

    assert "http_headers" not in extra
    assert "env_http_headers" not in extra
    assert "bearer_token_env_var" not in extra


# --- render: a fresh projection splits canonical headers into codex's carriers ---------


def test_fresh_projection_emits_literal_headers_under_http_headers() -> None:
    slot = _rendered_slot(_http(headers={"X-Region": "us-east-1"}), _mcp_surface())

    assert slot["http_headers"] == {"X-Region": "us-east-1"}
    assert "headers" not in slot


def test_fresh_projection_lifts_an_env_reference_header_into_env_http_headers() -> None:
    slot = _rendered_slot(_http(headers={"X-Trace": "${env:TRACE_TOKEN}"}), _mcp_surface())

    assert slot["env_http_headers"] == {"X-Trace": "TRACE_TOKEN"}
    assert "http_headers" not in slot  # the only header was an env reference


def test_fresh_projection_lifts_a_bearer_authorization_into_bearer_token_env_var() -> None:
    slot = _rendered_slot(
        _http(headers={"Authorization": "Bearer ${env:FIGMA_TOKEN}"}), _mcp_surface()
    )

    assert slot["bearer_token_env_var"] == "FIGMA_TOKEN"
    assert "http_headers" not in slot
    assert "env_http_headers" not in slot


def test_fresh_projection_suppresses_a_generic_auth_block() -> None:
    # codex has no oauth/auth field; a canonical auth map is not emitted as a generic block.
    slot = _rendered_slot(_http(auth={"type": "oauth"}), _mcp_surface())

    assert "auth" not in slot
    assert "oauth" not in slot


def test_fresh_projection_splits_mixed_headers_across_the_three_carriers() -> None:
    slot = _rendered_slot(
        _http(headers={
            "Authorization": "Bearer ${env:FIGMA_TOKEN}",
            "X-Trace": "${env:TRACE_TOKEN}",
            "X-Region": "us-east-1",
        }),
        _mcp_surface(),
    )

    assert slot["bearer_token_env_var"] == "FIGMA_TOKEN"
    assert slot["env_http_headers"] == {"X-Trace": "TRACE_TOKEN"}
    assert slot["http_headers"] == {"X-Region": "us-east-1"}


# --- integration ----------------------------------------------------------------------


def test_codex_carriers_round_trip_through_the_canonical_headers_without_drift() -> None:
    # parse -> render -> parse preserves the folded headers exactly, and no carrier strands:
    # all three carriers survive a sync cycle. (Transport field spelling is increment 6.)
    surface = _mcp_surface()
    text = _codex_file(
        surface,
        {"figma": {
            "pair_id": _ARTIFACT_ID,
            "url": _URL,
            "http_headers": {"X-Region": "us-east-1"},
            "env_http_headers": {"X-Trace": "TRACE_TOKEN"},
            "bearer_token_env_var": "FIGMA_TOKEN",
        }},
    )
    expected_headers = {
        "X-Region": "us-east-1",
        "X-Trace": "${env:TRACE_TOKEN}",
        "Authorization": "Bearer ${env:FIGMA_TOKEN}",
    }

    once = file_to_canonical(text, surface, None)
    twice = file_to_canonical(canonical_to_file(once, surface, text), surface, None)

    assert once.headers == expected_headers
    assert twice.headers == expected_headers
    assert twice.per_tool_extra.get("codex", {}) == {}


def test_a_canonical_bearer_header_reaches_the_codex_bearer_carrier() -> None:
    # the sync payoff: an Authorization bearer carried on the canonical headers map (e.g. set
    # by another tool) projects to codex's dedicated carrier, not a literal http_headers entry.
    canonical = _http(headers={"Authorization": "Bearer ${env:SHARED_TOKEN}", "X-Region": "eu"})

    slot = _rendered_slot(canonical, _mcp_surface())

    assert slot["bearer_token_env_var"] == "SHARED_TOKEN"
    assert slot["http_headers"] == {"X-Region": "eu"}
    assert "env_http_headers" not in slot


def test_a_stdio_slot_declaring_an_http_carrier_is_malformed() -> None:
    # the carriers are http-only; a stdio slot carrying one describes two servers at once.
    surface = _mcp_surface()
    text = _codex_file(surface, {"figma": {"command": "npx", "bearer_token_env_var": "TOK"}})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, surface, None)


def test_a_carrier_holding_an_invalid_env_var_name_is_malformed() -> None:
    # a carrier value becomes a ${env:NAME} reference, so it must be a valid env var name;
    # a non-conforming value is malformed content, not a silently-mangled reference (§8).
    surface = _mcp_surface()
    text = _codex_file(surface, {"figma": {"url": _URL, "env_http_headers": {"X": "not a name"}}})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, surface, None)
