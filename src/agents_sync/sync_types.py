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
    """One tool's view of one artifact in the current poll."""
    path: Path
    digest: str
    mtime: float
    pair_id_present: bool


@dataclass
class CustomizationArtifactInfo:
    """All tools' views of one pair, indexed by tool name."""
    kind: str
    agentic_tools: dict[str, AgenticToolInfo] = field(default_factory=dict)
