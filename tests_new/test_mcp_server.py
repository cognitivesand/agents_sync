"""Unit tests for the mcp_server dialect — stdio core (rebuild S13a).

An mcp_server artifact is one slot in a shared keyed-map file (like keyed_map_slot),
but its wire shape needs interpretation a flat field map cannot express: transport
canonicalization + an alias map, transport inference (command -> stdio), command/args
(array-form split), env, cwd/timeout, disabled, always_allow, and preservation of each
tool's own field spellings under ``per_tool_only``. http/sse transport and the
url/headers/auth fields are S13c; the mcp secret policy is the read phase (S18).
Pure in-memory tests through the translation seam (FR-09).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agents_sync.domain_model.tool_surface import KeyedMapSlot, SurfaceFormat, ToolSurface
from agents_sync.translation import (
    MalformedSurfaceError,
    canonical_to_file,
    extract_artifact_id,
    file_to_canonical,
)

# A keyed-map recipe for mcp servers: the slot lives at ``mcpServers.<slot>`` in a JSON
# file. The mcp dialect reads its field spellings from its own module constants, so the
# recipe needs only the slot location and the id field.
_MCP = SurfaceFormat(
    dialect="mcp_server",
    id_field="pair_id",
    map_key_path=("mcpServers",),
    file_format="json",
)
_EMBEDDED_ID = "11111111-1111-4111-8111-111111111111"


def _surface(slot: str = "github", tool: str = "cursor") -> ToolSurface:
    return ToolSurface(
        tool=tool,
        kind="mcp_server",
        location=KeyedMapSlot(file=Path(f"/u/.{tool}/mcp.json"), slot=slot),
        surface_format=_MCP,
    )


def _file(slots: dict[str, Any], **top_level: Any) -> str:
    return json.dumps({"mcpServers": slots, **top_level})


def _stdio_slot(**overrides: Any) -> dict[str, Any]:
    slot: dict[str, Any] = {
        "pair_id": _EMBEDDED_ID,
        "name": "github",
        "command": "npx",
        "args": ["-y", "gh-mcp"],
    }
    slot.update(overrides)
    return slot


def test_a_fully_populated_stdio_slot_is_stable_across_parse_render_parse() -> None:
    # The robust round-trip: a parsed canonical re-rendered and re-parsed is identical, so no
    # field (incl. the preserved per-tool spelling) drifts on a sync cycle. The slot is fully
    # populated so the anti-drift claim covers every stdio field, not just command/args.
    text = _file(
        {
            "github": _stdio_slot(
                transport="stdio",
                env={"T": "${X}"},
                cwd="/srv",
                timeout=30,
                disabled=False,
                alwaysAllow=["search", "create"],
            )
        }
    )

    once = file_to_canonical(text, _surface(), None)
    twice = file_to_canonical(canonical_to_file(once, _surface(), text), _surface(), None)

    assert once == twice


def test_command_and_args_are_folded_to_the_canonical() -> None:
    canonical = file_to_canonical(_file({"github": _stdio_slot()}), _surface(), None)

    assert canonical.command == "npx"
    assert canonical.args == ("-y", "gh-mcp")


def test_a_command_array_splits_into_command_and_args() -> None:
    # Some tools spell the invocation as a single array; it folds to command + args.
    text = _file({"github": {"name": "x", "command": ["npx", "-y", "gh-mcp"]}})

    canonical = file_to_canonical(text, _surface(), None)

    assert canonical.command == "npx"
    assert canonical.args == ("-y", "gh-mcp")


def test_transport_alias_local_canonicalises_to_stdio() -> None:
    text = _file({"github": _stdio_slot(transport="local")})

    assert file_to_canonical(text, _surface(), None).transport == "stdio"


def test_transport_is_inferred_from_command_when_no_transport_field() -> None:
    text = _file({"github": {"name": "x", "command": "npx"}})

    assert file_to_canonical(text, _surface(), None).transport == "stdio"


def test_the_transport_type_field_spelling_is_recognised_and_preserved() -> None:
    # transportType is the third accepted transport spelling: it canonicalises like the others
    # and re-emits under its own key on render.
    text = _file({"github": _stdio_slot(transportType="local")})

    canonical = file_to_canonical(text, _surface(), None)
    slot = json.loads(canonical_to_file(canonical, _surface(), text))["mcpServers"]["github"]

    assert canonical.transport == "stdio"
    assert slot["transportType"] == "local"


def test_env_is_folded_to_the_canonical() -> None:
    text = _file({"github": _stdio_slot(env={"GH": "${TOKEN}"})})

    assert file_to_canonical(text, _surface(), None).env == {"GH": "${TOKEN}"}


def test_disabled_flag_is_folded() -> None:
    text = _file({"github": _stdio_slot(disabled=True)})

    assert file_to_canonical(text, _surface(), None).disabled is True


def test_cwd_and_timeout_are_folded() -> None:
    text = _file({"github": _stdio_slot(cwd="/srv", timeout=30)})

    canonical = file_to_canonical(text, _surface(), None)

    assert canonical.cwd == "/srv"
    assert canonical.timeout == 30


def test_always_allow_alias_is_folded() -> None:
    # A tool spelling the allow-list as `alwaysAllow` folds to the canonical attribute.
    text = _file({"github": _stdio_slot(alwaysAllow=["search", "create"])})

    assert file_to_canonical(text, _surface(), None).always_allow == ("search", "create")


def test_always_allow_alias_is_preserved_on_render() -> None:
    # The tool's own allow-list spelling re-emits verbatim (NFR-06/16), not the canonical key —
    # the same spelling-preservation promise the transport field gets, on a different field.
    text = _file({"github": _stdio_slot(alwaysAllow=["search", "create"])})

    canonical = file_to_canonical(text, _surface(), None)
    slot = json.loads(canonical_to_file(canonical, _surface(), text))["mcpServers"]["github"]

    assert slot["alwaysAllow"] == ["search", "create"]
    assert "always_allow" not in slot


def test_a_tools_own_transport_spelling_survives_render() -> None:
    # cursor spells transport under `type` with value `local`: parse records that
    # spelling and render re-emits it verbatim rather than the canonical `transport`/`stdio`.
    text = _file({"github": _stdio_slot(type="local")})

    canonical = file_to_canonical(text, _surface(), None)
    slot = json.loads(canonical_to_file(canonical, _surface(), text))["mcpServers"]["github"]

    assert slot["type"] == "local"
    assert "transport" not in slot


def test_an_unknown_slot_key_is_preserved_in_per_tool_extra() -> None:
    # No-foreign-leak (NFR-06/16): a key the dialect does not own is kept in the tool's
    # extra bag and re-emitted, not dropped.
    text = _file({"github": _stdio_slot(weirdKey=7)})

    canonical = file_to_canonical(text, _surface(), None)

    assert canonical.per_tool_extra["cursor"]["weirdKey"] == 7
    slot = json.loads(canonical_to_file(canonical, _surface(), text))["mcpServers"]["github"]
    assert slot["weirdKey"] == 7


def test_render_preserves_sibling_slots() -> None:
    prior = _file({"github": _stdio_slot(), "gitlab": {"command": "glab"}})
    canonical = file_to_canonical(prior, _surface(slot="github"), None)

    rendered = json.loads(canonical_to_file(canonical, _surface(slot="github"), prior))

    assert rendered["mcpServers"]["gitlab"] == {"command": "glab"}


def test_extract_id_reads_the_slot_id() -> None:
    assert extract_artifact_id(_file({"github": _stdio_slot()}), _surface()) == _EMBEDDED_ID


def test_extract_id_returns_none_when_unreadable_or_absent() -> None:
    assert extract_artifact_id("{not json", _surface()) is None  # malformed: None, not a raise
    assert extract_artifact_id(_file({"github": {"command": "x"}}), _surface()) is None  # no id


def test_malformed_json_raises_malformed_surface_error() -> None:
    with pytest.raises(MalformedSurfaceError):
        file_to_canonical("{not json", _surface(), None)


def test_a_slot_declaring_no_transport_command_or_url_is_malformed() -> None:
    # The mcp content invariant: a slot must declare how to reach the server. A slot that
    # declares none is malformed CONTENT (the read phase freezes it), not a recipe error.
    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(_file({"github": {"name": "x"}}), _surface(), None)


def test_an_unsupported_transport_value_is_malformed_content() -> None:
    # A transport the canonical set does not recognise is bad user content, so it raises
    # MalformedSurfaceError (-> ParseFailure -> freeze), not a plain recipe ValueError.
    text = _file({"github": {"name": "x", "transport": "carrier-pigeon", "command": "x"}})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, _surface(), None)


def test_an_empty_stdio_command_array_is_malformed_content() -> None:
    text = _file({"github": {"name": "x", "command": []}})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, _surface(), None)


def test_stdio_args_that_is_neither_list_nor_string_is_malformed_content() -> None:
    text = _file({"github": {"name": "x", "command": "npx", "args": 42}})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, _surface(), None)


def test_a_command_array_spelling_is_preserved_on_render() -> None:
    # A tool that spells the invocation as a single array gets that shape back on render
    # (the same spelling-preservation promise transport and always_allow get): command
    # re-emits as [command, *args] under the one `command` key, with no split `args` key.
    text = _file({"github": {"name": "x", "command": ["npx", "-y", "gh-mcp"]}})

    canonical = file_to_canonical(text, _surface(), None)
    slot = json.loads(canonical_to_file(canonical, _surface(), text))["mcpServers"]["github"]

    assert slot["command"] == ["npx", "-y", "gh-mcp"]
    assert "args" not in slot


def test_a_command_array_with_a_separate_args_key_is_malformed_content() -> None:
    # The invocation declared twice in two conflicting shapes: folding one and silently
    # dropping the other would mangle the user's file, so it is bad content (-> freeze).
    text = _file({"github": {"name": "x", "command": ["npx", "-y"], "args": ["server.js"]}})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, _surface(), None)


def test_a_non_integer_timeout_is_malformed_content() -> None:
    # The canonical declares ``timeout: int | None``: a wire value of any other type is bad
    # user content (-> ParseFailure -> freeze), never silently stored against the schema.
    text = _file({"github": _stdio_slot(timeout="5s")})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, _surface(), None)


def test_a_boolean_timeout_is_malformed_content() -> None:
    # bool is an int subclass in Python; the schema means a genuine integer, so JSON
    # true/false is rejected rather than silently folded to 1/0.
    text = _file({"github": _stdio_slot(timeout=True)})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, _surface(), None)


def test_a_non_string_env_value_is_malformed_content() -> None:
    # The canonical declares ``env: Mapping[str, str]``: a JSON true must not become the
    # Python repr 'True' and be written back to the user's file — it fails loud instead.
    text = _file({"github": _stdio_slot(env={"DEBUG": True})})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, _surface(), None)


def test_a_non_string_cwd_is_malformed_content() -> None:
    text = _file({"github": _stdio_slot(cwd=7)})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, _surface(), None)


def test_a_non_string_scalar_command_is_malformed_content() -> None:
    text = _file({"github": {"name": "x", "command": 42}})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, _surface(), None)


def test_a_non_string_command_array_item_is_malformed_content() -> None:
    text = _file({"github": {"name": "x", "command": ["npx", 7]}})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, _surface(), None)


def test_a_non_string_args_item_is_malformed_content() -> None:
    text = _file({"github": {"name": "x", "command": "npx", "args": ["-y", 7]}})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, _surface(), None)


def test_a_non_string_always_allow_item_is_malformed_content() -> None:
    text = _file({"github": _stdio_slot(alwaysAllow=["search", 7])})

    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(text, _surface(), None)


def test_http_transport_fails_loud_pending_s13c() -> None:
    # http/sse (url/headers/auth) land in S13c. Until then an http slot fails loud with a
    # plain ValueError that is NOT a MalformedSurfaceError: the content is valid, the
    # dialect just does not support it yet, so it must not be swallowed as a ParseFailure.
    text = _file({"github": {"name": "x", "transport": "http", "url": "https://x"}})

    with pytest.raises(ValueError) as error:
        file_to_canonical(text, _surface(), None)
    # exactly a plain ValueError, not the MalformedSurfaceError subclass (which would be
    # swallowed into a ParseFailure and freeze a perfectly valid http server).
    assert type(error.value) is ValueError
