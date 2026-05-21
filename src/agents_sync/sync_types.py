"""Per-poll data containers shared between discovery, adoption, and the
top-level Syncer. These describe what discovery has *just observed* on
disk — distinct from agents_sync.state, which describes what the daemon
believes is true across polls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgenticToolInfo:
    """One tool's view of one artifact in the current poll.

    For ``SharedKeyedMapLayout`` artifacts (v0.5 ``mcp_server``),
    ``path`` is the shared keyed-map file and ``slot`` is the key
    inside the map identifying this artifact's entry. For every other
    layout ``slot`` is ``None`` and ``path`` is the per-file artifact
    path. ``digest`` is over the slot text when ``slot`` is set,
    over the whole file otherwise.
    """
    path: Path
    digest: str
    mtime: float
    pair_id_present: bool
    slot: str | None = None


@dataclass
class CustomizationArtifactInfo:
    """All tools' views of one pair, indexed by tool name."""
    kind: str
    agentic_tools: dict[str, AgenticToolInfo] = field(default_factory=dict)


@dataclass(frozen=True)
class PlannedTarget:
    """An adoption / projection target. ``slot`` is set only for
    ``SharedKeyedMapLayout`` (v0.5 ``mcp_server``) targets; otherwise
    ``slot`` is ``None`` and ``path`` is the per-file target path.
    """
    path: Path
    slot: str | None = None
    preexisting: bool = False


@dataclass(frozen=True)
class RenderResult:
    """Result of rendering one canonical onto one agentic_tool.

    For per-file artifacts, ``slot`` is ``None`` and ``path`` is the
    written file (or directory for skills). For
    ``SharedKeyedMapLayout`` artifacts, ``path`` is the shared keyed-
    map file and ``slot`` is the key written under
    ``map_key_path``. ``prior_slot_text`` is the slot's previous
    serialised value for archive purposes — populated only on keyed-
    map writes, ``None`` otherwise.
    """
    path: Path
    slot: str | None = None
    prior_slot_text: str | None = None
