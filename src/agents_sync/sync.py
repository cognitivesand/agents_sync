"""Per-pair sync algorithm — Phase 3 (bidirectional with mtime conflict resolution)."""
from __future__ import annotations

import logging
import os
import shutil
import sys
import unicodedata
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
from agents_sync.filesystem_windows_retry import retry_fs
from agents_sync.identity import InvalidPairId, validate_pair_id
from agents_sync.state import (
    AgenticToolState,
    CustomizationArtifactState,
    atomic_write_text,
    ignored_tree_names,
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


def stage_skill_dir(source: Path, target: Path, skill_md_content: str) -> None:
    """Stage a fresh copy of `source` as `target` and overwrite SKILL.md atomically."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    old = target.with_name(f".{target.name}.old")
    for stale in (tmp, old):
        if stale.exists():
            retry_fs(
                lambda stale=stale: shutil.rmtree(stale),
                operation=f"rmtree {stale}",
            )
    shutil.copytree(source, tmp, ignore=lambda _dir, names: ignored_tree_names(names))
    atomic_write_text(tmp / "SKILL.md", skill_md_content)
    if target.exists():
        retry_fs(
            lambda: target.rename(old),
            operation=f"rename {target} -> {old}",
        )
        try:
            retry_fs(
                lambda: tmp.rename(target),
                operation=f"rename {tmp} -> {target}",
            )
        except Exception:
            retry_fs(
                lambda: old.rename(target),
                operation=f"rollback {old} -> {target}",
            )
            raise
        retry_fs(
            lambda: shutil.rmtree(old),
            operation=f"cleanup {old}",
        )
    else:
        retry_fs(
            lambda: tmp.rename(target),
            operation=f"rename {tmp} -> {target}",
        )


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
        self.codex_agents_dir = expand_path(config["codex_agents_dir"])
        self.codex_skills_dir = expand_path(config["codex_skills_dir"])
        self.state_dir = expand_path(config["state_path"]).parent
        self._blocked_pair_ids: set[str] = set()
        # Per-tool status per US-11: "available" | "unavailable" | "disabled".
        # Empty until the first sync_once: that first poll's _refresh_tool_statuses
        # emits the startup INFO line for every tool.
        self._tool_status: dict[str, str] = {}

    # ---------- per-tool status (US-11) ----------

    def _refresh_tool_statuses(self) -> None:
        """Compute each tool's `available` / `unavailable` / `disabled` status.

        Status rules (US-11):
          - `disabled` ⇒ tool is registered but its enable-flag in config is False.
          - `unavailable` ⇒ tool is enabled but at least one of its
            customization_type roots is missing or unreadable on this poll.
          - `available` ⇒ tool is enabled and every root is reachable.

        Transitions are logged once (AC-5). Steady-state polls are silent.
        """
        new_status: dict[str, str] = {}
        reasons: dict[str, tuple[str, str]] = {}
        for tool_name, spec in self.agentic_tools.items():
            if not self._is_tool_enabled(spec):
                new_status[tool_name] = "disabled"
                continue
            status, reason = self._probe_tool_roots(spec)
            new_status[tool_name] = status
            if reason is not None:
                reasons[tool_name] = reason

        for tool_name, status in new_status.items():
            prev = self._tool_status.get(tool_name)
            if prev == status:
                continue
            self._log_status_transition(tool_name, prev, status, reasons.get(tool_name))
        self._tool_status = new_status

    def _is_tool_enabled(self, spec: AgenticToolSpec) -> bool:
        """Whether a tool's config-side enable-flag is on.

        A tool without `disable_config_key` cannot be disabled — it can only
        become `unavailable` by losing its root. Antigravity's
        `antigravity_enabled = False` is the only opt-out in v0.4.
        """
        if spec.disable_config_key is None:
            return True
        return bool(self.config.get(spec.disable_config_key, True))

    def _probe_tool_roots(self, spec: AgenticToolSpec) -> tuple[str, tuple[str, str] | None]:
        """Return (status, reason_or_None) for one tool's on-disk reachability."""
        for kind, config_key in spec.config_dir_keys.items():
            root = expand_path(self.config[config_key])
            if not root.exists():
                return "unavailable", (str(root), "path does not exist")
            try:
                next(root.iterdir(), None)
            except OSError as exc:
                return "unavailable", (str(root), f"{type(exc).__name__}: {exc}")
        return "available", None

    def _log_status_transition(
        self,
        tool_name: str,
        prev: str | None,
        status: str,
        reason: tuple[str, str] | None,
    ) -> None:
        if status == "disabled":
            return  # US-11 AC-5 / US-10 AC-7: disabled tools are silent.
        from_label = prev if prev is not None else "startup"
        if status == "available":
            logging.info("agentic_tool %s: %s -> available", tool_name, from_label)
            return
        # status == "unavailable"
        root_str = reason[0] if reason else "?"
        reason_str = reason[1] if reason else "?"
        if prev is None:
            logging.info(
                "agentic_tool %s: startup -> unavailable (root=%s reason=%s)",
                tool_name, root_str, reason_str,
            )
        else:
            logging.warning(
                "agentic_tool %s: %s -> unavailable (root=%s reason=%s)",
                tool_name, prev, root_str, reason_str,
            )

    def _available_participating_tools(self, kind: str) -> list[str]:
        """Participating tools whose status is currently `available`."""
        return [
            name for name in self._participating_tools(kind)
            if self._tool_status.get(name) == "available"
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
            if self._tool_status.get(tool_name) != "available":
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
        self._refresh_tool_statuses()
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
                self._tool_status.get(t) == "available"
                for t in ps.agentic_tools
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
            slug = target_slug(canonical["name"], info.kind)
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
        if not changed:
            return False
        if len(changed) == 1:
            return self._sync_from_agentic_tool(pair_id, changed[0], info, state)
        return self._resolve_conflict_n_way(pair_id, info, state, changed)

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
                target_key = self._path_collision_key(target)
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

        If every participating tool already has a copy of the artifact, returns
        []. Otherwise, parses one present tool's bytes to compute the slug, and
        builds the slug-derived target for each absent participating tool.
        """
        participating = self._participating_tools(info.kind)
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
        slug = target_slug(canonical["name"], info.kind)
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
        target_key = self._path_collision_key(path)
        for pair_id, pair_state in state.items():
            for tool_state in pair_state.agentic_tools.values():
                if self._path_collision_key(Path(tool_state.path)) == target_key:
                    return pair_id
        return None

    def _path_collision_key(self, path: Path) -> str:
        resolved = path.resolve()
        normalized = unicodedata.normalize("NFC", str(resolved))
        normcased = os.path.normcase(normalized)
        if sys.platform in {"darwin", "win32"}:
            return normcased.casefold()
        elif os.name != "nt" and normcased != normalized:
            return normcased
        return normalized

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
            self._write_artifact_inplace(
                source_io, source_info.path, source_io.render(canonical, text)
            )

        save_canonical(self.state_dir, pair_id, canonical)

        paths: dict[str, Path] = {source_tool: source_info.path}
        source_dir = source_info.path if source_io.storage == "directory_skill" else None
        for tool_name in self._available_participating_tools(info.kind):
            if tool_name == source_tool:
                continue
            existing_target_info = info.agentic_tools.get(tool_name)
            existing_target_path = (
                existing_target_info.path if existing_target_info is not None else None
            )
            paths[tool_name] = self._render_to_agentic_tool(
                self.agentic_tools[tool_name],
                info.kind,
                canonical,
                existing_path=existing_target_path,
                prior_text=None,
                source_dir=source_dir,
            )

        self._update_state_n_way(state, pair_id, info.kind, paths)
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
        """Project the source tool's bytes to every other present tool."""
        prior_canonical = load_canonical(self.state_dir, pair_id)
        source_info = info.agentic_tools[source_tool]
        source_spec = self.agentic_tools[source_tool]
        source_io = source_spec.io[info.kind]
        text = self._read_artifact_text(source_io, source_info.path)
        canonical = source_io.parse(text, prior_canonical)
        canonical["pair_id"] = pair_id
        save_canonical(self.state_dir, pair_id, canonical)

        paths: dict[str, Path] = {source_tool: source_info.path}
        source_dir = source_info.path if source_io.storage == "directory_skill" else None
        for tool_name in self._available_participating_tools(info.kind):
            if tool_name == source_tool:
                continue
            target_info = info.agentic_tools.get(tool_name)
            if target_info is None:
                continue
            target_spec = self.agentic_tools[tool_name]
            target_io = target_spec.io[info.kind]
            prior_text: str | None = None
            try:
                prior_text = self._read_artifact_text(target_io, target_info.path)
            except Exception:
                prior_text = None
            paths[tool_name] = self._render_to_agentic_tool(
                target_spec,
                info.kind,
                canonical,
                existing_path=target_info.path,
                prior_text=prior_text,
                source_dir=source_dir,
            )

        self._update_state_n_way(state, pair_id, info.kind, paths)
        logging.info("Synced from %s: pair_id=%s", source_tool, pair_id)
        return True

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
            if self._tool_status.get(tool) == "available":
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

    # ---------- read / render helpers ----------

    def _write_artifact_inplace(
        self, io: CustomizationTypeIO, path: Path, text: str
    ) -> None:
        """Write `text` back to the artifact-metadata location at `path`."""
        if io.storage == "single_file":
            atomic_write_text(path, text)
        else:
            atomic_write_text(path / "SKILL.md", text)

    def _render_to_agentic_tool(
        self,
        spec: AgenticToolSpec,
        kind: str,
        canonical: dict[str, Any],
        *,
        existing_path: Path | None,
        prior_text: str | None,
        source_dir: Path | None,
    ) -> Path:
        """Render `canonical` onto one target agentic tool.

        `prior_text` lets renderers that preserve user-frontmatter order
        (claude) re-use the existing on-disk bytes. `source_dir` is the
        directory whose non-SKILL.md siblings must be staged forward (for
        directory_skill storage).
        """
        io = spec.io[kind]
        root = expand_path(self.config[spec.config_dir_keys[kind]])
        slug = target_slug(canonical["name"], kind)
        if io.storage == "single_file":
            target = existing_path or (root / f"{slug}{io.file_suffix}")
            self._assert_target_available(target, existing_path)
            atomic_write_text(target, io.render(canonical, prior_text))
            return target
        if io.storage == "directory_skill":
            target_dir = existing_path or (root / slug)
            self._assert_target_available(target_dir, existing_path)
            skill_md_text = io.render(canonical, prior_text)
            if source_dir is not None and target_dir != source_dir:
                stage_skill_dir(source_dir, target_dir, skill_md_text)
            else:
                target_dir.mkdir(parents=True, exist_ok=True)
                atomic_write_text(target_dir / "SKILL.md", skill_md_text)
            return target_dir
        raise ValueError(f"Unknown storage shape: {io.storage}")

    def _update_state_n_way(
        self,
        state: dict[str, CustomizationArtifactState],
        pair_id: str,
        kind: str,
        paths: dict[str, Path],
    ) -> None:
        ps = state.setdefault(pair_id, CustomizationArtifactState(kind=kind))
        ps.kind = kind
        for tool_name, path in paths.items():
            spec = self.agentic_tools[tool_name]
            io = spec.io[kind]
            digest = (
                sha256_file(path) if io.storage == "single_file" else sha256_tree(path)
            )
            ps.agentic_tools[tool_name] = AgenticToolState(
                path=str(path),
                last_seen=digest,
                last_written=digest,
            )

    def _assert_target_available(self, target: Path, existing_path: Path | None) -> None:
        if existing_path is not None and (
            self._path_collision_key(target) == self._path_collision_key(existing_path)
        ):
            return
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite unowned target path: {target}")
