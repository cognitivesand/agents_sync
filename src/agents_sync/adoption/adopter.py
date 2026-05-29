"""Adoption + N-way sync.

A pair's first poll (no state entry) runs ``_adopt_new_pair``: pick
the lexicographically-first / latest tool, parse it, inject the
pair_id if newly minted, and project the canonical to every other
participating tool. Subsequent polls with exactly one changed tool
run ``_sync_from_agentic_tool``, which re-parses the changed tool's
bytes against the prior canonical and projects to the rest.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agents_sync import archive
from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    SharedKeyedMapLayout,
)
from agents_sync.canonical import load_canonical, save_canonical
from agents_sync.config import expand_path
from agents_sync.rendering import (
    read_artifact_text,
    render_to_agentic_tool,
    update_state_n_way,
    write_artifact_inplace,
)
from agents_sync.state import CustomizationArtifactState
from agents_sync.sync_types import (
    AgenticToolInfo,
    CustomizationArtifactInfo,
    RenderResult,
)


class AdopterMixin:
    """Adopt-new-pair and N-way sync. Relies on ``self.config``,
    ``self.agentic_tools``, ``self.state_dir``, and methods from
    :class:`AdoptionEngine` (``_pick_winner``,
    ``_available_participating_tools``, etc.)."""

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
        canonical["pair_id"] = pair_id

        if not source_info.pair_id_present:
            self._archive_source_before_write(
                pair_id, source_tool, source_io, source_info, text,
            )
            write_artifact_inplace(
                source_io, source_info.path,
                source_io.render(canonical, text),
                slot=source_info.slot,
            )

        save_canonical(self.state_dir, pair_id, canonical)

        source_dir = source_info.path if source_io.storage == "directory_skill" else None
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
        logging.info(
            "Adopted from %s: pair_id=%s paths=%s",
            source_tool, pair_id,
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
                self.state_dir, pair_id, source_tool,
                slot_name=str(source_info.slot),
                extension=source_io.file_layout.file_suffix,
                content=prior_text,
            )
            return
        archive.archive_copy(
            self.state_dir, pair_id, source_tool, source_info.path,
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
        canonical["pair_id"] = pair_id
        save_canonical(self.state_dir, pair_id, canonical)

        source_dir = source_info.path if source_io.storage == "directory_skill" else None
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
                path=source_info.path, slot=source_info.slot,
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
            if target_info is not None and self._target_is_private(
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
                target_io, target_info.path, slot=target_info.slot,
            )
        except (OSError, UnicodeDecodeError) as exc:
            logging.warning(
                "Could not read prior text at %s for pair_id=%s; "
                "rendered output will not preserve existing frontmatter "
                "formatting (%s: %s)",
                target_info.path, pair_id, type(exc).__name__, exc,
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
                self.state_dir, pair_id, tool,
                slot_name=str(result.slot),
                extension=extension or ".json",
                content=result.prior_slot_text,
            )

    def _pick_winner(
        self, tools: Iterable[str], info: CustomizationArtifactInfo
    ) -> str:
        """argmax(mtime) over ``tools``, alphabetical tiebreak (e.g. claude < codex)."""
        return sorted(
            tools,
            key=lambda t: (-info.agentic_tools[t].mtime, t),
        )[0]
