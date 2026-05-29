"""Per-cell artifact enumeration and registration.

Mixin consumed by :class:`DiscoveryWalker`. Encapsulates the
file-walking and shared-keyed-map slot iteration that produce a
``{pair_id -> CustomizationArtifactInfo}`` dict.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from agents_sync.agentic_tool_spec import (
    CustomizationTypeIO,
    SharedKeyedMapLayout,
)
from agents_sync.canonical import new_pair_id
from agents_sync.config import expand_path
from agents_sync.identity import InvalidPairId, validate_pair_id
from agents_sync.rendering import (
    path_collision_key,
    read_artifact_text,
)
from agents_sync.shared_keyed_map_io import read_slots
from agents_sync.state import (
    CustomizationArtifactState,
    sha256_file,
    sha256_text,
    sha256_tree,
)
from agents_sync.sync_types import (
    AgenticToolInfo,
    CustomizationArtifactInfo,
)

if TYPE_CHECKING:
    from agents_sync.discovery._host import _WalkerHost

    _WalkerHostBase = _WalkerHost
else:
    _WalkerHostBase = object


class EnumeratorMixin(_WalkerHostBase):
    """Discovery walker mixin: enumerate on-disk artifacts.

    Relies on ``self.config``, ``self.agentic_tools``, and
    ``self.tool_status`` from :class:`DiscoveryWalker`.
    """

    def _discover_shared_keyed_map(
        self,
        tool_name: str,
        customization_type: str,
        io: CustomizationTypeIO,
        pairs: dict[str, CustomizationArtifactInfo],
        blocked_pair_ids: set[str],
        state: dict[str, CustomizationArtifactState],
    ) -> None:
        """Discovery branch for ``SharedKeyedMapLayout``: read the shared
        file once, iterate over slots under ``map_key_path``, register
        each slot as a per-tool view of one artifact."""
        layout = io.file_layout
        assert isinstance(layout, SharedKeyedMapLayout)  # narrowed by caller
        if layout.shared_path_config_key not in self.config:
            return
        shared_path = expand_path(self.config[layout.shared_path_config_key])
        try:
            slots, absent_reason = read_slots(shared_path, layout)
        except Exception:
            logging.exception(
                "Cannot read shared keyed-map file: tool=%s type=%s path=%s",
                tool_name, customization_type, shared_path,
            )
            self._block_state_owners_for_path(
                shared_path, state, blocked_pair_ids,
            )
            return
        if absent_reason is not None:
            return
        try:
            mtime = shared_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        for slot_key, slot_text in slots.items():
            self._add_keyed_map_slot_artifact(
                tool_name, customization_type, io,
                shared_path, slot_key, slot_text, mtime,
                pairs, blocked_pair_ids, state,
            )

    def _add_keyed_map_slot_artifact(
        self,
        tool_name: str,
        customization_type: str,
        io: CustomizationTypeIO,
        shared_path: Path,
        slot_key: str,
        slot_text: str,
        mtime: float,
        pairs: dict[str, CustomizationArtifactInfo],
        blocked_pair_ids: set[str],
        state: dict[str, CustomizationArtifactState],
    ) -> None:
        """Register one keyed-map slot as a per-tool view of one artifact."""
        try:
            pair_id = io.extract_pair_id(slot_text)
        except Exception:
            logging.exception(
                "Cannot extract pair_id from %s %s slot: path=%s slot=%s",
                tool_name, customization_type, shared_path, slot_key,
            )
            self._block_state_owner_slot(
                shared_path, slot_key, state, blocked_pair_ids,
            )
            return
        present = pair_id is not None
        if pair_id is None:
            pair_id = new_pair_id()
        else:
            try:
                validate_pair_id(pair_id)
            except InvalidPairId:
                logging.error(
                    "Invalid pair_id in %s %s slot: path=%s slot=%s",
                    tool_name, customization_type, shared_path, slot_key,
                )
                self._block_state_owner_slot(
                    shared_path, slot_key, state, blocked_pair_ids,
                )
                return
        digest = sha256_text(slot_text)
        info = AgenticToolInfo(
            shared_path, digest, mtime, present, slot=slot_key,
        )
        self._insert_agentic_tool(
            pair_id, customization_type, tool_name, info,
            pairs, blocked_pair_ids,
        )

    def _enumerate_artifacts(
        self, root: Path, io: CustomizationTypeIO
    ) -> list[Path]:
        """Return the on-disk artifact paths under ``root`` for this IO cell.

        For single_file storage, returns the matching files. For
        directory_skill storage, returns the parent directory of each
        ``*/SKILL.md`` so callers get the artifact path (not the metadata file).
        """
        if io.storage == "single_file":
            candidate_names = io.detection_file_names
            if candidate_names:
                for candidate_name in candidate_names:
                    candidate_path = root / candidate_name
                    if candidate_path.is_file() and not candidate_path.name.startswith("."):
                        return [candidate_path]
                return []
            walker = root.rglob if io.recursive else root.glob
            return sorted(
                p for p in walker(f"*{io.file_suffix}")
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
        try:
            pair_id = io.extract_pair_id(text)
        except Exception:
            logging.exception(
                "Cannot extract pair_id from %s %s: path=%s",
                tool_name, customization_type, path,
            )
            self._block_state_owner(path, state, blocked_pair_ids)
            return
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

    def _block_state_owner_slot(
        self,
        path: Path,
        slot: str,
        state: dict[str, CustomizationArtifactState],
        blocked_pair_ids: set[str],
    ) -> None:
        owner = self.state_owner_for_path(path, state, slot=slot)
        if owner is not None:
            blocked_pair_ids.add(owner)

    def _block_state_owners_for_path(
        self,
        path: Path,
        state: dict[str, CustomizationArtifactState],
        blocked_pair_ids: set[str],
    ) -> None:
        target_key = path_collision_key(path)
        for pair_id, pair_state in state.items():
            if any(
                path_collision_key(tool_state.path) == target_key
                for tool_state in pair_state.agentic_tools.values()
            ):
                blocked_pair_ids.add(pair_id)
