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

    def _load_target_canonical_for_privacy(
        self,
        pair_id: str,
        target_spec: AgenticToolSpec,
        kind: str,
        target_path: Path,
        prior_text: str | None,
        prior_canonical: dict[str, Any] | None,
        artifact_root: Path | None = None,
        target_slot: str | None = None,
    ) -> dict[str, Any] | None:
        """Read and parse ``target_path`` for privacy inspection.

        Returns ``None`` when the target cannot be inspected; callers treat
        that as fail-closed private content.
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
                return None
        try:
            return target_io.parse(
                text,
                prior_canonical,
                artifact_path=target_path,
                artifact_root=artifact_root,
            )
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
            return None

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
            "Framework-specific rules held back (not propagated): pair_id=%s tool=%s token=%s",
            pair_id,
            source_tool,
            canonical.get("framework_specific_token"),
            extra={"event": "rules_framework_specific_held_back"},
        )
        return True
