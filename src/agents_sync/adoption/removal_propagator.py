"""Archive-then-delete survivors when one available tool removes the artifact.

Available tools that no longer surface the artifact are removal
signals. Surviving copies on other available tools are archived and
deleted; state entries for unavailable tools are preserved verbatim
(US-11 AC-4). If every entry in the pair would be dropped, the
pair_id itself is dropped.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agents_sync import archive
from agents_sync.agentic_tool_spec import SharedKeyedMapLayout
from agents_sync.shared_keyed_map_io import (
    SharedKeyedMapRaceError,
    SharedKeyedMapSlotCollisionError,
    apply_slot,
)
from agents_sync.state import CustomizationArtifactState
from agents_sync.sync_types import AgenticToolInfo, CustomizationArtifactInfo


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


class RemovalPropagatorMixin:
    """Removal propagation and orphan handling."""

    def propagate_orphan_state(
        self, pair_id: str, state: dict[str, CustomizationArtifactState]
    ) -> bool:
        """pair_id is in state but no available tool surfaced it this poll.

        Entries for ``available`` tools are dropped (those tools removed the
        artifact). Entries for ``unavailable`` tools are preserved verbatim
        (US-11 AC-4). When no entries remain, the pair_id itself is dropped.
        """
        ps = state[pair_id]
        for tool in list(ps.agentic_tools.keys()):
            if self.tool_status.is_available(tool):
                del ps.agentic_tools[tool]
        if not ps.agentic_tools:
            del state[pair_id]
            logging.info("Pair fully removed: pair_id=%s", pair_id)
        else:
            logging.info(
                "Pair partially removed: pair_id=%s preserved_unavailable=%s",
                pair_id, list(ps.agentic_tools.keys()),
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
        for tool in survivors:
            survivor_info = info.agentic_tools[tool]
            survivor_io = self.agentic_tools[tool].io[info.kind]
            if isinstance(survivor_io.file_layout, SharedKeyedMapLayout):
                if not self._remove_keyed_map_slot(
                    pair_id, tool, survivor_info, survivor_io,
                ):
                    return False
                continue
            if not self._remove_file_artifact(
                pair_id, tool, survivor_info.path,
            ):
                return False
        ps = state[pair_id]
        for tool in list(missing_tools) + list(survivors):
            ps.agentic_tools.pop(tool, None)
        if not ps.agentic_tools:
            del state[pair_id]
            logging.info(
                "Propagated removal (fully dropped): pair_id=%s missing=%s survivors=%s",
                pair_id, missing_tools, survivors,
            )
        else:
            logging.info(
                "Propagated removal: pair_id=%s missing=%s survivors=%s "
                "preserved_unavailable=%s",
                pair_id, missing_tools, survivors, list(ps.agentic_tools.keys()),
            )
        return True

    def _remove_keyed_map_slot(
        self,
        pair_id: str,
        tool: str,
        survivor_info: AgenticToolInfo,
        survivor_io: Any,
    ) -> bool:
        """Archive the prior slot text and delete the slot from the shared file.

        Returns False on failure (the caller aborts and leaves the survivor
        on disk; state is preserved so the next poll retries).
        """
        slot_key = survivor_info.slot
        if slot_key is None:
            return True
        try:
            prior_slot_text = apply_slot(
                survivor_info.path, survivor_io.file_layout,
                slot_key, new_slot_text=None,
                expected_pair_id=pair_id,
            )
        except _REMOVAL_FAILURES:
            logging.exception(
                "Archive-then-remove aborted: pair_id=%s survivor=%s slot=%s",
                pair_id, tool, slot_key,
            )
            return False
        if prior_slot_text is not None:
            archive.archive_text(
                self.state_dir, pair_id, tool,
                slot_name=slot_key,
                extension=survivor_io.file_layout.file_suffix,
                content=prior_slot_text,
            )
        return True

    def _remove_file_artifact(
        self, pair_id: str, tool: str, survivor_path: Path,
    ) -> bool:
        """Archive-move the survivor file into the per-pair archive."""
        if not survivor_path.exists():
            return True
        try:
            archive.archive_move(self.state_dir, pair_id, tool, survivor_path)
        except _REMOVAL_FAILURES:
            logging.exception(
                "Archive-then-remove aborted: pair_id=%s survivor=%s",
                pair_id, tool,
            )
            return False
        return True
