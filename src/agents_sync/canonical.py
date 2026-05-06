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

from agents_sync.state import atomic_write_text


SCHEMA_VERSION = 1


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
        "claude_only": {},
        "codex_only": {},
        "claude_extra": {},
        "codex_extra": {},
    }


def canonical_path(state_dir: Path, pair_id: str) -> Path:
    return state_dir / "canonical" / f"{pair_id}.json"


def load_canonical(state_dir: Path, pair_id: str) -> dict[str, Any] | None:
    path = canonical_path(state_dir, pair_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.error("Canonical for %s is unparseable: %s", pair_id, path)
        return None
    if not isinstance(data, dict):
        logging.error("Canonical for %s is not a JSON object: %s", pair_id, path)
        return None
    return data


def save_canonical(state_dir: Path, pair_id: str, canonical: dict[str, Any]) -> None:
    path = canonical_path(state_dir, pair_id)
    atomic_write_text(
        path,
        json.dumps(canonical, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )
