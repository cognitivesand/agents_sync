"""Unit coverage for SharedKeyedMapLayout and the format registry.

The Phase 1 deliverables of the v0.5 mcp_server implementation plan are
(a) a layout class describing slot-inside-shared-file storage and (b) a
pluggable format registry. The layout itself has no IO behaviour — it
just declares the shape. Integration coverage (discovery, render,
archive) lives in test_mcp_server_sync.py.
"""
from __future__ import annotations

import json
import tomllib

import pytest

from agents_sync.agentic_tool_spec import SharedKeyedMapLayout
from agents_sync.shared_keyed_map_formats import (
    SharedKeyedMapFormat,
    get_format,
    register_format,
)
from agents_sync.shared_keyed_map_io import apply_slot, read_slots


def test_layout_reports_shared_keyed_map_storage():
    layout = SharedKeyedMapLayout(
        shared_path_config_key="mcp_servers_file",
        map_key_path=("mcpServers",),
    )

    assert layout.storage == "shared_keyed_map"
    assert layout.file_suffix == ".json"
    assert layout.fixed_file_name is None
    assert layout.key_field == "name"
    assert layout.file_format == "json"


def test_json_format_roundtrips_minimal_mcp_file():
    text = '{"mcpServers": {"github": {"command": "gh-mcp"}}}'

    fmt = get_format("json")
    obj = fmt.deserialize(text)
    again = fmt.deserialize(fmt.serialize(obj))

    assert again == obj
    assert obj["mcpServers"]["github"]["command"] == "gh-mcp"


def test_json_format_tolerates_utf8_bom():
    fmt = get_format("json")
    obj = fmt.deserialize('\ufeff{"mcpServers": {"github": {"command": "gh-mcp"}}}')

    assert obj["mcpServers"]["github"]["command"] == "gh-mcp"


def test_json_format_handles_empty_text_as_empty_mapping():
    """First-boot before any MCP slot exists: the shared file may be empty
    or whitespace-only. The handler must not crash."""
    fmt = get_format("json")

    assert fmt.deserialize("") == {}
    assert fmt.deserialize("   \n  ") == {}


def test_json_format_rejects_non_object_root():
    """``mcp.json`` files are always objects at the root. A JSON array or
    scalar at the root is a user mistake the engine must surface, not
    silently overwrite."""
    fmt = get_format("json")

    with pytest.raises(ValueError, match="must be a JSON object"):
        fmt.deserialize("[]")


def test_unknown_format_name_raises_with_known_list():
    with pytest.raises(KeyError, match="known formats:"):
        get_format("ron")


def test_register_format_is_idempotent_under_replacement():
    """Re-registering replaces; adapter PRs can override registrations in
    test fixtures without leaking state across tests if they restore the
    default."""
    sentinel = SharedKeyedMapFormat(
        extension=".test",
        deserialize=lambda text: {},
        serialize=lambda obj: "",
    )
    original = get_format("json")
    try:
        register_format("json", sentinel)
        assert get_format("json") is sentinel
    finally:
        register_format("json", original)
    assert get_format("json") is original


def test_json_serialize_trailing_newline_for_unix_friendliness():
    """Editors append trailing newlines; matching that avoids spurious
    diffs when the user opens and saves the file by hand."""
    fmt = get_format("json")
    text = fmt.serialize({"mcpServers": {}})

    assert text.endswith("\n")
    assert json.loads(text) == {"mcpServers": {}}


def test_toml_format_rejects_json_text():
    fmt = get_format("toml")

    with pytest.raises(tomllib.TOMLDecodeError):
        fmt.deserialize('{"mcp_servers": {"github": {"command": "gh-mcp"}}}')


def test_toml_format_roundtrips_valid_toml():
    fmt = get_format("toml")
    obj = {
        "mcp_servers": {
            "github": {
                "command": "gh-mcp",
                "args": ["serve"],
            },
        },
    }

    assert fmt.deserialize(fmt.serialize(obj)) == obj


def test_read_slots_injects_missing_key_field_from_slot_key(tmp_path):
    layout = SharedKeyedMapLayout(
        shared_path_config_key="mcp_servers_file",
        map_key_path=("mcpServers",),
        key_field="name",
    )
    shared_file = tmp_path / "mcp.json"
    shared_file.write_text(json.dumps({
        "mcpServers": {
            "github": {"command": "gh-mcp"},
        },
    }), encoding="utf-8")

    slots, absent_reason = read_slots(shared_file, layout)

    assert absent_reason is None
    assert json.loads(slots["github"])["name"] == "github"


def test_read_slots_rejects_conflicting_inline_key_field(tmp_path):
    layout = SharedKeyedMapLayout(
        shared_path_config_key="mcp_servers_file",
        map_key_path=("mcpServers",),
        key_field="name",
    )
    shared_file = tmp_path / "mcp.json"
    shared_file.write_text(json.dumps({
        "mcpServers": {
            "github": {"name": "other", "command": "gh-mcp"},
        },
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="slot key conflict"):
        read_slots(shared_file, layout)


def test_apply_slot_serializes_concurrent_writers(tmp_path):
    """Two threads writing the same slot must produce a valid final file:
    no interleaved bytes, no lost final slot — the second writer wins as
    seen from the file system, but both writes were observed by readers."""
    import threading

    layout = SharedKeyedMapLayout(
        shared_path_config_key="mcp_servers_file",
        map_key_path=("mcpServers",),
    )
    shared_file = tmp_path / "mcp.json"
    shared_file.write_text(json.dumps({"mcpServers": {}}, indent=2) + "\n")
    barrier = threading.Barrier(2)
    iterations = 20

    def writer(slot_key: str, command: str) -> None:
        barrier.wait()
        for _ in range(iterations):
            apply_slot(
                shared_file,
                layout,
                slot_key,
                json.dumps({"name": slot_key, "command": command}),
            )

    threads = [
        threading.Thread(target=writer, args=("a", "cmd-a")),
        threading.Thread(target=writer, args=("b", "cmd-b")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = json.loads(shared_file.read_text(encoding="utf-8"))
    # Both slots survive every interleaving the lock allows.
    assert set(final["mcpServers"].keys()) == {"a", "b"}
    assert final["mcpServers"]["a"]["command"] == "cmd-a"
    assert final["mcpServers"]["b"]["command"] == "cmd-b"


def test_apply_slot_refuses_non_object_map_key_path_without_rewriting(tmp_path):
    layout = SharedKeyedMapLayout(
        shared_path_config_key="mcp_servers_file",
        map_key_path=("mcpServers",),
    )
    shared_file = tmp_path / "mcp.json"
    original_text = json.dumps({
        "mcpServers": "disabled",
        "theme": "dark",
    }, indent=2) + "\n"
    shared_file.write_text(original_text, encoding="utf-8")

    with pytest.raises(ValueError, match="not an object"):
        apply_slot(
            shared_file,
            layout,
            "github",
            json.dumps({"name": "github", "command": "gh-mcp"}),
        )

    assert shared_file.read_text(encoding="utf-8") == original_text
