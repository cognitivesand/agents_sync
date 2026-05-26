"""N-way conflict resolution: pick argmax(mtime), archive losers' bytes."""
from __future__ import annotations

import logging
from typing import Any

from agents_sync import archive
from agents_sync.agentic_tool_spec import SharedKeyedMapLayout
from agents_sync.canonical import load_canonical
from agents_sync.rendering import read_artifact_text
from agents_sync.state import CustomizationArtifactState
from agents_sync.sync_types import CustomizationArtifactInfo


class ConflictResolverMixin:
    """N-way conflict resolution. Relies on ``self.state_dir``,
    ``self.agentic_tools``, and adopter methods from :class:`AdoptionEngine`."""

    def _resolve_conflict_n_way(
        self,
        pair_id: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
        changed_tools: list[str],
    ) -> bool:
        """Pick argmax(mtime) over changed tools; archive losers' bytes; project."""
        winner = self._pick_winner(changed_tools, info)
        if self._winner_is_private(pair_id, winner, info):
            return False
        for tool in changed_tools:
            if tool == winner:
                continue
            self._archive_existing_tool_bytes(pair_id, info.kind, tool, info)
        logging.warning(
            "Conflict resolved (%s wins): pair_id=%s mtimes=%s",
            winner, pair_id,
            {t: info.agentic_tools[t].mtime for t in changed_tools},
        )
        return self._sync_from_agentic_tool(pair_id, winner, info, state)

    def _archive_existing_tool_bytes(
        self,
        pair_id: str,
        kind: str,
        tool: str,
        info: CustomizationArtifactInfo,
    ) -> None:
        """Archive the current bytes for ``tool`` respecting storage shape."""
        tool_info = info.agentic_tools[tool]
        tool_io = self.agentic_tools[tool].io[kind]
        if isinstance(tool_io.file_layout, SharedKeyedMapLayout):
            prior_text = read_artifact_text(
                tool_io, tool_info.path, slot=tool_info.slot,
            )
            archive.archive_text(
                self.state_dir, pair_id, tool,
                slot_name=str(tool_info.slot),
                extension=tool_io.file_layout.file_suffix,
                content=prior_text,
            )
            return
        archive.archive_copy(self.state_dir, pair_id, tool, tool_info.path)

    def _winner_is_private(
        self,
        pair_id: str,
        winner: str,
        info: CustomizationArtifactInfo,
    ) -> bool:
        prior_canonical = load_canonical(self.state_dir, pair_id)
        tool_info = info.agentic_tools[winner]
        tool_io = self.agentic_tools[winner].io[info.kind]
        text = read_artifact_text(tool_io, tool_info.path, slot=tool_info.slot)
        canonical = tool_io.parse(
            text,
            prior_canonical,
            artifact_path=tool_info.path,
        )
        return self._skip_private_canonical(pair_id, winner, canonical)
