"""Adoption target planning for not-yet-managed pairs.

Mixin consumed by :class:`DiscoveryWalker`. Given a discovered pair's
``CustomizationArtifactInfo``, produces the ``PlannedTarget`` list that
adoption would write on tools that don't yet hold the artifact.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    DirectorySkillLayout,
    SharedKeyedMapLayout,
    SingleFileLayout,
    is_reserved_customization_name,
)
from agents_sync.canonical import is_private
from agents_sync.config import expand_path
from agents_sync.rendering import (
    read_artifact_text,
    single_file_target,
)
from agents_sync.shared_keyed_map_io import read_slots
from agents_sync.state import target_slug
from agents_sync.sync_types import (
    CustomizationArtifactInfo,
    PlannedTarget,
)

if TYPE_CHECKING:
    from agents_sync.discovery._host import _WalkerHost

    _WalkerHostBase = _WalkerHost
else:
    _WalkerHostBase = object


class AdoptionPlannerMixin(_WalkerHostBase):
    """Plan adoption targets. Relies on ``self.config``, ``self.agentic_tools``,
    ``self.tool_status`` from :class:`DiscoveryWalker`."""

    def _planned_adoption_targets(self, info: CustomizationArtifactInfo) -> list[PlannedTarget]:
        """Return targets adoption would write on tools that don't yet hold
        the artifact.

        Per-file targets carry ``slot=None``; ``SharedKeyedMapLayout``
        targets carry the slot key derived from the canonical's
        ``key_field``. Disabled / unavailable tools never figure in
        adoption targets and therefore never participate in collision
        blocking.
        """
        participating = self._available_participating_tools(info.kind)
        missing = [t for t in participating if t not in info.agentic_tools]
        if not missing or not info.agentic_tools:
            return []
        try:
            canonical = self._read_source_canonical(info)
        except (OSError, UnicodeDecodeError, ValueError, KeyError) as exc:
            # Fail closed: an unreadable / unparseable source (incl. a broken
            # rules @import, US-15 AC-4) plans no adoption targets. Per-pair
            # processing handles the same failure and records it.
            logging.warning(
                "Cannot plan adoption targets; source unreadable/unparseable "
                "(%s: %s)",
                type(exc).__name__,
                exc,
                extra={"event": "adoption_plan_source_unreadable"},
            )
            return []
        # A private or framework-specific source is never propagated, so it
        # plans no targets and never figures in collision blocking (US-15).
        if is_private(canonical) or canonical.get("framework_specific"):
            return []
        return self._targets_for_missing(info.kind, missing, canonical)

    def _read_source_canonical(self, info: CustomizationArtifactInfo) -> dict[str, Any]:
        """Parse the canonical from the lexicographically-first existing tool."""
        source_tool = sorted(info.agentic_tools.keys())[0]
        source_info = info.agentic_tools[source_tool]
        source_spec = self.agentic_tools[source_tool]
        source_io = source_spec.io[info.kind]
        if isinstance(source_io.file_layout, SharedKeyedMapLayout):
            source_root = expand_path(self.config[source_io.file_layout.shared_path_config_key])
            slots, _ = read_slots(source_info.path, source_io.file_layout)
            text = slots.get(source_info.slot or "", "")
        else:
            source_root = expand_path(self.config[source_spec.config_dir_keys[info.kind]])
            text = read_artifact_text(source_io, source_info.path)
        return source_io.parse(
            text,
            None,
            artifact_path=source_info.path,
            artifact_root=source_root,
        )

    def _targets_for_missing(
        self,
        kind: str,
        missing: list[str],
        canonical: dict[str, Any],
    ) -> list[PlannedTarget]:
        targets: list[PlannedTarget] = []
        for tool_name in missing:
            spec = self.agentic_tools[tool_name]
            io = spec.io[kind]
            if self._is_reserved_target_name(spec, kind, canonical):
                continue
            target = self._target_for_tool(spec, kind, io, canonical)
            if target is not None:
                targets.append(target)
        return targets

    def _target_for_tool(
        self,
        spec: AgenticToolSpec,
        kind: str,
        io: Any,
        canonical: dict[str, Any],
    ) -> PlannedTarget | None:
        layout = io.file_layout
        if isinstance(layout, SharedKeyedMapLayout):
            raw_shared = self.config.get(layout.shared_path_config_key)
            if raw_shared is None:
                return None  # shared file not configured on this tool — skip
            shared_path = expand_path(raw_shared)
            slot_key = str(canonical.get(layout.key_field, ""))
            if not slot_key:
                return None
            return PlannedTarget(
                path=shared_path,
                slot=slot_key,
                file_layout=layout,
            )
        raw_root = self.config.get(spec.config_dir_keys[kind])
        if raw_root is None:
            return None  # target root not configured on this tool — skip it
        root = expand_path(raw_root)
        slugger = io.slugify_name or target_slug
        slug = slugger(canonical["name"])
        if isinstance(layout, SingleFileLayout):
            return PlannedTarget(path=single_file_target(root, io, slug))
        if isinstance(layout, DirectorySkillLayout):
            return PlannedTarget(path=root / slug)
        raise ValueError(f"Unknown file layout: {type(layout).__name__}")

    def _available_participating_tools(self, kind: str) -> list[str]:
        return [
            name
            for name, spec in self.agentic_tools.items()
            if kind in spec.supported_customization_types and self.tool_status.is_available(name)
        ]

    def _is_reserved_target_name(
        self,
        spec: AgenticToolSpec,
        kind: str,
        canonical: dict[str, Any],
    ) -> bool:
        io = spec.io[kind]
        name = str(canonical.get("name", ""))
        return is_reserved_customization_name(io, name)
