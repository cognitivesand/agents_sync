"""Unit tests for the keyed-map-slot dialect (rebuild S10).

One artifact stored as a single slot inside a shared keyed-map file (MCP servers):
the dialect navigates the recipe's ``map_key_path`` to the slot-map, folds the one
slot named by ``location.slot``, and on render reassembles the whole file untouched
but for that slot (sibling preservation). It shares the recipe-application
(``field_mapping``) with the markdown dialect, so the fold/project contract
(no-foreign-leak NFR-06/16, never-mint FR-11, kind from the surface) is the same;
only the wire extract/reassemble differs. S10 supports the JSON ``file_format``;
TOML/JSONC arrive with the structured-text codec at S11. Pure in-memory tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import KeyedMapSlot, SurfaceFormat, ToolSurface
from agents_sync.translation import (
    MalformedSurfaceError,
    canonical_to_file,
    extract_artifact_id,
    file_to_canonical,
)

# A representative keyed-map recipe (claude/cursor-shaped mcp): a slot is a flat
# field map at ``mcpServers.<slot>``. ``description`` folds to the canonical
# attribute; ``command``/``args`` are tool-only (kept under per_tool_only[tool]);
# anything else lands in per_tool_extra[tool].
_KEYED = SurfaceFormat(
    dialect="keyed_map_slot",
    id_field="pair_id",
    known_fields=(("description", "description"),),
    tool_only_fields=("command", "args"),
    map_key_path=("mcpServers",),
    file_format="json",
)
_EMBEDDED_ID = "11111111-1111-4111-8111-111111111111"
_PRIOR_ID = "22222222-2222-4222-8222-222222222222"


def _surface(slot: str = "github", tool: str = "cursor", kind: str = "mcp_server") -> ToolSurface:
    return ToolSurface(
        tool=tool,
        kind=kind,
        location=KeyedMapSlot(file=Path(f"/u/.{tool}/mcp.json"), slot=slot),
        surface_format=_KEYED,
    )


def _canonical(**overrides: object) -> CanonicalDocument:
    defaults: dict[str, object] = {
        "artifact_id": _EMBEDDED_ID,
        "kind": "mcp_server",
        "description": "GitHub MCP server",
        "per_tool_only": {"cursor": {"command": "npx", "args": ["-y", "gh-mcp"]}},
        "per_tool_extra": {"cursor": {"transport": "stdio"}},
    }
    defaults.update(overrides)
    return CanonicalDocument(**defaults)  # type: ignore[arg-type]


def _file(slots: dict[str, object], **top_level: object) -> str:
    return json.dumps({"mcpServers": slots, **top_level})


def test_render_then_parse_returns_an_equal_canonical() -> None:
    canonical = _canonical()

    text = canonical_to_file(canonical, _surface(), None)
    folded = file_to_canonical(text, _surface(), None)

    assert folded == canonical


def test_render_preserves_sibling_slots_and_out_of_map_keys() -> None:
    # The defining keyed-map property: writing one slot must not disturb the other
    # slots in the shared file, nor top-level keys outside the slot-map.
    prior = _file(
        {
            "github": {"pair_id": _EMBEDDED_ID, "description": "old"},
            "gitlab": {"command": "glab", "pair_id": "other-id"},
        },
        **{"$schema": "https://example/mcp.schema.json"},
    )

    rendered = canonical_to_file(_canonical(description="new desc"), _surface(slot="github"), prior)
    root = json.loads(rendered)

    assert root["mcpServers"]["gitlab"] == {"command": "glab", "pair_id": "other-id"}
    assert root["$schema"] == "https://example/mcp.schema.json"
    assert root["mcpServers"]["github"]["description"] == "new desc"


def test_unknown_slot_key_is_preserved_in_per_tool_extra() -> None:
    # No-foreign-leak (NFR-06/16): a slot key the recipe does not own is kept under
    # the tool's extra bag and re-emitted, not dropped or folded into a known field.
    text = _file({"github": {"pair_id": _EMBEDDED_ID, "weirdKey": 7}})

    canonical = file_to_canonical(text, _surface(), None)

    assert canonical.per_tool_extra["cursor"]["weirdKey"] == 7
    rendered = json.loads(canonical_to_file(canonical, _surface(), None))
    assert rendered["mcpServers"]["github"]["weirdKey"] == 7  # re-emitted, not dropped


def test_a_foreign_tools_bag_survives_folding_this_slot() -> None:
    # No-foreign-leak across tools: folding cursor's slot must not disturb the bags the
    # prior canonical holds for other tools.
    prior = _canonical(
        per_tool_only={"codex": {"command": "codex-mcp"}},
        per_tool_extra={"cursor": {"transport": "old"}, "gemini": {"flag": "y"}},
    )
    text = _file({"github": {"pair_id": _EMBEDDED_ID, "transport": "new"}})

    folded = file_to_canonical(text, _surface(tool="cursor"), prior)

    assert folded.per_tool_only["codex"] == {"command": "codex-mcp"}
    assert folded.per_tool_extra["gemini"] == {"flag": "y"}
    assert folded.per_tool_extra["cursor"]["transport"] == "new"


def test_tool_only_field_is_kept_under_per_tool_only() -> None:
    text = _file({"github": {"pair_id": _EMBEDDED_ID, "command": "npx"}})

    canonical = file_to_canonical(text, _surface(), None)

    assert canonical.per_tool_only["cursor"]["command"] == "npx"


def test_kind_is_stamped_from_the_surface() -> None:
    text = _file({"github": {"pair_id": _EMBEDDED_ID}})

    assert file_to_canonical(text, _surface(kind="mcp_server"), None).kind == "mcp_server"


def test_an_id_less_slot_with_no_prior_is_not_minted() -> None:
    text = _file({"github": {"description": "x"}})

    assert file_to_canonical(text, _surface(), None).artifact_id == ""


def test_embedded_id_is_carried_through() -> None:
    text = _file({"github": {"pair_id": _EMBEDDED_ID}})

    assert file_to_canonical(text, _surface(), None).artifact_id == _EMBEDDED_ID


def test_prior_id_is_carried_when_the_slot_omits_one() -> None:
    prior = _canonical(artifact_id=_PRIOR_ID)
    text = _file({"github": {"description": "x"}})

    assert file_to_canonical(text, _surface(), prior).artifact_id == _PRIOR_ID


def test_a_missing_slot_folds_to_defaults() -> None:
    # The shared file exists with a sibling, but our slot is absent: a metadata-less
    # fold (kind from the surface, no id), not an error.
    text = _file({"other": {"pair_id": "z"}})

    canonical = file_to_canonical(text, _surface(slot="github"), None)

    assert canonical.artifact_id == ""
    assert canonical.kind == "mcp_server"
    assert not canonical.per_tool_only  # no stray tool bag created for an absent slot
    assert not canonical.per_tool_extra


def test_a_missing_map_path_folds_to_defaults() -> None:
    canonical = file_to_canonical("{}", _surface(), None)

    assert canonical.artifact_id == ""
    assert not canonical.per_tool_only
    assert not canonical.per_tool_extra


def test_malformed_json_raises() -> None:
    with pytest.raises(MalformedSurfaceError):
        file_to_canonical("{not valid json", _surface(), None)


def test_extract_id_reads_a_well_formed_id() -> None:
    text = _file({"github": {"pair_id": _EMBEDDED_ID}})

    assert extract_artifact_id(text, _surface()) == _EMBEDDED_ID


def test_extract_id_never_raises_and_returns_none_when_unreadable_or_absent() -> None:
    assert extract_artifact_id("{not json", _surface()) is None  # malformed: None, not a raise
    assert extract_artifact_id(_file({"github": {}}), _surface()) is None  # slot present, no id
    assert extract_artifact_id("{}", _surface()) is None  # slot absent


def test_an_unsupported_file_format_fails_loud() -> None:
    # TOML is deferred to the S11 structured-text codec; until then the keyed-map
    # dialect must fail loud on an unimplemented format (a recipe error, not a
    # malformed-content error).
    toml_recipe = SurfaceFormat(
        dialect="keyed_map_slot",
        id_field="pair_id",
        map_key_path=("mcpServers",),
        file_format="toml",
    )
    surface = ToolSurface(
        tool="codex",
        kind="mcp_server",
        location=KeyedMapSlot(file=Path("/u/.codex/config.toml"), slot="github"),
        surface_format=toml_recipe,
    )

    # The distinction matters because MalformedSurfaceError subclasses ValueError: an
    # unimplemented format is a recipe error, NOT a malformed-content error, so it must
    # not masquerade as the latter. extract_id fails loud the same way (not None).
    with pytest.raises(ValueError, match="toml") as parse_error:
        file_to_canonical(_file({"github": {}}), surface, None)
    assert not isinstance(parse_error.value, MalformedSurfaceError)

    with pytest.raises(ValueError, match="toml") as id_error:
        extract_artifact_id(_file({"github": {}}), surface)
    assert not isinstance(id_error.value, MalformedSurfaceError)
