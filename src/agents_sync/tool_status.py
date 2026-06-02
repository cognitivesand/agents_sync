"""Per-tool availability tracking (US-11).

Owns the ``available`` / ``unavailable`` / ``disabled`` status for each
registered agentic tool, with transition logging on every state change.
Extracted from Syncer so the orchestrator does not need to carry the
status-probing logic alongside its discovery and reconciliation duties.
"""

from __future__ import annotations

import logging
from typing import Any

from agents_sync.agentic_tool_spec import AgenticToolSpec
from agents_sync.config import expand_path


class ToolStatusTracker:
    """Compute and remember each tool's availability across polls.

    Empty until the first ``refresh()`` call. ``ensure_roots`` is a startup
    convenience that pre-creates every enabled tool's roots so a fresh
    install lands on ``available`` rather than ``unavailable``.
    """

    def __init__(
        self,
        config: dict[str, Any],
        agentic_tools: dict[str, AgenticToolSpec],
    ) -> None:
        self.config = config
        self.agentic_tools = agentic_tools
        self._status: dict[str, str] = {}
        self._available_kinds: dict[str, set[str]] = {}

    # ---------- public read API ----------

    def get(self, tool_name: str) -> str | None:
        return self._status.get(tool_name)

    def is_available(self, tool_name: str) -> bool:
        return self._status.get(tool_name) == "available"

    def is_kind_available(self, tool_name: str, kind: str) -> bool:
        return kind in self._available_kinds.get(tool_name, set())

    def snapshot(self) -> dict[str, str]:
        """A shallow copy of the current status map, for inspection in tests."""
        return dict(self._status)

    # ---------- startup ----------

    def ensure_roots(self) -> None:
        """mkdir -p every enabled tool's configured customization-type roots.

        Best-effort: a failure here (permission denied, parent is a file) is
        not fatal — ``refresh()`` will observe the failure on the first poll
        and mark the tool ``unavailable`` with the underlying OSError.
        """
        for spec in self.agentic_tools.values():
            if not self._is_tool_enabled(spec):
                continue
            for kind, config_key in spec.config_dir_keys.items():
                if not self._is_kind_enabled(spec, kind):
                    continue
                raw_root = self.config.get(config_key)
                if raw_root is None:
                    continue
                layout = spec.io[kind].file_layout
                resolved = expand_path(raw_root)
                parent = layout.probe_check_path(resolved) if layout is not None else resolved
                try:
                    parent.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    logging.warning(
                        "Could not pre-create %s root %s (%s: %s); "
                        "next poll will mark this tool unavailable.",
                        spec.name,
                        parent,
                        type(exc).__name__,
                        exc,
                    )

    # ---------- per-poll refresh ----------

    def refresh(self) -> None:
        """Compute each tool's status; log every transition (US-11 AC-5).

        Status rules:
          - ``disabled`` ⇒ tool is registered but its enable-flag is False.
          - ``unavailable`` ⇒ tool is enabled but at least one of its
            customization_type roots is missing or unreadable on this poll.
          - ``available`` ⇒ tool is enabled and every root is reachable.
        """
        new_status: dict[str, str] = {}
        reasons: dict[str, tuple[str, str]] = {}
        available_kinds: dict[str, set[str]] = {}
        for tool_name, spec in self.agentic_tools.items():
            if not self._is_tool_enabled(spec):
                new_status[tool_name] = "disabled"
                available_kinds[tool_name] = set()
                continue
            status, reason, kinds = self._probe_tool_roots(spec)
            new_status[tool_name] = status
            available_kinds[tool_name] = kinds
            if reason is not None:
                reasons[tool_name] = reason

        for tool_name, status in new_status.items():
            prev = self._status.get(tool_name)
            if prev == status:
                continue
            self._log_status_transition(tool_name, prev, status, reasons.get(tool_name))
        self._status = new_status
        self._available_kinds = available_kinds

    # ---------- internals ----------

    def _is_tool_enabled(self, spec: AgenticToolSpec) -> bool:
        """Whether a tool's config-side enable-flag is on.

        A tool without ``disable_config_key`` cannot be disabled — it can only
        become ``unavailable`` by losing its root. Optional tools such as
        Antigravity and opencode use explicit enable flags.
        """
        if spec.disable_config_key is None:
            return True
        return bool(self.config.get(spec.disable_config_key, True))

    def _is_kind_enabled(self, spec: AgenticToolSpec, kind: str) -> bool:
        if not self._is_tool_enabled(spec):
            return False
        config_key = spec.kind_disable_config_keys.get(kind)
        if config_key is None:
            return True
        return bool(self.config.get(config_key, True))

    def _probe_tool_roots(
        self, spec: AgenticToolSpec
    ) -> tuple[str, tuple[str, str] | None, set[str]]:
        """Return (status, reason_or_None) for one tool's on-disk reachability."""
        available_kinds: set[str] = set()
        first_reason: tuple[str, str] | None = None
        enabled_kind_count = 0
        for kind, config_key in spec.config_dir_keys.items():
            if not self._is_kind_enabled(spec, kind):
                continue
            enabled_kind_count += 1
            layout = spec.io[kind].file_layout
            if config_key not in self.config:
                if layout is not None and layout.tolerates_missing_config_key():
                    continue
                reason = (config_key, "config key missing")
                if not spec.partial_availability:
                    return "unavailable", reason, set()
                if first_reason is None:
                    first_reason = reason
                continue
            raw_root = self.config.get(config_key)
            if raw_root is None:
                reason = (config_key, "path is not configured")
                if not spec.partial_availability:
                    return "unavailable", reason, set()
                if first_reason is None:
                    first_reason = reason
                continue
            resolved = expand_path(raw_root)
            probe_path = layout.probe_check_path(resolved) if layout is not None else resolved
            if not probe_path.exists():
                reason = (str(probe_path), "path does not exist")
                if not spec.partial_availability:
                    return "unavailable", reason, set()
                if first_reason is None:
                    first_reason = reason
                continue
            try:
                next(probe_path.iterdir(), None)
            except OSError as exc:
                reason = (str(probe_path), f"{type(exc).__name__}: {exc}")
                if not spec.partial_availability:
                    return "unavailable", reason, set()
                if first_reason is None:
                    first_reason = reason
                continue
            available_kinds.add(kind)
        if spec.partial_availability:
            if available_kinds:
                return "available", None, available_kinds
            if enabled_kind_count == 0:
                return "disabled", None, set()
            return "unavailable", first_reason, set()
        return "available", None, available_kinds

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
                tool_name,
                root_str,
                reason_str,
            )
        else:
            logging.warning(
                "agentic_tool %s: %s -> unavailable (root=%s reason=%s)",
                tool_name,
                prev,
                root_str,
                reason_str,
            )
