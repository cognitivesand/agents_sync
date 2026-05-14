"""Per-pair adoption, sync, conflict resolution, and removal propagation.

AdoptionEngine owns every operation that mutates a single pair's on-disk
artifacts or state entry. Its public surface is two methods:

  - process_pair: dispatch a single discovered pair to one of:
      adopt / sync / conflict-resolve / extend-to-new-tools / removal.
  - propagate_orphan_state: drop a pair that has no on-disk evidence
    left on any available tool.

Extracted from Syncer so the orchestrator does not host the seven
distinct per-pair operations.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

from agents_sync import archive
from agents_sync.agentic_tool_spec import AgenticToolSpec
from agents_sync.canonical import load_canonical, save_canonical
from agents_sync.rendering import (
    read_artifact_text,
    render_to_agentic_tool,
    update_state_n_way,
    write_artifact_inplace,
)
from agents_sync.state import CustomizationArtifactState
from agents_sync.sync_types import CustomizationArtifactInfo
from agents_sync.tool_status import ToolStatusTracker


class AdoptionEngine:
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

    # ---------- public dispatcher ----------

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
                pair_id, info, state, missing_from_state, survivors=present
            )
        if not present:
            return False

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

    # ---------- adoption ----------

    def _adopt_new_pair(
        self,
        pair_id: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
    ) -> bool:
        winner = self._pick_winner(info.agentic_tools.keys(), info)
        return self._adopt_from_agentic_tool(pair_id, winner, info, state)

    def _adopt_from_agentic_tool(
        self,
        pair_id: str,
        source_tool: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
    ) -> bool:
        """Parse from `source_tool`, inject pair_id if newly minted, then project
        the canonical to every other participating tool."""
        source_info = info.agentic_tools[source_tool]
        source_spec = self.agentic_tools[source_tool]
        source_io = source_spec.io[info.kind]
        text = read_artifact_text(source_io, source_info.path)
        canonical = source_io.parse(text, None)
        canonical["pair_id"] = pair_id

        if not source_info.pair_id_present:
            archive.archive_copy(self.state_dir, pair_id, source_tool, source_info.path)
            write_artifact_inplace(
                source_io, source_info.path, source_io.render(canonical, text)
            )

        save_canonical(self.state_dir, pair_id, canonical)

        source_dir = source_info.path if source_io.storage == "directory_skill" else None
        paths = self._project_to_other_tools(
            pair_id=pair_id,
            canonical=canonical,
            info=info,
            source_tool=source_tool,
            source_dir=source_dir,
            read_prior_text=False,
        )

        update_state_n_way(state, pair_id, info.kind, paths, self.agentic_tools)
        logging.info(
            "Adopted from %s: pair_id=%s paths=%s",
            source_tool, pair_id, {k: str(v) for k, v in paths.items()},
        )
        return True

    # ---------- N-way sync ----------

    def _sync_from_agentic_tool(
        self,
        pair_id: str,
        source_tool: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
    ) -> bool:
        """Project the source tool's bytes to every other available tool.

        Tools that are available-but-absent-from-info (a newly available
        antigravity tool whose dir was just provisioned, for example) are
        extended to in the same poll per v0.4 plan §5 first bullet — the
        canonical from the source is rendered onto a fresh slug-derived path
        on the target.
        """
        prior_canonical = load_canonical(self.state_dir, pair_id)
        source_info = info.agentic_tools[source_tool]
        source_spec = self.agentic_tools[source_tool]
        source_io = source_spec.io[info.kind]
        text = read_artifact_text(source_io, source_info.path)
        canonical = source_io.parse(text, prior_canonical)
        canonical["pair_id"] = pair_id
        save_canonical(self.state_dir, pair_id, canonical)

        source_dir = source_info.path if source_io.storage == "directory_skill" else None
        paths = self._project_to_other_tools(
            pair_id=pair_id,
            canonical=canonical,
            info=info,
            source_tool=source_tool,
            source_dir=source_dir,
            read_prior_text=True,
        )

        update_state_n_way(state, pair_id, info.kind, paths, self.agentic_tools)
        logging.info("Synced from %s: pair_id=%s", source_tool, pair_id)
        return True

    def _project_to_other_tools(
        self,
        *,
        pair_id: str,
        canonical: dict[str, Any],
        info: CustomizationArtifactInfo,
        source_tool: str,
        source_dir: Path | None,
        read_prior_text: bool,
    ) -> dict[str, Path]:
        """Render `canonical` onto every available tool except `source_tool`.

        `read_prior_text=True` (the sync path) re-reads each target's existing
        bytes so the renderer can preserve user frontmatter ordering;
        `read_prior_text=False` (the adoption path) skips that read since the
        target either doesn't exist yet or hasn't been claimed by this pair.
        """
        paths: dict[str, Path] = {source_tool: info.agentic_tools[source_tool].path}
        for tool_name in self._available_participating_tools(info.kind):
            if tool_name == source_tool:
                continue
            target_info = info.agentic_tools.get(tool_name)
            target_spec = self.agentic_tools[tool_name]
            existing_path: Path | None = None
            prior_text: str | None = None
            if target_info is not None:
                existing_path = target_info.path
                if read_prior_text:
                    target_io = target_spec.io[info.kind]
                    try:
                        prior_text = read_artifact_text(target_io, target_info.path)
                    except (OSError, UnicodeDecodeError) as exc:
                        logging.warning(
                            "Could not read prior text at %s for pair_id=%s; "
                            "rendered output will not preserve existing frontmatter "
                            "formatting (%s: %s)",
                            target_info.path, pair_id, type(exc).__name__, exc,
                        )
                        prior_text = None
            paths[tool_name] = render_to_agentic_tool(
                self.config,
                target_spec,
                info.kind,
                canonical,
                existing_path=existing_path,
                prior_text=prior_text,
                source_dir=source_dir,
            )
        return paths

    # ---------- extend ----------

    def _extend_to_new_tools(
        self,
        pair_id: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
        target_tools: list[str],
    ) -> bool:
        """Render the canonical to newly-participating tools (§5 first bullet)."""
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

        paths: dict[str, Path] = {}
        for tool_name in target_tools:
            target_spec = self.agentic_tools[tool_name]
            paths[tool_name] = render_to_agentic_tool(
                self.config,
                target_spec,
                info.kind,
                canonical,
                existing_path=None,
                prior_text=None,
                source_dir=source_dir,
            )
        update_state_n_way(state, pair_id, info.kind, paths, self.agentic_tools)
        logging.info(
            "Extended to newly available tools: pair_id=%s tools=%s",
            pair_id, target_tools,
        )
        return True

    # ---------- conflict resolution ----------

    def _resolve_conflict_n_way(
        self,
        pair_id: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
        changed_tools: list[str],
    ) -> bool:
        """Pick argmax(mtime) over changed tools; archive losers' bytes; project."""
        winner = self._pick_winner(changed_tools, info)
        for tool in changed_tools:
            if tool == winner:
                continue
            archive.archive_copy(
                self.state_dir, pair_id, tool, info.agentic_tools[tool].path
            )
        logging.warning(
            "Conflict resolved (%s wins): pair_id=%s mtimes=%s",
            winner, pair_id,
            {t: info.agentic_tools[t].mtime for t in changed_tools},
        )
        return self._sync_from_agentic_tool(pair_id, winner, info, state)

    def _pick_winner(
        self, tools: Iterable[str], info: CustomizationArtifactInfo
    ) -> str:
        """argmax(mtime) over `tools`, with alphabetical tiebreak (e.g. claude < codex)."""
        return sorted(
            tools,
            key=lambda t: (-info.agentic_tools[t].mtime, t),
        )[0]

    # ---------- removal propagation ----------

    def _propagate_removal(
        self,
        pair_id: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
        missing_tools: list[str],
        survivors: list[str],
    ) -> bool:
        """An available tool removed the artifact: archive then delete each
        available survivor, then drop their state entries.

        State entries for ``unavailable`` tools are preserved (US-11 AC-4). If
        every entry in the pair would be dropped, the pair_id itself is
        dropped. Abort if archiving any survivor fails — survivors stay on
        disk and the state entry is preserved so the next poll retries.
        """
        for tool in survivors:
            survivor_path = info.agentic_tools[tool].path
            if not survivor_path.exists():
                continue
            try:
                archive.archive_move(self.state_dir, pair_id, tool, survivor_path)
            except Exception:
                logging.exception(
                    "Archive-then-remove aborted: pair_id=%s survivor=%s",
                    pair_id, tool,
                )
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

    # ---------- internals ----------

    def _available_participating_tools(self, kind: str) -> list[str]:
        """Participating tools whose status is currently `available`."""
        return [
            name for name, spec in self.agentic_tools.items()
            if kind in spec.supported_customization_types
            and self.tool_status.is_available(name)
        ]
