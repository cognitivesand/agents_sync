"""Canonical projection: heal / extend / re-project a managed pair.

Three sibling operations that each render a pair's canonical document onto a set
of available tools, differing only in which tools they target and how they
archive:

- ``_extend_to_new_tools``   — project to newly-available tools, sourcing skill
  bytes from an existing tool copy; archives prior shared-slot bytes after.
- ``project_from_canonical`` — heal: project a stub (zero tools) or glitch-vanished
  pair (US-11 AC-8/AC-9, NFR-16); canonical-only, no archive.
- ``reproject_canonical``    — re-project an out-of-band canonical change (FR-14)
  onto the tools that already hold it, archiving each displaced file first.

Extracted from ``engine.py`` as a composed mixin (the established pattern, like
``PrivacyGateMixin`` / ``RemovalPropagatorMixin``). Relies on ``config``,
``state_dir``, ``agentic_tools``, ``_available_participating_tools``,
``_is_reserved_target_name``, ``_archive_prior_slot_results`` and
``_archive_existing_tool_bytes`` provided by :class:`AdoptionEngine`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents_sync.canonical import (
    canonical_metadata,
    load_canonical,
    save_canonical,
    set_canonical_metadata,
)
from agents_sync.rendering import render_to_agentic_tool, update_state_n_way
from agents_sync.state import CustomizationArtifactState
from agents_sync.sync_types import CustomizationArtifactInfo, RenderResult

if TYPE_CHECKING:
    from agents_sync.adoption._host import _AdoptionHost

    _AdoptionHostBase = _AdoptionHost
else:
    _AdoptionHostBase = object


class CanonicalProjectionMixin(_AdoptionHostBase):
    """Heal / extend / re-project a managed pair from its canonical document."""

    def _ensure_canonical_metadata(self, pair_id: str, canonical: dict[str, Any]) -> None:
        if canonical_metadata(canonical):
            return
        set_canonical_metadata(canonical, last_modified=0.0, generation=0)
        save_canonical(self.state_dir, pair_id, canonical)

    def _render_canonical_one(
        self,
        pair_id: str,
        kind: str,
        canonical: dict[str, Any],
        tool_name: str,
        *,
        existing_path: Path | None = None,
        source_dir: Path | None = None,
        existing_slot: str | None = None,
        check_reserved: bool = True,
    ) -> RenderResult | None:
        """Render one tool's projection of ``canonical``. Returns ``None`` when
        the target is a reserved name that must be skipped (only checked when
        ``check_reserved`` — ``reproject_canonical`` targets already-owned files
        that passed the check at adoption, so it does not re-check)."""
        target_spec = self.agentic_tools[tool_name]
        if check_reserved and self._is_reserved_target_name(target_spec, kind, canonical):
            logging.warning(
                "Reserved name skipped on projection: pair_id=%s tool=%s name=%s",
                pair_id,
                tool_name,
                canonical.get("name"),
            )
            return None
        return render_to_agentic_tool(
            self.config,
            target_spec,
            kind,
            canonical,
            existing_path=existing_path,
            prior_text=None,
            source_dir=source_dir,
            existing_slot=existing_slot,
        )

    def _extend_to_new_tools(
        self,
        pair_id: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
        target_tools: list[str],
    ) -> bool:
        canonical = load_canonical(self.state_dir, pair_id)
        if canonical is None:
            logging.error("Cannot extend pair_id=%s: canonical document missing", pair_id)
            return False
        self._ensure_canonical_metadata(pair_id, canonical)

        source_dir: Path | None = None
        if info.kind == "skill":
            for _tool_name, tool_info in info.agentic_tools.items():
                if tool_info.path.exists():
                    source_dir = tool_info.path
                    break

        results: dict[str, RenderResult] = {}
        for tool_name in target_tools:
            result = self._render_canonical_one(
                pair_id, info.kind, canonical, tool_name, source_dir=source_dir
            )
            if result is not None:
                results[tool_name] = result
        self._archive_prior_slot_results(pair_id, info.kind, results)
        update_state_n_way(state, pair_id, info.kind, results, self.agentic_tools)
        logging.info(
            "Extended to newly available tools: pair_id=%s tools=%s",
            pair_id,
            target_tools,
        )
        return True

    def project_from_canonical(
        self,
        pair_id: str,
        state: dict[str, CustomizationArtifactState],
        target_tools: list[str] | None = None,
    ) -> bool:
        """Heal: project a managed pair's canonical onto supporting, available
        tools (US-11 AC-8/AC-9, NFR-16).

        Unlike ``_extend_to_new_tools`` this needs no on-disk ``info`` — it is
        the path for a pair present on **zero** tools (a freshly imported stub)
        or for glitch-vanished tools re-projected per US-11 AC-9. With
        ``target_tools=None`` it projects onto every supporting available tool
        not yet recorded (the stub case); pass an explicit list to re-heal
        specific (already-recorded) tools. Rendering is canonical-only
        (``source_dir=None``); ``update_state_n_way`` records the post-write
        on-disk digest so the next poll re-projects nothing (NFR-05).
        """
        ps = state[pair_id]
        canonical = load_canonical(self.state_dir, pair_id)
        if canonical is None:
            logging.error("Cannot project pair_id=%s: canonical document missing", pair_id)
            return False
        self._ensure_canonical_metadata(pair_id, canonical)
        kind = ps.kind
        if target_tools is None:
            target_tools = [
                t for t in self._available_participating_tools(kind) if t not in ps.agentic_tools
            ]
        results: dict[str, RenderResult] = {}
        for tool_name in target_tools:
            result = self._render_canonical_one(pair_id, kind, canonical, tool_name)
            if result is not None:
                results[tool_name] = result
        if not results:
            return False
        update_state_n_way(state, pair_id, kind, results, self.agentic_tools)
        logging.info(
            "Projected from canonical: pair_id=%s tools=%s",
            pair_id,
            sorted(results),
        )
        return True

    def reproject_canonical(
        self,
        pair_id: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
    ) -> bool:
        """Re-project a canonical that changed out of band (FR-14) onto the tools
        that currently hold it, archiving their displaced bytes first (NFR-01).

        Unlike the stub heal (``project_from_canonical``), the tools already hold
        an owned file, so rendering targets the existing path (overwrite) rather
        than a fresh slug path.
        """
        canonical = load_canonical(self.state_dir, pair_id)
        if canonical is None:
            logging.error("Cannot re-project pair_id=%s: canonical missing", pair_id)
            return False
        self._ensure_canonical_metadata(pair_id, canonical)
        present = [
            t for t in self._available_participating_tools(info.kind) if t in info.agentic_tools
        ]
        results: dict[str, RenderResult] = {}
        for tool in present:
            self._archive_existing_tool_bytes(pair_id, info.kind, tool, info)
            tool_info = info.agentic_tools[tool]
            result = self._render_canonical_one(
                pair_id,
                info.kind,
                canonical,
                tool,
                existing_path=tool_info.path,
                existing_slot=tool_info.slot,
                check_reserved=False,
            )
            if result is not None:
                results[tool] = result
        if not results:
            return False
        update_state_n_way(state, pair_id, info.kind, results, self.agentic_tools)
        logging.info("Canonical re-projected (FR-14): pair_id=%s tools=%s", pair_id, present)
        return True
