"""The canonical document — the lossless, pure per-artifact truth (no I/O).

A ``CanonicalDocument`` is the authoritative representation of one customization
artifact (NFR-16); every tool-side file is a projection of it. This module is
pure: it does no I/O, mints no identity, and knows no tool dialect. Persistence
lives in the canonical-store gateway; runtime metadata (``last_modified``,
``generation``) is *not* part of the document, so the content digest is over
content only (FR-14).

The document is an immutable value object: attributes cannot be rebound (frozen)
and the per-tool bags are exposed read-only, so its ``content_digest`` is stable
and it is safely hashable (by content). The field set mirrors the established
canonical schema; modelling kind-specific fields (``model``/``effort``/``tools``
are agent-only) as a per-kind structure is deferred — a schema change out of
scope for the entity extraction.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

_REQUIRED_FIELDS: tuple[str, ...] = ("artifact_id", "kind")


@dataclass(frozen=True)
class CanonicalDocument:
    """One artifact's content, normalisable to a byte-stable form."""

    artifact_id: str
    kind: str
    name: str = ""
    description: str = ""
    body: str = ""
    model: str | None = None
    effort: str | None = None
    tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    permission_mode: str | None = None
    provenance: str = "user"
    private: bool = False
    per_tool_only: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    per_tool_extra: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Deep-freeze the per-tool bags: frozen guards attribute rebinding, not
        # container contents, so every nested mapping is made read-only to keep the
        # value object immutable and its content digest stable.
        object.__setattr__(self, "per_tool_only", _freeze(self.per_tool_only))
        object.__setattr__(self, "per_tool_extra", _freeze(self.per_tool_extra))

    def __hash__(self) -> int:
        # Hashable and consistent with equality: equal content hashes equal. The
        # auto-generated hash would raise on the mapping fields, so hash by digest.
        return hash(self.content_digest())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanonicalDocument:
        """Build from a content dict, ignoring non-content keys (e.g. metadata).

        Raises ``ValueError`` if an identifying field is absent or empty — a
        content dict without it is not a valid canonical document (§8).
        """
        for required in _REQUIRED_FIELDS:
            if not data.get(required):
                raise ValueError(f"canonical document missing required field: {required}")
        return cls(
            artifact_id=str(data["artifact_id"]),
            kind=str(data["kind"]),
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            body=str(data.get("body", "")),
            model=data.get("model"),
            effort=data.get("effort"),
            tools=tuple(data.get("tools") or ()),
            disallowed_tools=tuple(data.get("disallowed_tools") or ()),
            permission_mode=data.get("permission_mode"),
            provenance=str(data.get("provenance", "user")),
            private=bool(data.get("private", False)),
            per_tool_only=dict(data.get("per_tool_only") or {}),
            per_tool_extra=dict(data.get("per_tool_extra") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the content as a plain, independently-owned dict (no aliasing)."""
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
            "body": self.body,
            "model": self.model,
            "effort": self.effort,
            "tools": list(self.tools),
            "disallowed_tools": list(self.disallowed_tools),
            "permission_mode": self.permission_mode,
            "provenance": self.provenance,
            "private": self.private,
            "per_tool_only": _thaw(self.per_tool_only),
            "per_tool_extra": _thaw(self.per_tool_extra),
        }

    def normalised(self) -> CanonicalDocument:
        """Return a copy collapsing differences that are not semantic.

        Order-insensitive lists are sorted, ``name``/``description`` are stripped,
        and ``body`` line endings are normalised to LF with a single trailing
        newline. Idempotent; two semantically-equal documents normalise equal.
        """
        return replace(
            self,
            name=self.name.strip(),
            description=self.description.strip(),
            body=_normalise_body(self.body),
            tools=tuple(sorted(self.tools)),
            disallowed_tools=tuple(sorted(self.disallowed_tools)),
        )

    def content_digest(self) -> str:
        """Stable lowercase-hex SHA-256 over normalised content (FR-14)."""
        payload = json.dumps(self.normalised().to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _freeze(value: Any) -> Any:
    """Rebuild ``value`` fully immutable at every depth.

    Mappings become ``MappingProxyType`` and lists become tuples, recursively, so
    no nested container exposed by the document can be mutated in place (which
    would silently change ``content_digest``). :func:`_thaw` restores lists for
    ``to_dict``, so JSON shape still round-trips faithfully."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Inverse of :func:`_freeze`: plain, independently-owned dicts and lists."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _normalise_body(body: str) -> str:
    """LF line endings, a single trailing newline; inline whitespace preserved."""
    text = body.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return text + "\n" if text else ""
