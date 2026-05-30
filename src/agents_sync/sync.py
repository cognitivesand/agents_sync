"""Per-pair sync algorithm — Phase 3 (bidirectional with mtime conflict resolution)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml.error import YAMLError

from agents_sync import archive
from agents_sync.adoption import AdoptionEngine
from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    SharedKeyedMapLayout,
    default_agentic_tools,
)
from agents_sync.canonical import is_private
from agents_sync.config import (
    expand_path,
    normalize_config,
    prepare_state_storage,
    validate_config,
)
from agents_sync.discovery import DiscoveryWalker
from agents_sync.markdown_yaml_metadata_block import AdapterParseError
from agents_sync.mcp_secret_policy import reset_mcp_secret_warning_cache
from agents_sync.rendering import read_artifact_text, slot_aware_collision_key
from agents_sync.state import (
    CustomizationArtifactState,
    load_state,
    save_state,
    target_slug,
)
from agents_sync.sync_types import AgenticToolInfo, CustomizationArtifactInfo
from agents_sync.tool_status import ToolStatusTracker


@dataclass(frozen=True, eq=False)
class SyncResult:
    """Outcome of one ``Syncer.sync_once`` call.

    - ``changed`` — number of pairs whose bytes or state advanced this poll.
    - ``failed`` — pair_ids whose per-pair processing raised (logged at
      exception level; daemon supervisor can count consecutive failures).
    - ``blocked`` — pair_ids elided from processing because of an unresolved
      collision (managed-owner, unmanaged-slug, or shared-keyed-map slot).
    """

    changed: int = 0
    failed: tuple[str, ...] = field(default_factory=tuple)
    blocked: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "failed", tuple(self.failed))
        object.__setattr__(self, "blocked", tuple(self.blocked))

    def __bool__(self) -> bool:
        """A poll counts as truthy when something changed (back-compat)."""
        return self.changed != 0

    def __int__(self) -> int:
        """Legacy callers comparing the return as an int still work."""
        return self.changed

    def __eq__(self, other: object) -> bool:
        """Back-compat for older tests/callers that compared sync_once() to int."""
        if isinstance(other, SyncResult):
            return (
                self.changed,
                self.failed,
                self.blocked,
            ) == (
                other.changed,
                other.failed,
                other.blocked,
            )
        if isinstance(other, int):
            return self.changed == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.changed, self.failed, self.blocked))


class Syncer:
    def __init__(
        self,
        config: dict[str, Any],
        agentic_tools: dict[str, AgenticToolSpec] | None = None,
    ) -> None:
        self.config = normalize_config(config, source="syncer", warn_deprecated=False)
        validate_config(self.config)
        self.agentic_tools: dict[str, AgenticToolSpec] = (
            agentic_tools if agentic_tools is not None else default_agentic_tools(self.config)
        )
        self.state_dir = prepare_state_storage(self.config)
        self._blocked_pair_ids: set[str] = set()
        self.tool_status = ToolStatusTracker(self.config, self.agentic_tools)
        self.discovery = DiscoveryWalker(self.config, self.agentic_tools, self.tool_status)
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

    def sync_once(self) -> SyncResult:
        reset_mcp_secret_warning_cache()
        self.tool_status.refresh()
        state = load_state(self.state_dir)
        discovery, self._blocked_pair_ids = self.discovery.discover(state)
        self._reconcile_new_groups(discovery, state)
        self._blocked_pair_ids |= self.discovery.block_target_collisions(discovery, state)
        glitch_tools = self._glitch_tools(discovery, state)
        changed = 0
        failed: list[str] = []

        for pair_id, info in discovery.items():
            try:
                if self.adoption.process_pair(pair_id, info, state, glitch_tools):
                    changed += 1
            except (AdapterParseError, YAMLError) as exc:
                # US-03 AC-11 / FR-11: a managed artifact whose content cannot be
                # parsed is frozen, not failed — never synced, never removed
                # (it stays in `discovery`, so the removal loop skips it), until
                # the user repairs it. Structured warning per NFR-13.
                locations = ", ".join(
                    f"{tool}:{ti.path}" for tool, ti in info.agentic_tools.items()
                )
                logging.warning(
                    "Frozen — unparseable artifact content: pair_id=%s artifacts=[%s] cause=%s",
                    pair_id,
                    locations,
                    exc,
                )
                self._blocked_pair_ids.add(pair_id)
            except Exception:
                logging.exception("Failed to sync pair: pair_id=%s", pair_id)
                failed.append(pair_id)

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
            if not ps.agentic_tools:
                # Never-projected stub (a freshly imported canonical on zero
                # tools): heal it onto every supporting available tool from the
                # authoritative canonical (US-11 AC-8, NFR-16) — not a removal.
                try:
                    if self.adoption.project_from_canonical(pair_id, state):
                        changed += 1
                except Exception:
                    logging.exception("Failed to project pair: pair_id=%s", pair_id)
                    failed.append(pair_id)
                continue
            if not any(self.tool_status.is_kind_available(t, ps.kind) for t in ps.agentic_tools):
                continue
            try:
                if self.adoption.propagate_orphan_state(pair_id, state, glitch_tools):
                    changed += 1
            except Exception:
                logging.exception("Failed to handle orphan state: pair_id=%s", pair_id)
                failed.append(pair_id)

        save_state(self.state_dir, state)
        result = SyncResult(
            changed=changed,
            failed=tuple(failed),
            blocked=tuple(sorted(self._blocked_pair_ids)),
        )
        logging.info(
            "Sync poll complete: changed=%d failed=%d blocked=%d",
            result.changed,
            len(result.failed),
            len(result.blocked),
        )
        return result

    def _glitch_tools(
        self,
        discovery: dict[str, CustomizationArtifactInfo],
        state: dict[str, CustomizationArtifactState],
    ) -> frozenset[str]:
        """Tools that lost **two or more** of their recorded artifacts this poll.

        A bulk disappearance from one available tool is a glitch (uninstall,
        unmount, mid-write), not a deliberate deletion (US-11 AC-9). Per
        available tool, count the managed pairs that `state` records for it but
        that the poll shows absent on it; >=2 flags the tool. Blocked pairs are
        excluded (their absence is not a removal signal).
        """
        vanished: dict[str, set[str]] = {}
        for pair_id, ps in state.items():
            if pair_id in self._blocked_pair_ids:
                continue
            info = discovery.get(pair_id)
            for tool in ps.agentic_tools:
                if not self.tool_status.is_kind_available(tool, ps.kind):
                    continue
                if info is None or tool not in info.agentic_tools:
                    vanished.setdefault(tool, set()).add(pair_id)
        return frozenset(t for t, pids in vanished.items() if len(pids) >= 2)

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
        new_pair_ids = self._collect_new_pair_ids(discovery)
        if not new_pair_ids:
            return

        groups, source_tool_by_pair = self._group_new_pairs_by_slug(
            new_pair_ids,
            discovery,
        )

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

            storage_targets = {
                slot_aware_collision_key(
                    discovery[p].agentic_tools[source_tool_by_pair[p]].path,
                    discovery[p].agentic_tools[source_tool_by_pair[p]].slot,
                )
                for p in group_pair_ids
            }
            if len(storage_targets) != len(group_pair_ids):
                continue
            self._merge_new_artifact_group(
                discovery, kind, slug, group_pair_ids, source_tool_by_pair
            )

    def _collect_new_pair_ids(
        self,
        discovery: dict[str, CustomizationArtifactInfo],
    ) -> list[str]:
        """Return pair_ids whose every tool-side observation lacks a pair_id —
        i.e. the artifact has never been managed before. Sole eligibility for
        the §5.5 group-and-merge phase."""
        return [
            pair_id
            for pair_id, info in discovery.items()
            if info.agentic_tools
            and all(not t.pair_id_present for t in info.agentic_tools.values())
        ]

    def _group_new_pairs_by_slug(
        self,
        new_pair_ids: list[str],
        discovery: dict[str, CustomizationArtifactInfo],
    ) -> tuple[dict[tuple[str, str], list[str]], dict[str, str]]:
        """Group every new pair by (customization_type, target_slug) so multi-
        tool duplicates can be detected. Returns:

        - ``groups``: ``{(kind, slug): [pair_id, ...]}``.
        - ``source_tool_by_pair``: ``{pair_id: tool_name}`` (every new pair has
          exactly one tool by construction).

        Private artifacts are dropped from ``discovery`` here so neither the
        grouping nor any downstream projection sees them. Parse failures are
        logged and skipped — they cannot participate in a merge group.
        """
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
                text = read_artifact_text(io, tool_info.path, slot=tool_info.slot)
                canonical = io.parse(
                    text,
                    None,
                    artifact_path=tool_info.path,
                    artifact_root=root,
                )
            except Exception:
                logging.exception(
                    "Reconcile: cannot parse for grouping: pair_id=%s tool=%s path=%s",
                    pair_id,
                    tool_name,
                    tool_info.path,
                )
                continue
            if is_private(canonical):
                discovery.pop(pair_id, None)
                continue
            slug = target_slug(canonical["name"])
            groups.setdefault((info.kind, slug), []).append(pair_id)
            source_tool_by_pair[pair_id] = tool_name
        return groups, source_tool_by_pair

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
            loser_info = tool_info_for(p)
            loser_path = loser_info.path
            loser_io = self.agentic_tools[loser_tool].io[kind]
            try:
                if isinstance(loser_io.file_layout, SharedKeyedMapLayout):
                    loser_text = read_artifact_text(
                        loser_io,
                        loser_path,
                        slot=loser_info.slot,
                    )
                    archive.archive_text(
                        self.state_dir,
                        merged_pair_id,
                        loser_tool,
                        slot_name=str(loser_info.slot),
                        extension=loser_io.file_layout.file_suffix,
                        content=loser_text,
                    )
                else:
                    archive.archive_copy(self.state_dir, merged_pair_id, loser_tool, loser_path)
            except Exception:
                logging.exception(
                    "Reconcile: archive failed; aborting merge kind=%s slug=%s pair_id=%s tool=%s",
                    kind,
                    slug,
                    p,
                    loser_tool,
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
            "Reconciled new-artifact group: kind=%s slug=%s pair_id=%s winner=%s merged_tools=%s",
            kind,
            slug,
            merged_pair_id,
            source_tool_by_pair[winner_pair_id],
            list(merged_tools.keys()),
        )
