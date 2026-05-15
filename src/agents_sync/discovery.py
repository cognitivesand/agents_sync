"""On-disk discovery of agentic-tool artifacts plus pre-process collision blocking.

DiscoveryWalker walks every (agentic_tool, customization_type) cell in the
registry, reads each artifact, validates its pair_id, and groups artifacts
by pair_id into a discovery dict. After per-pair processing has a chance
to assign new pair_ids, the caller invokes ``block_target_collisions`` to
veto any pair whose planned adoption target would clobber another pair's
managed path or a foreign unmanaged path.

Extracted from Syncer so the discovery / collision logic does not share a
class with the orchestration loop.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import AgenticToolSpec, CustomizationTypeIO
from agents_sync.canonical import new_pair_id
from agents_sync.config import expand_path
from agents_sync.identity import InvalidPairId, validate_pair_id
from agents_sync.rendering import path_collision_key, read_artifact_text
from agents_sync.state import (
    CustomizationArtifactState,
    sha256_file,
    sha256_tree,
    target_slug,
)
from agents_sync.sync_types import AgenticToolInfo, CustomizationArtifactInfo
from agents_sync.tool_status import ToolStatusTracker


class DiscoveryWalker:
    """Walks the on-disk artifact tree and produces a discovery view.

    The walker holds no per-poll state of its own; ``discover`` and
    ``block_target_collisions`` are pure functions of their inputs except
    for their explicit ``discovery`` / ``state`` mutations.
    """

    def __init__(
        self,
        config: dict[str, Any],
        agentic_tools: dict[str, AgenticToolSpec],
        tool_status: ToolStatusTracker,
    ) -> None:
        self.config = config
        self.agentic_tools = agentic_tools
        self.tool_status = tool_status

    # ---------- public entry points ----------

    def discover(
        self, state: dict[str, CustomizationArtifactState]
    ) -> tuple[dict[str, CustomizationArtifactInfo], set[str]]:
        """Walk every (agentic_tool, customization_type) cell in the registry.

        Tools whose status is not ``available`` are skipped entirely so
        unreadable / unmounted / disabled tools never appear as removal
        signals (US-11 AC-4).

        Returns ``(pairs, blocked_pair_ids)``. A blocked pair_id has already
        been popped from ``pairs``.
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
        return pairs, blocked_pair_ids

    def block_target_collisions(
        self,
        discovery: dict[str, CustomizationArtifactInfo],
        state: dict[str, CustomizationArtifactState],
    ) -> set[str]:
        """For each not-yet-managed pair, plan its adoption targets. Block any
        pair whose target collides with a managed pair's owned path, with an
        unmanaged path on disk, or with another pair's planned target.

        Mutates ``discovery`` (pops blocked entries) and returns the set of
        blocked pair_ids so the caller can fold them into the overall block.
        """
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

                owner = self.state_owner_for_path(target, state)
                if owner is not None and owner != pair_id:
                    logging.error(
                        "Target path collision with managed pair: "
                        "pair_id=%s owner_pair_id=%s target=%s",
                        pair_id, owner, target,
                    )
                    blocked.add(pair_id)
                elif owner is None and target.exists():
                    logging.error(
                        "Target path collision with unmanaged path: pair_id=%s target=%s",
                        pair_id, target,
                    )
                    blocked.add(pair_id)

        for target_key, pair_ids in targets.items():
            if len(pair_ids) <= 1:
                continue
            logging.error(
                "Target path collision: target=%s pair_ids=%s",
                target_display[target_key], pair_ids,
            )
            blocked.update(pair_ids)

        for pair_id in blocked:
            discovery.pop(pair_id, None)
        return blocked

    def state_owner_for_path(
        self,
        path: Path,
        state: dict[str, CustomizationArtifactState],
    ) -> str | None:
        """Return the pair_id whose state owns `path`, or None."""
        target_key = path_collision_key(path)
        for pair_id, pair_state in state.items():
            for tool_state in pair_state.agentic_tools.values():
                if path_collision_key(Path(tool_state.path)) == target_key:
                    return pair_id
        return None

    # ---------- internals ----------

    def _enumerate_artifacts(
        self, root: Path, io: CustomizationTypeIO
    ) -> list[Path]:
        """Return the on-disk artifact paths under `root` for this IO cell.

        For single_file storage, returns the matching files. For
        directory_skill storage, returns the parent directory of each
        ``*/SKILL.md`` so callers get the artifact path (not the metadata file).
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
            text = read_artifact_text(io, path)
        except Exception:
            logging.exception(
                "Cannot read %s %s: path=%s",
                tool_name, customization_type, path,
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
                    tool_name, customization_type, path,
                )
                self._block_state_owner(path, state, blocked_pair_ids)
                return
        digest = sha256_file(path) if io.storage == "single_file" else sha256_tree(path)
        info = AgenticToolInfo(path, digest, path.stat().st_mtime, present)
        self._insert_agentic_tool(
            pair_id, customization_type, tool_name, info, pairs, blocked_pair_ids
        )

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
                tool_name, pair_id,
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
        owner = self.state_owner_for_path(path, state)
        if owner is not None:
            blocked_pair_ids.add(owner)

    def _planned_adoption_targets(
        self, info: CustomizationArtifactInfo
    ) -> list[Path]:
        """Return target paths adoption would write on tools that don't yet hold
        the artifact.

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
        text = read_artifact_text(source_io, source_info.path)
        canonical = source_io.parse(text, None, artifact_path=source_info.path)
        targets: list[Path] = []
        for tool_name in missing:
            spec = self.agentic_tools[tool_name]
            io = spec.io[info.kind]
            root = expand_path(self.config[spec.config_dir_keys[info.kind]])
            slugger = io.slugify_name or target_slug
            slug = slugger(canonical["name"])
            if io.storage == "single_file":
                targets.append(root / f"{slug}{io.file_suffix}")
            else:
                targets.append(root / slug)
        return targets

    def _available_participating_tools(self, kind: str) -> list[str]:
        return [
            name for name, spec in self.agentic_tools.items()
            if kind in spec.supported_customization_types
            and self.tool_status.is_available(name)
        ]
