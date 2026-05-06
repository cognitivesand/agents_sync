"""State store — pair_id-keyed index + filesystem helpers."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PairState:
    kind: str  # "agent" | "skill"
    claude_path: str | None = None
    codex_path: str | None = None
    claude_last_seen: str | None = None
    codex_last_seen: str | None = None
    claude_last_written: str | None = None
    codex_last_written: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "claude_path": self.claude_path,
            "codex_path": self.codex_path,
            "claude_last_seen": self.claude_last_seen,
            "codex_last_seen": self.codex_last_seen,
            "claude_last_written": self.claude_last_written,
            "codex_last_written": self.codex_last_written,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PairState":
        return cls(
            kind=data["kind"],
            claude_path=data.get("claude_path"),
            codex_path=data.get("codex_path"),
            claude_last_seen=data.get("claude_last_seen"),
            codex_last_seen=data.get("codex_last_seen"),
            claude_last_written=data.get("claude_last_written"),
            codex_last_written=data.get("codex_last_written"),
        )


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "converted"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def state_path(state_dir: Path) -> Path:
    return state_dir / "state.json"


def load_state(state_dir: Path) -> dict[str, PairState]:
    path = state_path(state_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.warning("Invalid state file, rebuilding: %s", path)
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, PairState] = {}
    for pair_id, entry in data.items():
        if not isinstance(entry, dict):
            continue
        try:
            result[pair_id] = PairState.from_dict(entry)
        except KeyError:
            logging.warning("Skipping malformed state entry for pair_id=%s", pair_id)
    return result


def save_state(state_dir: Path, state: dict[str, PairState]) -> None:
    path = state_path(state_dir)
    serializable = {pair_id: ps.to_dict() for pair_id, ps in state.items()}
    atomic_write_text(
        path,
        json.dumps(serializable, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )
