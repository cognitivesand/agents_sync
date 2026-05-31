"""Typing-only host contract for the adoption leaf-mixins.

:class:`~agents_sync.adoption.engine.AdoptionEngine` composes the
self-contained ``RemovalPropagatorMixin`` (and the host-free
``PrivacyGateMixin``). ``RemovalPropagatorMixin`` reads shared engine state
(``agentic_tools``, ``state_dir``, ``tool_status``); this Protocol declares
that contract so the mixin type-checks in isolation.

Imported only under ``TYPE_CHECKING`` and used purely as a type-checking base
(``_AdoptionHostBase = _AdoptionHost if TYPE_CHECKING else object``), so it
never alters the mixin's runtime bases or metaclass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from agents_sync.agentic_tool_spec import AgenticToolSpec
from agents_sync.state import CustomizationArtifactState
from agents_sync.sync_types import CustomizationArtifactInfo, RenderResult
from agents_sync.tool_status import ToolStatusTracker


class _AdoptionHost(Protocol):
    """Attributes and methods the adoption leaf-mixins read from their host."""

    config: dict[str, Any]
    agentic_tools: dict[str, AgenticToolSpec]
    state_dir: Path
    tool_status: ToolStatusTracker

    def project_from_canonical(
        self,
        pair_id: str,
        state: dict[str, CustomizationArtifactState],
        target_tools: list[str] | None = None,
    ) -> bool: ...

    def _available_participating_tools(self, kind: str) -> list[str]: ...

    def _is_reserved_target_name(
        self, spec: AgenticToolSpec, kind: str, canonical: dict[str, Any]
    ) -> bool: ...

    def _archive_prior_slot_results(
        self, pair_id: str, kind: str, results: dict[str, RenderResult]
    ) -> None: ...

    def _archive_existing_tool_bytes(
        self, pair_id: str, kind: str, tool: str, info: CustomizationArtifactInfo
    ) -> None: ...
