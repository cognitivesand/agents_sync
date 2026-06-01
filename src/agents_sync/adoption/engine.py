"""AdoptionEngine: per-pair dispatcher plus adopt / sync / conflict / extend.

The orchestrator dispatches one discovered pair to adopt / sync /
conflict-resolve / extend-to-new-tools / removal. Adopt, N-way sync, conflict
resolution and extension are mutually-recursive parts of one per-pair
responsibility and live directly on this class. The two genuinely independent
operations are kept as composed mixins:

- ``privacy_gate``       — fail-closed private-canonical detection (host-free)
- ``removal_propagator`` — archive-then-delete survivors + orphan handling
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agents_sync import archive
from agents_sync.adoption.privacy_gate import PrivacyGateMixin
from agents_sync.adoption.removal_propagator import RemovalPropagatorMixin
from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    DirectorySkillLayout,
    SharedKeyedMapLayout,
    is_reserved_customization_name,
)
from agents_sync.canonical import load_canonical, save_canonical
from agents_sync.config import expand_path
from agents_sync.rendering import (
    read_artifact_text,
    render_to_agentic_tool,
    update_state_n_way,
    write_artifact_inplace,
)
from agents_sync.state import CustomizationArtifactState, save_state
from agents_sync.sync_types import (
    AgenticToolInfo,
    CustomizationArtifactInfo,
    RenderResult,
)
from agents_sync.tool_status import ToolStatusTracker


class AdoptionEngine(
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
        """Tools that can participate in this `kind` right now.

        Gated on kind-level availability (`is_kind_available`), not tool-level:
        a tool whose root for `kind` is unconfigured / missing / unreadable
        cannot hold, sync, be-removed-from, or be-extended-to for this kind, so
        it must never enter the participation set. (Tool-level `is_available`
        let such a cell through — e.g. copilot, available via its CLI surfaces
        but with no VS Code `rules` root — and crashed render on `Path(None)`.)
        """
        return [
            name for name in self.agentic_tools
            if self.tool_status.is_kind_available(name, kind)
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

    # ------------------------------------------------------------------ #
    # Adopt + N-way sync
    #
    # A pair's first poll (no state entry) runs ``_adopt_new_pair``: pick
    # the latest tool, parse it, inject the pair_id if newly minted, and
    # project the canonical to every other participating tool. Subsequent
    # polls with exactly one changed tool run ``_sync_from_agentic_tool``,
    # which re-parses the changed tool's bytes against the prior canonical
    # and projects to the rest.
    # ------------------------------------------------------------------ #

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
        """Parse from ``source_tool``, inject pair_id if newly minted, then
        project the canonical to every other participating tool."""
        source_info = info.agentic_tools[source_tool]
        source_spec = self.agentic_tools[source_tool]
        source_io = source_spec.io[info.kind]
        source_root = expand_path(self.config[source_spec.config_dir_keys[info.kind]])
        text = read_artifact_text(source_io, source_info.path, slot=source_info.slot)
        canonical = source_io.parse(
            text,
            None,
            artifact_path=source_info.path,
            artifact_root=source_root,
        )
        if self._skip_private_canonical(pair_id, source_tool, canonical):
            return False
        if self._skip_framework_specific(pair_id, source_tool, canonical):
            return False
        canonical["pair_id"] = pair_id

        # Persist canonical + source state entry before mutating any on-disk
        # bytes, so a crash mid-adoption leaves a recoverable state entry
        # bound to the injected pair_id (audit: adoption-crash recovery).
        source_result = RenderResult(path=source_info.path, slot=source_info.slot)
        save_canonical(self.state_dir, pair_id, canonical)
        update_state_n_way(
            state,
            pair_id,
            info.kind,
            {source_tool: source_result},
            self.agentic_tools,
            bump=False,
        )
        save_state(self.state_dir, state)

        if not source_info.pair_id_present:
            self._archive_source_before_write(
                pair_id,
                source_tool,
                source_io,
                source_info,
                text,
            )
            write_artifact_inplace(
                source_io,
                source_info.path,
                source_io.render(canonical, text),
                slot=source_info.slot,
            )
            update_state_n_way(
                state,
                pair_id,
                info.kind,
                {source_tool: source_result},
                self.agentic_tools,
                bump=False,
            )
            save_state(self.state_dir, state)

        source_dir = (
            source_info.path
            if isinstance(source_io.file_layout, DirectorySkillLayout)
            else None
        )
        results = self._project_to_other_tools(
            pair_id=pair_id,
            canonical=canonical,
            info=info,
            source_tool=source_tool,
            source_dir=source_dir,
            read_prior_text=False,
        )
        self._archive_prior_slot_results(pair_id, info.kind, results)

        update_state_n_way(state, pair_id, info.kind, results, self.agentic_tools)
        save_state(self.state_dir, state)
        logging.info(
            "Adopted from %s: pair_id=%s paths=%s",
            source_tool,
            pair_id,
            {k: str(v.path) for k, v in results.items()},
        )
        return True

    def _archive_source_before_write(
        self,
        pair_id: str,
        source_tool: str,
        source_io: Any,
        source_info: Any,
        prior_text: str,
    ) -> None:
        """Preserve the source's prior bytes before the engine rewrites
        them. For per-file artifacts the original file is archived
        unchanged; for SharedKeyedMapLayout artifacts the prior slot
        text is archived (the shared file as a whole is never archived,
        only the slot we are about to overwrite)."""
        if isinstance(source_io.file_layout, SharedKeyedMapLayout):
            archive.archive_text(
                self.state_dir,
                pair_id,
                source_tool,
                slot_name=str(source_info.slot),
                extension=source_io.file_layout.file_suffix,
                content=prior_text,
            )
            return
        archive.archive_copy(
            self.state_dir,
            pair_id,
            source_tool,
            source_info.path,
        )

    def _sync_from_agentic_tool(
        self,
        pair_id: str,
        source_tool: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
    ) -> bool:
        """Project the source tool's bytes to every other available tool."""
        prior_canonical = load_canonical(self.state_dir, pair_id)
        source_info = info.agentic_tools[source_tool]
        source_spec = self.agentic_tools[source_tool]
        source_io = source_spec.io[info.kind]
        source_root = expand_path(self.config[source_spec.config_dir_keys[info.kind]])
        text = read_artifact_text(source_io, source_info.path, slot=source_info.slot)
        canonical = source_io.parse(
            text,
            prior_canonical,
            artifact_path=source_info.path,
            artifact_root=source_root,
        )
        if self._skip_private_canonical(pair_id, source_tool, canonical):
            return False
        if self._skip_framework_specific(pair_id, source_tool, canonical):
            return False
        canonical["pair_id"] = pair_id
        save_canonical(self.state_dir, pair_id, canonical)
        if not source_info.pair_id_present:
            self._archive_source_before_write(
                pair_id, source_tool, source_io, source_info, text,
            )
            write_artifact_inplace(
                source_io,
                source_info.path,
                source_io.render(canonical, text),
                slot=source_info.slot,
            )

        source_dir = (
            source_info.path
            if isinstance(source_io.file_layout, DirectorySkillLayout)
            else None
        )
        results = self._project_to_other_tools(
            pair_id=pair_id,
            canonical=canonical,
            info=info,
            source_tool=source_tool,
            source_dir=source_dir,
            read_prior_text=True,
        )
        self._archive_prior_slot_results(pair_id, info.kind, results)

        update_state_n_way(state, pair_id, info.kind, results, self.agentic_tools)
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
    ) -> dict[str, RenderResult]:
        """Render ``canonical`` onto every available tool except ``source_tool``."""
        source_info = info.agentic_tools[source_tool]
        results: dict[str, RenderResult] = {
            source_tool: RenderResult(
                path=source_info.path,
                slot=source_info.slot,
            )
        }
        for tool_name in self._available_participating_tools(info.kind):
            if tool_name == source_tool:
                continue
            target_info = info.agentic_tools.get(tool_name)
            target_spec = self.agentic_tools[tool_name]
            prior_text = self._read_target_prior_text(
                pair_id=pair_id,
                tool_name=tool_name,
                target_spec=target_spec,
                target_info=target_info,
                kind=info.kind,
                read_prior_text=read_prior_text,
            )
            if target_info is not None and self._target_is_protected(
                pair_id,
                tool_name,
                target_spec,
                info.kind,
                target_info.path,
                prior_text,
                target_slot=target_info.slot,
            ):
                continue
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
                existing_path=target_info.path if target_info is not None else None,
                prior_text=prior_text,
                source_dir=source_dir,
                existing_slot=target_info.slot if target_info is not None else None,
                allow_unpaired_existing_slot=(
                    target_info is not None and not target_info.pair_id_present
                ),
            )
        return results

    def _read_target_prior_text(
        self,
        *,
        pair_id: str,
        tool_name: str,
        target_spec: AgenticToolSpec,
        target_info: AgenticToolInfo | None,
        kind: str,
        read_prior_text: bool,
    ) -> str | None:
        """Return the existing on-disk text at ``target_info.path`` (or ``None``)."""
        if target_info is None or not read_prior_text:
            return None
        target_io = target_spec.io[kind]
        try:
            return read_artifact_text(
                target_io,
                target_info.path,
                slot=target_info.slot,
            )
        except (OSError, UnicodeDecodeError) as exc:
            logging.warning(
                "Could not read prior text at %s for pair_id=%s; "
                "rendered output will not preserve existing frontmatter "
                "formatting (%s: %s)",
                target_info.path,
                pair_id,
                type(exc).__name__,
                exc,
                extra={"event": "prior_text_unreadable"},
            )
            return None

    def _archive_prior_slot_results(
        self,
        pair_id: str,
        kind: str,
        results: dict[str, RenderResult],
    ) -> None:
        """Archive keyed-map slots returned by render writes."""
        for tool, result in results.items():
            if result.prior_slot_text is None:
                continue
            tool_io = self.agentic_tools[tool].io[kind]
            extension = (
                tool_io.file_layout.file_suffix
                if isinstance(tool_io.file_layout, SharedKeyedMapLayout)
                else result.path.suffix
            )
            archive.archive_text(
                self.state_dir,
                pair_id,
                tool,
                slot_name=str(result.slot),
                extension=extension or ".json",
                content=result.prior_slot_text,
            )

    def _pick_winner(self, tools: Iterable[str], info: CustomizationArtifactInfo) -> str:
        """argmax(mtime) over ``tools``, alphabetical tiebreak (e.g. claude < codex)."""
        return sorted(
            tools,
            key=lambda t: (-info.agentic_tools[t].mtime, t),
        )[0]

    # ------------------------------------------------------------------ #
    # N-way conflict resolution: pick argmax(mtime), archive losers' bytes.
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # Extend an existing canonical to newly-available tools (v0.4 plan §5).
    # ------------------------------------------------------------------ #

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
