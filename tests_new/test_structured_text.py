"""Unit tests for the structured-text module — codec (S11a) and dialect (S11b).

The codec (``deserialize`` / ``serialize``) is the one place a structured-text wire
format (``json`` or ``toml``) is read and written; the keyed-map dialect and this
module's own whole-file dialect call it. Round-trip preserves key order and data —
comments are NOT preserved (matching current behaviour; stdlib only, no new
dependency). A malformed document raises ``MalformedSurfaceError`` (content error);
an unsupported format raises a plain ``ValueError`` (recipe error).

The whole-file dialect (``parse`` / ``render`` / ``extract_id``, exercised here
through the translation seam) treats the entire file as one field map: codex's
whole-``.toml`` agent, whose body lives under a named field (``developer_instructions``)
expressed via the recipe's ``known_fields``. Pure in-memory tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.dialects import MalformedSurfaceError
from agents_sync.dialects.structured_text import deserialize, serialize
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import SurfaceFormat, ToolSurface
from agents_sync.translation import (
    canonical_to_file,
    extract_artifact_id,
    file_to_canonical,
)

# A codex-agent-shaped whole-file recipe: the body lives under ``developer_instructions``,
# expressed as a known_fields pair so it folds through the shared recipe-application with
# no special-casing. ``sandbox_mode`` is tool-only; anything else lands in per_tool_extra.
_AGENT = SurfaceFormat(
    dialect="structured_text",
    id_field="pair_id",
    known_fields=(
        ("name", "name"),
        ("model", "model"),
        ("developer_instructions", "body"),
    ),
    tool_only_fields=("sandbox_mode",),
    file_format="toml",
)
_AGENT_ID = "11111111-1111-4111-8111-111111111111"


def _agent_surface(kind: str = "agent", file_format: str = "toml") -> ToolSurface:
    recipe = _AGENT if file_format == "toml" else SurfaceFormat(
        dialect="structured_text",
        id_field=_AGENT.id_field,
        known_fields=_AGENT.known_fields,
        tool_only_fields=_AGENT.tool_only_fields,
        file_format=file_format,
    )
    suffix = "toml" if file_format == "toml" else "json"
    return ToolSurface(
        tool="codex",
        kind=kind,
        location=Path(f"/u/.codex/agents/reviewer.{suffix}"),
        surface_format=recipe,
    )


def _agent_canonical(**overrides: object) -> CanonicalDocument:
    defaults: dict[str, object] = {
        "artifact_id": _AGENT_ID,
        "kind": "agent",
        "name": "reviewer",
        "model": "gpt-5",
        "body": "Do the review.",
        "per_tool_only": {"codex": {"sandbox_mode": "read-only"}},
        "per_tool_extra": {"codex": {"approval_policy": "on-request"}},
    }
    defaults.update(overrides)
    return CanonicalDocument(**defaults)  # type: ignore[arg-type]


def test_json_round_trips_data_and_key_order() -> None:
    data = {"beta": 1, "alpha": {"inner_y": [1, 2], "inner_x": "v"}, "gamma": [3]}

    text = serialize(data, "json")

    assert deserialize(text, "json") == data
    assert text.index('"beta"') < text.index('"alpha"') < text.index('"gamma"')


def test_toml_round_trips_data_and_key_order() -> None:
    data = {"name": "srv", "enabled": True, "settings": {"port": 8080, "tags": ["x", "y"]}}

    text = serialize(data, "toml")

    assert deserialize(text, "toml") == data
    # The writer emits scalars before nested tables, in insertion order.
    assert text.index("name") < text.index("enabled") < text.index("[settings]")


def test_a_nested_toml_table_round_trips() -> None:
    # The shape keyed_map_slot produces: an artifact slot under a nested map path. The
    # keys are inserted in NON-alphabetical order (pair_id before command) so that
    # insertion order differs from sorted order — a within-table sort regression would
    # then reorder them and fail the assertion below.
    data = {"mcp_servers": {"github": {"pair_id": "id-1", "command": "gh-mcp"}}}

    text = serialize(data, "toml")

    assert deserialize(text, "toml") == data
    assert text.index("pair_id") < text.index("command")  # in-table insertion order kept


def test_a_float_value_round_trips_through_toml() -> None:
    # Exercises the float branch of the scalar emitter; both values are exactly
    # representable in binary float, so structural equality is sound (no tolerance needed).
    data = {"ratio": 1.5, "weight": 0.25}

    assert deserialize(serialize(data, "toml"), "toml") == data


def test_empty_text_deserializes_to_an_empty_mapping() -> None:
    assert deserialize("", "json") == {}
    assert deserialize("   \n", "toml") == {}


def test_malformed_json_raises_malformed_surface_error() -> None:
    with pytest.raises(MalformedSurfaceError):
        deserialize("{not valid json", "json")


def test_malformed_toml_raises_malformed_surface_error() -> None:
    with pytest.raises(MalformedSurfaceError):
        deserialize("[unclosed", "toml")


def test_a_non_object_root_raises_malformed_surface_error() -> None:
    # A structured-config file is expected to be an object/table at the root; a bare
    # array is malformed for our use.
    with pytest.raises(MalformedSurfaceError):
        deserialize("[1, 2]", "json")


def test_an_unsupported_format_fails_loud_not_as_malformed() -> None:
    # An unimplemented format is a recipe error, not a content error: a plain
    # ValueError, never a MalformedSurfaceError (which subclasses ValueError).
    with pytest.raises(ValueError, match="yaml") as read_error:
        deserialize("{}", "yaml")
    assert not isinstance(read_error.value, MalformedSurfaceError)

    with pytest.raises(ValueError, match="yaml") as write_error:
        serialize({}, "yaml")
    assert not isinstance(write_error.value, MalformedSurfaceError)


# --- the whole-file dialect (parse / render / extract_id via the translation seam) ---


def test_render_then_parse_returns_an_equal_canonical() -> None:
    canonical = _agent_canonical()

    text = canonical_to_file(canonical, _agent_surface(), None)
    folded = file_to_canonical(text, _agent_surface(), None)

    assert folded == canonical


def test_the_body_maps_to_its_recipe_field_and_round_trips() -> None:
    # codex's body lives under `developer_instructions`; the recipe folds it to/from
    # canonical.body with no special-casing in the dialect.
    canonical = _agent_canonical(body="Line one.\nLine two.")

    text = canonical_to_file(canonical, _agent_surface(), None)

    assert "developer_instructions" in text
    assert file_to_canonical(text, _agent_surface(), None).body == "Line one.\nLine two."


def test_an_empty_body_omits_the_body_field_and_round_trips() -> None:
    # An empty body is the distinct "drop the field" path: developer_instructions is not
    # emitted, and parsing the field's absence keeps the default empty body.
    canonical = _agent_canonical(body="")

    text = canonical_to_file(canonical, _agent_surface(), None)

    assert "developer_instructions" not in text
    assert file_to_canonical(text, _agent_surface(), None) == canonical


def test_an_unknown_top_level_key_is_kept_in_per_tool_extra() -> None:
    # No-foreign-leak (NFR-06/16): a top-level key the recipe does not own is kept under
    # the tool's extra bag, not dropped or folded into a known field.
    text = serialize({"pair_id": _AGENT_ID, "name": "reviewer", "weird_key": 7}, "toml")

    canonical = file_to_canonical(text, _agent_surface(), None)

    assert canonical.per_tool_extra["codex"]["weird_key"] == 7
    assert "weird_key" in canonical_to_file(canonical, _agent_surface(), None)


def test_a_tool_only_field_is_kept_under_per_tool_only() -> None:
    text = serialize({"pair_id": _AGENT_ID, "name": "reviewer", "sandbox_mode": "ro"}, "toml")

    canonical = file_to_canonical(text, _agent_surface(), None)

    assert canonical.per_tool_only["codex"]["sandbox_mode"] == "ro"


def test_kind_is_stamped_from_the_surface() -> None:
    text = serialize({"pair_id": _AGENT_ID, "name": "reviewer"}, "toml")

    assert file_to_canonical(text, _agent_surface(kind="custom"), None).kind == "custom"


def test_an_id_less_file_with_no_prior_is_not_minted() -> None:
    text = serialize({"name": "reviewer"}, "toml")

    assert file_to_canonical(text, _agent_surface(), None).artifact_id == ""


def test_an_embedded_id_is_carried_through() -> None:
    text = serialize({"pair_id": _AGENT_ID, "name": "reviewer"}, "toml")

    assert file_to_canonical(text, _agent_surface(), None).artifact_id == _AGENT_ID


def test_a_malformed_file_raises() -> None:
    with pytest.raises(MalformedSurfaceError):
        file_to_canonical("[unclosed", _agent_surface(), None)


def test_extract_id_reads_the_id_and_never_raises() -> None:
    with_id = serialize({"pair_id": _AGENT_ID, "name": "reviewer"}, "toml")
    without_id = serialize({"name": "reviewer"}, "toml")

    assert extract_artifact_id(with_id, _agent_surface()) == _AGENT_ID
    assert extract_artifact_id("[unclosed", _agent_surface()) is None  # malformed: None, not raise
    assert extract_artifact_id(without_id, _agent_surface()) is None  # present file, no id


def test_the_dialect_is_format_agnostic_via_the_recipe() -> None:
    # The same dialect serves a JSON whole-file artifact — only the recipe's file_format
    # differs; the round-trip holds identically.
    canonical = _agent_canonical()
    json_surface = _agent_surface(file_format="json")

    folded = file_to_canonical(canonical_to_file(canonical, json_surface, None), json_surface, None)

    assert folded == canonical


def test_the_json_format_also_raises_on_malformed_and_never_mints() -> None:
    # The JSON and TOML codecs are different stdlib parsers; the malformed→raise and
    # id-less→no-mint contracts must hold for JSON too, not only TOML.
    json_surface = _agent_surface(file_format="json")

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical("{not valid json", json_surface, None)

    id_less = serialize({"name": "reviewer"}, "json")
    assert file_to_canonical(id_less, json_surface, None).artifact_id == ""
