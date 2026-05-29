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
from typing import Protocol

from agents_sync.agentic_tool_spec import AgenticToolSpec
from agents_sync.tool_status import ToolStatusTracker


class _AdoptionHost(Protocol):
    """Attributes the removal-propagation mixin reads from its host."""

    agentic_tools: dict[str, AgenticToolSpec]
    state_dir: Path
    tool_status: ToolStatusTracker
