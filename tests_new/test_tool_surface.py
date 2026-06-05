"""Unit tests for the tool-surface vocabulary (rebuild S3b).

`KeyedMapSlot`, the minimal `SurfaceFormat` (just `dialect` for now — recipe
fields grow with their consumers in S9/S17), and `ToolSurface` are immutable,
hashable value objects describing where a tool keeps an artifact. Only the
value-object contract is built yet (YAGNI): no parse/render/select behaviour.
The contract under test (immutability + hashing + a Path-or-slot location) is
load-bearing — the planner groups surfaces in sets and recompute-from-disk relies
on them not mutating.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from agents_sync.domain_model.tool_surface import KeyedMapSlot, SurfaceFormat, ToolSurface

_FORMAT = SurfaceFormat(dialect="markdown_frontmatter")
_AGENT_PATH = Path("/home/u/.claude/agents/reviewer.md")
_MCP_SLOT = KeyedMapSlot(file=Path("/home/u/.codex/config.toml"), slot="mcp_servers.github")


def _surface(**overrides: object) -> ToolSurface:
    defaults: dict[str, object] = {
        "tool": "claude",
        "kind": "agent",
        "location": _AGENT_PATH,
        "surface_format": _FORMAT,
    }
    defaults.update(overrides)
    return ToolSurface(**defaults)  # type: ignore[arg-type]


def test_location_can_be_a_file_path_or_a_keyed_map_slot() -> None:
    # The Path-or-slot union is the one real design point: a per-file surface and
    # a shared keyed-map surface (mcp_server) each preserve their location and are
    # distinct.
    by_path = _surface(location=_AGENT_PATH)
    by_slot = _surface(kind="mcp_server", location=_MCP_SLOT)

    assert by_path.location == _AGENT_PATH
    assert by_slot.location == _MCP_SLOT
    assert by_path != by_slot


def test_equal_tool_surfaces_are_hashable_and_dedupe_in_a_set() -> None:
    one = _surface()
    same = _surface()

    assert one == same
    assert hash(one) == hash(same)
    assert len({one, same}) == 1


@pytest.mark.parametrize(
    "difference",
    [{"tool": "codex"}, {"kind": "skill"}, {"location": Path("/other.md")}],
)
def test_tool_surfaces_differing_in_a_field_are_unequal(difference: dict[str, object]) -> None:
    assert _surface() != _surface(**difference)


def test_tool_surface_is_immutable() -> None:
    surface = _surface()

    with pytest.raises(FrozenInstanceError):
        surface.kind = "skill"  # type: ignore[misc]


def test_keyed_map_slot_is_an_immutable_hashable_value_object() -> None:
    a = KeyedMapSlot(file=Path("/c.toml"), slot="x")
    b = KeyedMapSlot(file=Path("/c.toml"), slot="x")

    assert a == b
    assert hash(a) == hash(b)
    with pytest.raises(FrozenInstanceError):
        a.slot = "y"  # type: ignore[misc]


def test_surface_format_is_an_immutable_value_object() -> None:
    a = SurfaceFormat(dialect="keyed_map_slot")
    same = SurfaceFormat(dialect="keyed_map_slot")

    assert a == same  # value-equal by dialect (the translation discriminator)
    assert a != SurfaceFormat(dialect="markdown_frontmatter")
    with pytest.raises(FrozenInstanceError):
        a.dialect = "structured_text"  # type: ignore[misc]
