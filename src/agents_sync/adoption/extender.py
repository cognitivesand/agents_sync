"""Extend an existing canonical to newly-available tools (v0.4 plan §5)."""
from __future__ import annotations

import logging
from pathlib import Path

from agents_sync.canonical import load_canonical
from agents_sync.rendering import render_to_agentic_tool, update_state_n_way
from agents_sync.state import CustomizationArtifactState
from agents_sync.sync_types import CustomizationArtifactInfo, RenderResult


class ExtenderMixin:
    """Render the canonical to newly-participating tools (§5 first bullet)."""

    def _extend_to_new_tools(
        self,
        pair_id: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
        target_tools: list[str],
    ) -> bool:
        canonical = load_canonical(self.state_dir, pair_id)
        if canonical is None:
            logging.error(
                "Cannot extend pair_id=%s: canonical document missing", pair_id
            )
            return False

        source_dir: Path | None = None
        if info.kind == "skill":
            for _tool_name, tool_info in info.agentic_tools.items():
                if tool_info.path.exists():
                    source_dir = tool_info.path
                    break

        results: dict[str, RenderResult] = {}
        for tool_name in target_tools:
            target_spec = self.agentic_tools[tool_name]
            if self._is_reserved_target_name(target_spec, info.kind, canonical):
                logging.warning(
                    "Reserved slash_command name skipped: pair_id=%s tool=%s name=%s",
                    pair_id,
                    tool_name,
                    canonical.get("name"),
                )
                continue
            results[tool_name] = render_to_agentic_tool(
                self.config,
                target_spec,
                info.kind,
                canonical,
                existing_path=None,
                prior_text=None,
                source_dir=source_dir,
            )
        self._archive_prior_slot_results(pair_id, info.kind, results)
        update_state_n_way(state, pair_id, info.kind, results, self.agentic_tools)
        logging.info(
            "Extended to newly available tools: pair_id=%s tools=%s",
            pair_id, target_tools,
        )
        return True
