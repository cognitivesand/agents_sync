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
    """Privacy detection. Relies on ``self.agentic_tools`` from
    :class:`AdoptionEngine`."""

    def _target_is_private(
        self,
        pair_id: str,
        tool_name: str,
        target_spec: AgenticToolSpec,
        kind: str,
        target_path: Path,
        prior_text: str | None,
        target_slot: str | None = None,
    ) -> bool:
        """Decide whether ``target_path`` is privacy-protected."""
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
