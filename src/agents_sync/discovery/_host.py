"""Typing-only host contract for the discovery mixins.

The :class:`~agents_sync.discovery.walker.DiscoveryWalker` composes
``EnumeratorMixin``, ``AdoptionPlannerMixin`` and ``CollisionBlockerMixin``.
Each mixin reaches into shared walker state (``config``, ``agentic_tools``,
``tool_status``) and a small number of cross-boundary methods. This Protocol
makes that implicit ``self`` contract explicit so the mixins type-check in
isolation.

It is imported only under ``TYPE_CHECKING`` and used purely as a
type-checking base (``_WalkerHostBase = _WalkerHost if TYPE_CHECKING else
object``), so it never alters the mixins' runtime bases or metaclass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from agents_sync.agentic_tool_spec import AgenticToolSpec
from agents_sync.state import CustomizationArtifactState
from agents_sync.sync_types import CustomizationArtifactInfo, PlannedTarget
from agents_sync.tool_status import ToolStatusTracker


class _WalkerHost(Protocol):
    """Attributes and methods the discovery mixins read from their host."""

    config: dict[str, Any]
    agentic_tools: dict[str, AgenticToolSpec]
    tool_status: ToolStatusTracker

    def state_owner_for_path(
        self,
        path: Path,
        state: dict[str, CustomizationArtifactState],
        slot: str | None = None,
    ) -> str | None: ...

    def _planned_adoption_targets(self, info: CustomizationArtifactInfo) -> list[PlannedTarget]: ...
