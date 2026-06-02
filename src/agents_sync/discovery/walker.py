"""DiscoveryWalker: orchestrator and public API.

The walker holds no per-poll state of its own; ``discover`` and
``block_target_collisions`` are pure functions of their inputs except
for their explicit ``discovery`` / ``state`` mutations. The per-cell
enumeration, adoption-target planning, and collision-detection
responsibilities live in dedicated mixins (see :mod:`enumerator`,
:mod:`adoption_planner`, :mod:`collision_blocker`).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    SharedKeyedMapLayout,
)
from agents_sync.config import expand_path
from agents_sync.discovery.adoption_planner import AdoptionPlannerMixin
from agents_sync.discovery.collision_blocker import CollisionBlockerMixin
from agents_sync.discovery.enumerator import EnumeratorMixin
from agents_sync.rendering import slot_aware_collision_key
from agents_sync.state import CustomizationArtifactState
from agents_sync.sync_types import CustomizationArtifactInfo
from agents_sync.tool_status import ToolStatusTracker


class DiscoveryWalker(
    EnumeratorMixin,
    AdoptionPlannerMixin,
    CollisionBlockerMixin,
):
    """Walks the on-disk artifact tree and produces a discovery view."""

    def __init__(
        self,
        config: Mapping[str, Any],
        agentic_tools: dict[str, AgenticToolSpec],
        tool_status: ToolStatusTracker,
    ) -> None:
        self.config = config
        self.agentic_tools = agentic_tools
        self.tool_status = tool_status

    def discover(
        self, state: dict[str, CustomizationArtifactState]
    ) -> tuple[dict[str, CustomizationArtifactInfo], set[str]]:
        """Walk every (agentic_tool, customization_type) cell in the registry.

        Tools whose status is not ``available`` are skipped entirely so
        unreadable / unmounted / disabled tools never appear as removal
        signals (US-11 AC-4).

        Returns ``(pairs, blocked_pair_ids)``. A blocked pair_id has already
        been popped from ``pairs``.
        """
        pairs: dict[str, CustomizationArtifactInfo] = {}
        blocked_pair_ids: set[str] = set()

        for tool_name, spec in self.agentic_tools.items():
            if not self.tool_status.is_available(tool_name):
                continue
            for customization_type in sorted(spec.supported_customization_types):
                if not self.tool_status.is_kind_available(tool_name, customization_type):
                    continue
                io = spec.io[customization_type]
                if isinstance(io.file_layout, SharedKeyedMapLayout):
                    self._discover_shared_keyed_map(
                        tool_name,
                        customization_type,
                        io,
                        pairs,
                        blocked_pair_ids,
                        state,
                    )
                    continue
                root = expand_path(self.config[spec.config_dir_keys[customization_type]])
                if not root.exists():
                    continue
                for artifact_path in self._enumerate_artifacts(root, io):
                    self._add_agentic_tool_artifact(
                        tool_name,
                        customization_type,
                        artifact_path,
                        io,
                        pairs,
                        blocked_pair_ids,
                        state,
                    )

        # A pair_id can be blocked (e.g. invalid id on one tool) after another
        # tool has already inserted its valid entry into `pairs`. Evict those
        # late-blocked entries so per-pair processing doesn't see a partial
        # info and mistake the blocked tools for removed.
        for pair_id in blocked_pair_ids:
            pairs.pop(pair_id, None)
        return pairs, blocked_pair_ids

    def state_owner_for_path(
        self,
        path: Path,
        state: dict[str, CustomizationArtifactState],
        slot: str | None = None,
    ) -> str | None:
        """Return the pair_id whose state owns ``(path, slot)``, or None.

        For per-file artifacts, ``slot`` is ``None`` and the comparison
        matches any state entry whose path normalises to the same key,
        regardless of that entry's slot field. For keyed-map artifacts,
        ``slot`` must match the state entry's slot exactly — two slots
        in the same shared file are distinct artifacts.
        """
        target_key = slot_aware_collision_key(path, slot)
        for pair_id, pair_state in state.items():
            for tool_state in pair_state.agentic_tools.values():
                state_key = slot_aware_collision_key(
                    tool_state.path,
                    tool_state.slot,
                )
                if state_key == target_key:
                    return pair_id
        return None
