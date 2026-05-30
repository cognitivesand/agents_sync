"""Archive-then-delete survivors when one available tool removes the artifact.

Available tools that no longer surface the artifact are removal
signals. Surviving copies on other available tools are archived and
deleted; state entries for unavailable tools are preserved verbatim
(US-11 AC-4). If every entry in the pair would be dropped, the
pair_id itself is dropped. If a survivor removal fails after earlier
survivors were already deleted, state advances for the completed
survivors so the next poll retries only the entries still present.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents_sync import archive
from agents_sync.agentic_tool_spec import SharedKeyedMapLayout
from agents_sync.shared_keyed_map_io import (
    SharedKeyedMapRaceError,
    SharedKeyedMapSlotCollisionError,
    apply_slot,
)
from agents_sync.state import CustomizationArtifactState
from agents_sync.sync_types import AgenticToolInfo, CustomizationArtifactInfo

if TYPE_CHECKING:
    from agents_sync.adoption._host import _AdoptionHost

    _AdoptionHostBase = _AdoptionHost
else:
    _AdoptionHostBase = object

# Narrow except set used by removal-propagation paths: I/O errors,
# format-parse errors, and the two lock/collision failures that apply_slot
# raises by contract. Captured here so the per-pair handlers don't swallow
# programmer errors (TypeError, AttributeError) as if they were I/O failures
# (audit slice 08 · CQ-12).
_REMOVAL_FAILURES: tuple[type[Exception], ...] = (
    OSError,
    ValueError,
    SharedKeyedMapRaceError,
    SharedKeyedMapSlotCollisionError,
)


class RemovalPropagatorMixin(_AdoptionHostBase):
    """Removal propagation and orphan handling."""

    def propagate_orphan_state(
        self,
        pair_id: str,
        state: dict[str, CustomizationArtifactState],
        glitch_tools: frozenset[str] = frozenset(),
    ) -> bool:
        """pair_id is in state but no available tool surfaced it this poll.

        If **every** available tool that recorded the pair is glitch-flagged
        (>=2 of its artifacts vanished this poll, US-11 AC-9), the disappearance
        is a transient glitch: re-project the pair from the canonical, drop
        nothing. Otherwise it is a deliberate removal — entries for ``available``
        tools are dropped (those tools removed the artifact), entries for
        ``unavailable`` tools are preserved verbatim (US-11 AC-4), and when no
        entries remain the canonical is archived (US-05 AC-5) and the pair_id
        dropped.
        """
        ps = state[pair_id]
        available_recorded = [t for t in ps.agentic_tools if self.tool_status.is_available(t)]
        if available_recorded and all(t in glitch_tools for t in available_recorded):
            self.project_from_canonical(pair_id, state, target_tools=available_recorded)
            logging.warning(
                "Glitch (bulk disappearance) re-projected, not removed: pair_id=%s tools=%s",
                pair_id,
                available_recorded,
            )
            return True
        for tool in available_recorded:
            del ps.agentic_tools[tool]
        if not ps.agentic_tools:
            archive.archive_canonical(self.state_dir, pair_id)
            del state[pair_id]
            logging.info("Pair fully removed: pair_id=%s", pair_id)
        else:
            logging.info(
                "Pair partially removed: pair_id=%s preserved_unavailable=%s",
                pair_id,
                list(ps.agentic_tools.keys()),
            )
        return True

    def _propagate_removal(
        self,
        pair_id: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
        missing_tools: list[str],
        survivors: list[str],
    ) -> bool:
        removed_survivors: list[str] = []
        failed_survivor: str | None = None
        for tool in survivors:
            survivor_info = info.agentic_tools[tool]
            survivor_io = self.agentic_tools[tool].io[info.kind]
            if isinstance(survivor_io.file_layout, SharedKeyedMapLayout):
                if not self._remove_keyed_map_slot(
                    pair_id,
                    tool,
                    survivor_info,
                    survivor_io,
                ):
                    failed_survivor = tool
                    break
                removed_survivors.append(tool)
                continue
            if not self._remove_file_artifact(
                pair_id,
                tool,
                survivor_info.path,
            ):
                failed_survivor = tool
                break
            removed_survivors.append(tool)

        if failed_survivor is not None:
            if not removed_survivors:
                return False
            self._drop_state_tools(pair_id, state, removed_survivors)
            logging.warning(
                "Removal propagation partially applied: pair_id=%s "
                "missing=%s removed_survivors=%s failed_survivor=%s",
                pair_id,
                missing_tools,
                removed_survivors,
                failed_survivor,
            )
            return True

        self._drop_state_tools(pair_id, state, list(missing_tools) + removed_survivors)
        if pair_id not in state:
            logging.info(
                "Propagated removal (fully dropped): pair_id=%s missing=%s survivors=%s",
                pair_id,
                missing_tools,
                survivors,
            )
        else:
            ps = state[pair_id]
            logging.info(
                "Propagated removal: pair_id=%s missing=%s survivors=%s preserved_unavailable=%s",
                pair_id,
                missing_tools,
                survivors,
                list(ps.agentic_tools.keys()),
            )
        return True

    def _drop_state_tools(
        self,
        pair_id: str,
        state: dict[str, CustomizationArtifactState],
        tools: list[str],
    ) -> None:
        ps = state[pair_id]
        for tool in tools:
            ps.agentic_tools.pop(tool, None)
        if not ps.agentic_tools:
            # US-05 AC-5: archive-and-remove the canonical before dropping the
            # pair, so a stale canonical can never be re-projected (NFR-16).
            archive.archive_canonical(self.state_dir, pair_id)
            del state[pair_id]

    def _remove_keyed_map_slot(
        self,
        pair_id: str,
        tool: str,
        survivor_info: AgenticToolInfo,
        survivor_io: Any,
    ) -> bool:
        """Archive the prior slot text and delete the slot from the shared file.

        Returns False on failure. The caller records successful earlier
        removals in state so the next poll retries only the remaining tools.
        """
        slot_key = survivor_info.slot
        if slot_key is None:
            return True
        try:
            prior_slot_text = apply_slot(
                survivor_info.path,
                survivor_io.file_layout,
                slot_key,
                new_slot_text=None,
                expected_pair_id=pair_id,
            )
        except _REMOVAL_FAILURES:
            logging.exception(
                "Archive-then-remove aborted: pair_id=%s survivor=%s slot=%s",
                pair_id,
                tool,
                slot_key,
            )
            return False
        if prior_slot_text is not None:
            archive.archive_text(
                self.state_dir,
                pair_id,
                tool,
                slot_name=slot_key,
                extension=survivor_io.file_layout.file_suffix,
                content=prior_slot_text,
            )
        return True

    def _remove_file_artifact(
        self,
        pair_id: str,
        tool: str,
        survivor_path: Path,
    ) -> bool:
        """Archive-move the survivor file into the per-pair archive."""
        if not survivor_path.exists():
            return True
        try:
            archive.archive_move(self.state_dir, pair_id, tool, survivor_path)
        except _REMOVAL_FAILURES:
            logging.exception(
                "Archive-then-remove aborted: pair_id=%s survivor=%s",
                pair_id,
                tool,
            )
            return False
        return True
