"""Fail-closed privacy gate.

If either the bytes cannot be read or the parser cannot produce a
canonical, treat the artifact as private and skip projection. The
alternative (fail open) would overwrite a file we could not inspect —
which would defeat the privacy invariant the user signalled by marking
artifacts private. The trade-off: a parse regression in an adapter
starts looking like a privacy block until it is fixed; that is the
safer direction. The decision is logged at WARNING with the underlying
exception type so operators can disambiguate.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import AgenticToolSpec
from agents_sync.canonical import is_private
from agents_sync.rendering import read_artifact_text


class PrivacyGateMixin:
    """Egress gate: refuse to read-from or write-over a protected artifact.

    An artifact is protected when the user marked it ``private`` or when its
    content is framework-specific (US-15: it references a tool's own private
    directory, so it must not propagate to other tools). Relies on
    ``self.agentic_tools`` from :class:`AdoptionEngine`."""

    def _target_is_protected(
        self,
        pair_id: str,
        tool_name: str,
        target_spec: AgenticToolSpec,
        kind: str,
        target_path: Path,
        prior_text: str | None,
        target_slot: str | None = None,
    ) -> bool:
        """Decide whether ``target_path`` must not be overwritten.

        True when the existing target is privacy-protected or framework-specific
        (US-15): either way the daemon leaves the file as the user authored it.
        """
        target_io = target_spec.io[kind]
        text = prior_text
        if text is None:
            try:
                text = read_artifact_text(target_io, target_path, slot=target_slot)
            except (OSError, UnicodeDecodeError) as exc:
                logging.warning(
                    "Could not inspect prior text at %s for pair_id=%s; "
                    "treating as private (fail-closed) "
                    "(%s: %s)",
                    target_path,
                    pair_id,
                    type(exc).__name__,
                    exc,
                    extra={"event": "privacy_gate_failed_closed_on_read"},
                )
                return True
        try:
            canonical = target_io.parse(text, None, artifact_path=target_path)
        except (OSError, UnicodeDecodeError, ValueError, KeyError) as exc:
            logging.warning(
                "Could not inspect prior canonical at %s for pair_id=%s; "
                "treating as private (fail-closed) (%s: %s)",
                target_path,
                pair_id,
                type(exc).__name__,
                exc,
                extra={"event": "privacy_gate_failed_closed_on_parse"},
            )
            return True
        if self._skip_framework_specific(pair_id, tool_name, canonical):
            return True
        return self._skip_private_canonical(pair_id, tool_name, canonical)

    def _skip_private_canonical(
        self,
        pair_id: str,
        source_tool: str,
        canonical: dict[str, Any],
    ) -> bool:
        if not is_private(canonical):
            return False
        logging.info(
            "Skipped private customization_artifact: pair_id=%s source=%s kind=%s",
            pair_id,
            source_tool,
            canonical.get("kind"),
        )
        return True

    def _skip_framework_specific(
        self,
        pair_id: str,
        source_tool: str,
        canonical: dict[str, Any],
    ) -> bool:
        """US-15: hold a framework-specific `rules` file back from other tools.

        Detected at parse time (``framework_specific`` set when the effective
        body references a tool-private directory). The whole file is neither
        propagated from this tool nor written over on another."""
        if not canonical.get("framework_specific"):
            return False
        logging.warning(
            "Framework-specific rules held back (not propagated): "
            "pair_id=%s tool=%s token=%s",
            pair_id,
            source_tool,
            canonical.get("framework_specific_token"),
            extra={"event": "rules_framework_specific_held_back"},
        )
        return True
