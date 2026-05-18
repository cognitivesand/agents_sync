"""Per-pair sync algorithm — Phase 3 (bidirectional with mtime conflict resolution)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agents_sync import archive
from agents_sync.adoption import AdoptionEngine
from agents_sync.agentic_tool_spec import AgenticToolSpec, default_agentic_tools
from agents_sync.canonical import is_private
from agents_sync.config import expand_path, validate_config
from agents_sync.discovery import DiscoveryWalker
from agents_sync.rendering import read_artifact_text
from agents_sync.state import (
    CustomizationArtifactState,
    load_state,
    save_state,
    target_slug,
)
from agents_sync.sync_types import AgenticToolInfo, CustomizationArtifactInfo
from agents_sync.tool_status import ToolStatusTracker


class Syncer:
    def __init__(
        self,
        config: dict[str, Any],
        agentic_tools: dict[str, AgenticToolSpec] | None = None,
    ) -> None:
        self.config = dict(config)
        self.agentic_tools: dict[str, AgenticToolSpec] = (
            agentic_tools if agentic_tools is not None else default_agentic_tools()
        )
        self.state_dir = expand_path(config["state_path"]).parent
        self._blocked_pair_ids: set[str] = set()
        self.tool_status = ToolStatusTracker(self.config, self.agentic_tools)
        self.discovery = DiscoveryWalker(
            self.config, self.agentic_tools, self.tool_status
        )
        self.adoption = AdoptionEngine(
            self.config, self.agentic_tools, self.state_dir, self.tool_status
        )
        # Best-effort: create each enabled tool's roots once at startup. This
        # turns "fresh-install, dir-not-yet-materialised" into `available` on
        # the first poll, instead of US-11 `unavailable` (which would silently
        # strand the user's library). Mid-life loss of a root still flips the
        # tool to `unavailable` per US-11 AC-2.
        self.tool_status.ensure_roots()

    def tool_root(self, tool_name: str, customization_type: str) -> Path:
        """Return the configured root for one tool/customization-type cell."""
        spec = self.agentic_tools[tool_name]
        config_key = spec.config_dir_keys[customization_type]
        return expand_path(self.config[config_key])

    # ---------- top-level loop ----------

    def sync_once(self) -> int:
        validate_config(self.config)
        self.tool_status.refresh()
        state = load_state(self.state_dir)
        discovery, self._blocked_pair_ids = self.discovery.discover(state)
        self._reconcile_new_groups(discovery, state)
        self._blocked_pair_ids |= self.discovery.block_target_collisions(
            discovery, state
        )
        changed = 0

        for pair_id, info in discovery.items():
            try:
                if self.adoption.process_pair(pair_id, info, state):
                    changed += 1
            except Exception:
                logging.exception("Failed to sync pair: pair_id=%s", pair_id)

        # Detect deleted pairs (in state but not in discovery). Per US-11 AC-4,
        # only `available` tools can be removal sources: a pair whose state
        # entries are all for unavailable tools is preserved verbatim until at
        # least one of its tools returns to `available`.
        for pair_id in list(state.keys()):
            if pair_id in discovery:
                continue
            if pair_id in self._blocked_pair_ids:
                continue
            ps = state[pair_id]
            if not any(
                self.tool_status.is_available(t) for t in ps.agentic_tools
            ):
                continue
            try:
                if self.adoption.propagate_orphan_state(pair_id, state):
                    changed += 1
            except Exception:
                logging.exception("Failed to handle orphan state: pair_id=%s", pair_id)

        save_state(self.state_dir, state)
        return changed

    # ---------- first-boot reconciliation (v0.4 plan §5.5) ----------

    def _reconcile_new_groups(
        self,
        discovery: dict[str, CustomizationArtifactInfo],
        state: dict[str, CustomizationArtifactState],
    ) -> None:
        """Merge multi-tool new-artifact duplicates before per-tool adoption.

        Discovery produces one CustomizationArtifactInfo per (tool, file) when
        files lack a pair_id, because each tool mints its own UUID. If the same
        logical artifact (same name, hence same target_slug) exists on multiple
        tools with no pair_id on any of them, naive adoption would block on a
        slug collision. This phase groups those entries by
        (customization_type, slug) and collapses each multi-tool group into a
        single managed artifact under one pair_id (argmax mtime, alphabetical
        tiebreak). Losers' pre-merge bytes are archived; the winner's
        pre-injection bytes are archived later by _adopt_from_agentic_tool.

        Singleton groups, mixed groups with a managed artifact at the same
        slug, and multi-managed-id collisions are left untouched here; the
        existing _block_target_collisions step handles them.
        """
        new_pair_ids = [
            pair_id for pair_id, info in discovery.items()
            if info.agentic_tools and all(
                not t.pair_id_present for t in info.agentic_tools.values()
            )
        ]
        if not new_pair_ids:
            return

        groups: dict[tuple[str, str], list[str]] = {}
        source_tool_by_pair: dict[str, str] = {}
        for pair_id in new_pair_ids:
            info = discovery[pair_id]
            tool_name = next(iter(info.agentic_tools))
            tool_info = info.agentic_tools[tool_name]
            io = self.agentic_tools[tool_name].io[info.kind]
            root = expand_path(
                self.config[self.agentic_tools[tool_name].config_dir_keys[info.kind]]
            )
            try:
                text = read_artifact_text(io, tool_info.path)
                canonical = io.parse(
                    text,
                    None,
                    artifact_path=tool_info.path,
                    artifact_root=root,
                )
            except Exception:
                logging.exception(
                    "Reconcile: cannot parse for grouping: pair_id=%s tool=%s path=%s",
                    pair_id, tool_name, tool_info.path,
                )
                continue
            if is_private(canonical):
                discovery.pop(pair_id, None)
                continue
            slug = target_slug(canonical["name"])
            groups.setdefault((info.kind, slug), []).append(pair_id)
            source_tool_by_pair[pair_id] = tool_name

        for (kind, slug), group_pair_ids in groups.items():
            if len(group_pair_ids) < 2:
                continue
            # Skip groups where the same tool appears twice: those are intra-tool
            # slug collisions (e.g. two distinct claude files that slugify to the
            # same name), not multi-tool duplicates. Hand them to
            # _block_target_collisions intact.
            tools_in_group = {source_tool_by_pair[p] for p in group_pair_ids}
            if len(tools_in_group) != len(group_pair_ids):
                continue
            self._merge_new_artifact_group(
                discovery, kind, slug, group_pair_ids, source_tool_by_pair
            )

    def _merge_new_artifact_group(
        self,
        discovery: dict[str, CustomizationArtifactInfo],
        kind: str,
        slug: str,
        pair_ids: list[str],
        source_tool_by_pair: dict[str, str],
    ) -> None:
        """Collapse a multi-tool new-artifact group into one merged entry.

        Winner = argmax(mtime) with alphabetical tiebreak across tool names.
        Losers' bytes archived under the winner's minted pair_id before
        discovery is rewritten. Adoption then proceeds from the winner.
        """
        def tool_info_for(pair_id: str) -> AgenticToolInfo:
            return discovery[pair_id].agentic_tools[source_tool_by_pair[pair_id]]

        winner_pair_id = sorted(
            pair_ids,
            key=lambda p: (-tool_info_for(p).mtime, source_tool_by_pair[p]),
        )[0]
        merged_pair_id = winner_pair_id

        for p in pair_ids:
            if p == winner_pair_id:
                continue
            loser_tool = source_tool_by_pair[p]
            loser_path = tool_info_for(p).path
            try:
                archive.archive_copy(
                    self.state_dir, merged_pair_id, loser_tool, loser_path
                )
            except Exception:
                logging.exception(
                    "Reconcile: archive failed; aborting merge "
                    "kind=%s slug=%s pair_id=%s tool=%s",
                    kind, slug, p, loser_tool,
                )
                return

        merged_tools: dict[str, AgenticToolInfo] = {}
        for p in pair_ids:
            tool = source_tool_by_pair[p]
            merged_tools[tool] = tool_info_for(p)
        merged_info = CustomizationArtifactInfo(kind=kind, agentic_tools=merged_tools)

        for p in pair_ids:
            discovery.pop(p, None)
        discovery[merged_pair_id] = merged_info

        logging.info(
            "Reconciled new-artifact group: kind=%s slug=%s pair_id=%s "
            "winner=%s merged_tools=%s",
            kind, slug, merged_pair_id,
            source_tool_by_pair[winner_pair_id],
            list(merged_tools.keys()),
        )

