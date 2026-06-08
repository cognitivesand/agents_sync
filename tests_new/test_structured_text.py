"""Unit tests for the shared structured-text codec (rebuild S11a).

``deserialize`` / ``serialize`` are the one place a structured-text wire format
(``json`` or ``toml``) is read and written; the keyed-map dialect (and the S11b
whole-file dialect) call them instead of carrying their own codec. Round-trip
preserves key order and data — comments are NOT preserved (matching current
behaviour; stdlib only, no new dependency). A malformed document raises
``MalformedSurfaceError`` (content error); an unsupported format raises a plain
``ValueError`` (recipe error). Pure in-memory tests.
"""

from __future__ import annotations

import pytest

from agents_sync.dialects import MalformedSurfaceError
from agents_sync.dialects.structured_text import deserialize, serialize


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
