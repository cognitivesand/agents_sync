from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceItem:
    kind: str
    source_path: Path
    logical_name: str
    digest: str


@dataclass(frozen=True)
class ExportResult:
    source: SourceItem
    targets: list[Path]


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


def load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {"sources": {}}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.warning("Invalid state file, rebuilding: %s", state_path)
        return {"sources": {}}
    if not isinstance(data, dict):
        return {"sources": {}}
    data.setdefault("sources", {})
    return data


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    atomic_write_text(
        state_path,
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )
