"""AdoptionEngine: per-pair dispatcher and shared helpers.

The orchestrator dispatches one discovered pair to one of:
adopt / sync / conflict-resolve / extend-to-new-tools / removal.
Per-responsibility logic lives in the mixins composed below.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agents_sync.adoption.adopter import AdopterMixin
from agents_sync.adoption.conflict_resolver import ConflictResolverMixin
from agents_sync.adoption.extender import ExtenderMixin
from agents_sync.adoption.privacy_gate import PrivacyGateMixin
from agents_sync.adoption.removal_propagator import RemovalPropagatorMixin
from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    is_reserved_customization_name,
)
from agents_sync.state import CustomizationArtifactState
from agents_sync.sync_types import CustomizationArtifactInfo
from agents_sync.tool_status import ToolStatusTracker


class AdoptionEngine(
    AdopterMixin,
    ConflictResolverMixin,
    ExtenderMixin,
    PrivacyGateMixin,
    RemovalPropagatorMixin,
):
    """Per-pair operations: adopt, sync, resolve conflict, extend, remove."""

    def __init__(
        self,
        config: dict[str, Any],
        agentic_tools: dict[str, AgenticToolSpec],
        state_dir: Path,
        tool_status: ToolStatusTracker,
    ) -> None:
        self.config = config
        self.agentic_tools = agentic_tools
        self.state_dir = state_dir
        self.tool_status = tool_status

    def process_pair(
        self,
        pair_id: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
    ) -> bool:
        ps = state.get(pair_id)
        if ps is None:
            return self._adopt_new_pair(pair_id, info, state)

        # Only available tools can be removal-source signals or sync targets
        # (US-11 AC-4: an unavailable tool's absence from `info` is not removal).
        available = self._available_participating_tools(info.kind)
        present = [t for t in available if t in info.agentic_tools]
        missing_from_state = [
            t for t in available
            if t in ps.agentic_tools and t not in info.agentic_tools
        ]
        if missing_from_state:
            return self._propagate_removal(
                pair_id, info, state, missing_from_state, survivors=present,
            )
        if not present:
            return False

        missing_pair_id_tools = [
            t for t in present
            if t in ps.agentic_tools and not info.agentic_tools[t].pair_id_present
        ]
        if missing_pair_id_tools:
            source = self._pick_winner(missing_pair_id_tools, info)
            return self._sync_from_agentic_tool(pair_id, source, info, state)

        changed = [
            t for t in present
            if info.agentic_tools[t].digest
            != (ps.agentic_tools[t].last_written if t in ps.agentic_tools else None)
        ]
        # Available tools that are newly participating (in neither state nor
        # info) — extend the canonical to them per v0.4 plan §5 first bullet.
        to_extend = [
            t for t in available
            if t not in ps.agentic_tools and t not in info.agentic_tools
        ]
        if not changed:
            if to_extend:
                return self._extend_to_new_tools(pair_id, info, state, to_extend)
            return False
        if len(changed) == 1:
            return self._sync_from_agentic_tool(pair_id, changed[0], info, state)
        return self._resolve_conflict_n_way(pair_id, info, state, changed)

    def _available_participating_tools(self, kind: str) -> list[str]:
        """Participating tools whose status is currently `available`."""
        return [
            name for name, spec in self.agentic_tools.items()
            if kind in spec.supported_customization_types
            and self.tool_status.is_available(name)
        ]

    def _is_reserved_target_name(
        self,
        spec: AgenticToolSpec,
        kind: str,
        canonical: dict[str, Any],
    ) -> bool:
        """Whether rendering would create a command with a target-reserved name."""
        io = spec.io[kind]
        name = str(canonical.get("name", ""))
        return is_reserved_customization_name(io, name)
