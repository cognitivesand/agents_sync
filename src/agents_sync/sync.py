"""Per-pair sync algorithm — Phase 3 (bidirectional with mtime conflict resolution)."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents_sync import archive
from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    default_agentic_tools,
)
from agents_sync.canonical import (
    load_canonical,
    new_pair_id,
    save_canonical,
)
from agents_sync.config import expand_path
from agents_sync.config import validate_config
from agents_sync.identity import InvalidPairId, validate_pair_id
from agents_sync.rendering import (
    path_collision_key,
    render_to_agentic_tool,
    update_state_n_way,
    write_artifact_inplace,
)
from agents_sync.tool_status import ToolStatusTracker
from agents_sync.state import (
    CustomizationArtifactState,
    load_state,
    save_state,
    sha256_file,
    sha256_tree,
    target_slug,
)


@dataclass
class AgenticToolInfo:
    path: Path
    digest: str
    mtime: float
    pair_id_present: bool


@dataclass
class CustomizationArtifactInfo:
    kind: str
    agentic_tools: dict[str, AgenticToolInfo] = field(default_factory=dict)


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
        self.claude_agents_dir = expand_path(config["claude_agents_dir"])
        self.claude_skills_dir = expand_path(config["claude_skills_dir"])
        self.codex_skills_dir = expand_path(config["codex_skills_dir"])
        self.state_dir = expand_path(config["state_path"]).parent
        self._blocked_pair_ids: set[str] = set()
        self.tool_status = ToolStatusTracker(self.config, self.agentic_tools)
        # Best-effort: create each enabled tool's roots once at startup. This
        # turns "fresh-install, dir-not-yet-materialised" into `available` on
        # the first poll, instead of US-11 `unavailable` (which would silently
        # strand the user's library). Mid-life loss of a root still flips the
        # tool to `unavailable` per US-11 AC-2.
        self.tool_status.ensure_roots()

    def _available_participating_tools(self, kind: str) -> list[str]:
        """Participating tools whose status is currently `available`."""
        return [
            name for name in self._participating_tools(kind)
            if self.tool_status.is_available(name)
        ]

    # ---------- discovery ----------

    def _discover(self, state: dict[str, CustomizationArtifactState]) -> dict[str, CustomizationArtifactInfo]:
        """Walk every (agentic_tool, customization_type) cell in the registry.

        For each cell, enumerate on-disk artifacts under that root and dispatch
        to _add_agentic_tool_artifact. Tools whose status is not `available`
        are skipped entirely so unreadable / unmounted / disabled tools never
        appear as removal signals (US-11 AC-4).
        """
        pairs: dict[str, CustomizationArtifactInfo] = {}
        blocked_pair_ids: set[str] = set()

        for tool_name, spec in self.agentic_tools.items():
            if not self.tool_status.is_available(tool_name):
                continue
            for customization_type in sorted(spec.supported_customization_types):
                io = spec.io[customization_type]
                root = expand_path(self.config[spec.config_dir_keys[customization_type]])
                if not root.exists():
                    continue
                for artifact_path in self._enumerate_artifacts(root, io):
                    self._add_agentic_tool_artifact(
                        tool_name,
                        customization_type,
                        artifact_path,
                        io,
                        pairs,
                        blocked_pair_ids,
                        state,
                    )

        # A pair_id can be blocked (e.g. invalid id on one tool) after another
        # tool has already inserted its valid entry into `pairs`. Evict those
        # late-blocked entries so per-pair processing doesn't see a partial
        # info and mistake the blocked tools for removed.
        for pair_id in blocked_pair_ids:
            pairs.pop(pair_id, None)
        self._blocked_pair_ids = blocked_pair_ids
        return pairs

    def _enumerate_artifacts(self, root: Path, io: CustomizationTypeIO) -> list[Path]:
        """Return the on-disk artifact paths under `root` for this IO cell.

        For single_file storage, returns the matching files. For
        directory_skill storage, returns the parent directory of each
        `*/SKILL.md` so callers get the artifact path (not the metadata file).
        """
        if io.storage == "single_file":
            return sorted(
                p for p in root.glob(f"*{io.file_suffix}")
                if p.is_file() and not p.name.startswith(".")
            )
        if io.storage == "directory_skill":
            return sorted(
                p.parent for p in root.glob("*/SKILL.md")
                if not p.parent.name.startswith(".")
            )
        raise ValueError(f"Unknown storage shape: {io.storage}")

    def _add_agentic_tool_artifact(
        self,
        tool_name: str,
        customization_type: str,
        path: Path,
        io: CustomizationTypeIO,
        pairs: dict[str, CustomizationArtifactInfo],
        blocked_pair_ids: set[str],
        state: dict[str, CustomizationArtifactState],
    ) -> None:
        """Read one on-disk artifact, validate, and register it under its pair_id."""
        try:
            text = self._read_artifact_text(io, path)
        except Exception:
            logging.exception(
                "Cannot read %s %s: path=%s",
                tool_name,
                customization_type,
                path,
            )
            self._block_state_owner(path, state, blocked_pair_ids)
            return
        pair_id = io.extract_pair_id(text)
        present = pair_id is not None
        if pair_id is None:
            pair_id = new_pair_id()
        else:
            try:
                validate_pair_id(pair_id)
            except InvalidPairId:
                logging.error(
                    "Invalid pair_id in %s %s: path=%s",
                    tool_name,
                    customization_type,
                    path,
                )
                self._block_state_owner(path, state, blocked_pair_ids)
                return
        digest = sha256_file(path) if io.storage == "single_file" else sha256_tree(path)
        info = AgenticToolInfo(path, digest, path.stat().st_mtime, present)
        self._insert_agentic_tool(
            pair_id, customization_type, tool_name, info, pairs, blocked_pair_ids
        )

    def _read_artifact_text(self, io: CustomizationTypeIO, path: Path) -> str:
        """Read the artifact-metadata text for an artifact at `path`."""
        if io.storage == "single_file":
            return path.read_text(encoding="utf-8")
        return (path / "SKILL.md").read_text(encoding="utf-8")

    def _insert_agentic_tool(
        self,
        pair_id: str,
        kind: str,
        tool_name: str,
        info: AgenticToolInfo,
        pairs: dict[str, CustomizationArtifactInfo],
        blocked_pair_ids: set[str],
    ) -> None:
        if pair_id in blocked_pair_ids:
            return
        pair = pairs.get(pair_id)
        if pair is None:
            pair = CustomizationArtifactInfo(kind=kind)
            pairs[pair_id] = pair
        elif pair.kind != kind:
            logging.error("pair_id reused across kinds: pair_id=%s", pair_id)
            pairs.pop(pair_id, None)
            blocked_pair_ids.add(pair_id)
            return

        if tool_name in pair.agentic_tools:
            logging.error(
                "duplicate pair_id on %s agentic tool: pair_id=%s",
                tool_name,
                pair_id,
            )
            pairs.pop(pair_id, None)
            blocked_pair_ids.add(pair_id)
            return

        pair.agentic_tools[tool_name] = info

    def _block_state_owner(
        self,
        path: Path,
        state: dict[str, CustomizationArtifactState],
        blocked_pair_ids: set[str],
    ) -> None:
        owner = self._state_owner_for_path(path, state)
        if owner is not None:
            blocked_pair_ids.add(owner)

    # ---------- top-level loop ----------

    def sync_once(self) -> int:
        validate_config(self.config)
        self.tool_status.refresh()
        state = load_state(self.state_dir)
        discovery = self._discover(state)
        self._reconcile_new_groups(discovery, state)
        self._block_target_collisions(discovery, state)
        changed = 0

        for pair_id, info in discovery.items():
            try:
                if self._process_pair(pair_id, info, state):
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
                if self._propagate_orphan_state(pair_id, state):
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
            try:
                text = self._read_artifact_text(io, tool_info.path)
                canonical = io.parse(text, None)
            except Exception:
                logging.exception(
                    "Reconcile: cannot parse for grouping: pair_id=%s tool=%s path=%s",
                    pair_id, tool_name, tool_info.path,
                )
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

    def _process_pair(self, pair_id: str, info: CustomizationArtifactInfo, state: dict[str, CustomizationArtifactState]) -> bool:
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
            for tool_name, tool_info in info.agentic_tools.items():
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

    def _participating_tools(self, kind: str) -> list[str]:
        """Tools whose registry supports this customization_type, in deterministic order."""
        return [
            name for name, spec in self.agentic_tools.items()
            if kind in spec.supported_customization_types
        ]

    def _block_target_collisions(
        self,
        discovery: dict[str, CustomizationArtifactInfo],
        state: dict[str, CustomizationArtifactState],
    ) -> None:
        targets: dict[str, list[str]] = {}
        target_display: dict[str, Path] = {}
        blocked: set[str] = set()

        for pair_id, info in discovery.items():
            if pair_id in state:
                continue
            try:
                planned_targets = self._planned_adoption_targets(info)
            except Exception:
                logging.exception("Cannot plan adoption target: pair_id=%s", pair_id)
                blocked.add(pair_id)
                continue
            for target in planned_targets:
                target_key = path_collision_key(target)
                targets.setdefault(target_key, []).append(pair_id)
                target_display.setdefault(target_key, target)

                owner = self._state_owner_for_path(target, state)
                if owner is not None and owner != pair_id:
                    logging.error(
                        "Target path collision with managed pair: pair_id=%s owner_pair_id=%s target=%s",
                        pair_id,
                        owner,
                        target,
                    )
                    blocked.add(pair_id)
                elif owner is None and target.exists():
                    logging.error(
                        "Target path collision with unmanaged path: pair_id=%s target=%s",
                        pair_id,
                        target,
                    )
                    blocked.add(pair_id)

        for target_key, pair_ids in targets.items():
            if len(pair_ids) <= 1:
                continue
            logging.error(
                "Target path collision: target=%s pair_ids=%s",
                target_display[target_key],
                pair_ids,
            )
            blocked.update(pair_ids)

        for pair_id in blocked:
            discovery.pop(pair_id, None)
            self._blocked_pair_ids.add(pair_id)

    def _planned_adoption_targets(self, info: CustomizationArtifactInfo) -> list[Path]:
        """Return target paths adoption would write on tools that don't yet hold the artifact.

        If every available participating tool already has a copy of the
        artifact, returns []. Otherwise, parses one present tool's bytes to
        compute the slug, and builds the slug-derived target for each absent
        available tool. Disabled / unavailable tools never figure in adoption
        targets and therefore never participate in collision blocking.
        """
        participating = self._available_participating_tools(info.kind)
        missing = [t for t in participating if t not in info.agentic_tools]
        if not missing:
            return []
        if not info.agentic_tools:
            return []
        # Deterministic source pick: alphabetical first present tool.
        source_tool = sorted(info.agentic_tools.keys())[0]
        source_info = info.agentic_tools[source_tool]
        source_io = self.agentic_tools[source_tool].io[info.kind]
        text = self._read_artifact_text(source_io, source_info.path)
        canonical = source_io.parse(text, None)
        slug = target_slug(canonical["name"])
        targets: list[Path] = []
        for tool_name in missing:
            spec = self.agentic_tools[tool_name]
            io = spec.io[info.kind]
            root = expand_path(self.config[spec.config_dir_keys[info.kind]])
            if io.storage == "single_file":
                targets.append(root / f"{slug}{io.file_suffix}")
            else:
                targets.append(root / slug)
        return targets

    def _state_owner_for_path(
        self,
        path: Path,
        state: dict[str, CustomizationArtifactState],
    ) -> str | None:
        target_key = path_collision_key(path)
        for pair_id, pair_state in state.items():
            for tool_state in pair_state.agentic_tools.values():
                if path_collision_key(Path(tool_state.path)) == target_key:
                    return pair_id
        return None

    # ---------- adoption ----------

    def _adopt_new_pair(self, pair_id: str, info: CustomizationArtifactInfo, state: dict[str, CustomizationArtifactState]) -> bool:
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
        text = self._read_artifact_text(source_io, source_info.path)
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
        text = self._read_artifact_text(source_io, source_info.path)
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
                        prior_text = self._read_artifact_text(target_io, target_info.path)
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
            winner,
            pair_id,
            {t: info.agentic_tools[t].mtime for t in changed_tools},
        )
        return self._sync_from_agentic_tool(pair_id, winner, info, state)

    def _pick_winner(self, tools: "Iterable[str]", info: CustomizationArtifactInfo) -> str:
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

        State entries for `unavailable` tools are preserved (US-11 AC-4). If
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

    def _propagate_orphan_state(self, pair_id: str, state: dict[str, CustomizationArtifactState]) -> bool:
        """pair_id is in state but no available tool surfaced it this poll.

        Entries for `available` tools are dropped (those tools removed the
        artifact). Entries for `unavailable` tools are preserved verbatim
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

