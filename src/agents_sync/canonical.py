"""Canonical JSON document — the lossless intermediate per pair.

Each managed pair has one canonical document at:
  <state_dir>/canonical/<pair_id>.json

Both renderers project from it; in Phase 3 both parsers will fold side
changes back into it. For Phase 2 (one-way) only the Claude parser is
wired through.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from agents_sync.state import _quarantine_corrupt, atomic_write_text
from agents_sync.identity import validate_pair_id


SCHEMA_VERSION = 2


def new_pair_id() -> str:
    return str(uuid.uuid4())


def empty_canonical(kind: str, pair_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "pair_id": pair_id or new_pair_id(),
        "kind": kind,
        "name": "",
        "description": "",
        "body": "",
        "model": None,
        "effort": None,
        "tools": [],
        "disallowed_tools": [],
        "permission_mode": None,
        "provenance": "user",
        "private": False,
        "per_agentic_tool_only": {},
        "per_agentic_tool_extra": {},
    }


def is_private(canonical: dict[str, Any]) -> bool:
    return bool(canonical.get("private", False))


def canonical_path(state_dir: Path, pair_id: str) -> Path:
    validate_pair_id(pair_id)
    return state_dir / "canonical" / f"{pair_id}.json"


def load_canonical(state_dir: Path, pair_id: str) -> dict[str, Any] | None:
    """Return the canonical dict for ``pair_id``, or ``None`` if absent.

    Corrupt canonicals (unparseable JSON, non-object root) are quarantined
    under ``state_dir/quarantine/`` before this returns ``None`` — distinguishing
    a partial-write recovery scenario from "never existed yet" by inspecting
    the quarantine directory. Callers may treat the ``None`` return as
    "treat as absent for this poll" without losing the corrupt bytes.
    """
    path = canonical_path(state_dir, pair_id)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logging.exception("Could not read canonical for %s: %s", pair_id, path)
        _quarantine_corrupt(state_dir, path, reason="unreadable bytes")
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        _quarantine_corrupt(state_dir, path, reason="JSON parse error")
        return None
    if not isinstance(data, dict):
        _quarantine_corrupt(state_dir, path, reason="root is not a JSON object")
        return None
    return data


def save_canonical(state_dir: Path, pair_id: str, canonical: dict[str, Any]) -> None:
    path = canonical_path(state_dir, pair_id)
    atomic_write_text(
        path,
        json.dumps(canonical, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )


def apply_per_tool_partition(
    canonical: dict[str, Any],
    *,
    agentic_tool_name: str,
    frontmatter_data: dict[str, Any],
    tool_only_fields: tuple[str, ...],
    known_fields: frozenset[str] | set[str],
) -> None:
    """Project ``frontmatter_data`` into ``per_agentic_tool_only`` and
    ``per_agentic_tool_extra`` under ``agentic_tool_name``.

    - ``tool_only_fields`` is the ordered set of frontmatter keys this
      adapter owns (rendered back into the tool's frontmatter on emit but
      excluded from the cross-tool canonical surface).
    - ``known_fields`` is the union of all keys this adapter knows about
      (canonical fields *plus* tool-only fields); any key not in this set
      lands in ``per_agentic_tool_extra`` so user-authored fields the
      project does not yet model are not silently dropped.

    Mutates ``canonical`` in place. Other agentic tools' entries are
    preserved untouched — only this adapter's slice is rewritten.

    This helper replaces three hand-rolled copies of the same eight-line
    pattern that previously lived in ``rules_io.py`` and
    ``slash_command_io.py`` (Phase 2.3 of the audit remediation).
    """
    per_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_only[agentic_tool_name] = {
        field_name: frontmatter_data[field_name]
        for field_name in tool_only_fields
        if field_name in frontmatter_data
    }
    canonical["per_agentic_tool_only"] = per_only

    per_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_extra[agentic_tool_name] = {
        key: value
        for key, value in frontmatter_data.items()
        if key not in known_fields
    }
    canonical["per_agentic_tool_extra"] = per_extra
