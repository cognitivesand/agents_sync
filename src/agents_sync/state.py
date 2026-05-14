"""State store — pair_id-keyed index + filesystem helpers."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents_sync.filesystem_windows_retry import retry_fs
from agents_sync.identity import InvalidPairId, validate_pair_id


STATE_SCHEMA_VERSION = 2


_WINDOWS_RESERVED_BASENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}

_IGNORED_TREE_FILE_NAMES = {".DS_Store"}
_IGNORED_TREE_FILE_PREFIXES = ("._",)


@dataclass
class AgenticToolState:
    """Per-agentic-tool slice of one customization artifact's state."""

    path: str
    last_seen: str | None = None
    last_written: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "last_seen": self.last_seen,
            "last_written": self.last_written,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgenticToolState":
        return cls(
            path=data["path"],
            last_seen=data.get("last_seen"),
            last_written=data.get("last_written"),
        )


@dataclass
class CustomizationArtifactState:
    """One managed customization artifact, projected across N agentic tools."""

    kind: str  # "agent" | "skill" — serialized as "customization_type"
    agentic_tools: dict[str, AgenticToolState] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "customization_type": self.kind,
            "agentic_tools": {
                name: at.to_dict() for name, at in self.agentic_tools.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CustomizationArtifactState":
        raw_tools = data.get("agentic_tools") or {}
        if not isinstance(raw_tools, dict):
            raise ValueError("agentic_tools must be a mapping")
        return cls(
            kind=data["customization_type"],
            agentic_tools={
                name: AgenticToolState.from_dict(entry)
                for name, entry in raw_tools.items()
                if isinstance(entry, dict)
            },
        )


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    value = value.rstrip(" .")
    if not value:
        return "converted"
    if value.upper() in _WINDOWS_RESERVED_BASENAMES:
        return f"{value}-item"
    return value


def target_slug(value: str, kind: str) -> str:
    slug = slugify(value)
    suffix = "agent" if kind == "agent" else "skill"
    if slug.endswith(f"-{suffix}") or slug.endswith(f"-{suffix}s"):
        return slug
    return f"{slug}-{suffix}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_ignored_tree_path(path: Path) -> bool:
    return path.name in _IGNORED_TREE_FILE_NAMES or path.name.startswith(_IGNORED_TREE_FILE_PREFIXES)


def ignored_tree_names(names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in _IGNORED_TREE_FILE_NAMES or name.startswith(_IGNORED_TREE_FILE_PREFIXES)
    }


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not is_ignored_tree_path(p)):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    retry_fs(
        lambda: tmp.replace(path),
        operation=f"replace {path}",
    )


def state_path(state_dir: Path) -> Path:
    return state_dir / "state.json"


def load_state(state_dir: Path) -> dict[str, CustomizationArtifactState]:
    """Read state.json (schema_version=2 only).

    Older flat-shape state files written by v0.3 are not read — v0.4 is a
    pre-1.0 cutover for two known users (jmirodg, gabi) who regenerate state
    on first boot. Anything that isn't a v2 envelope rebuilds from scratch.
    """
    path = state_path(state_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.warning("Invalid state file, rebuilding: %s", path)
        return {}
    if not isinstance(data, dict) or data.get("schema_version") != STATE_SCHEMA_VERSION:
        logging.warning(
            "state.json is not schema_version=%d, rebuilding: %s",
            STATE_SCHEMA_VERSION,
            path,
        )
        return {}
    raw_entries = data.get("customization_artifacts")
    if not isinstance(raw_entries, dict):
        return {}
    result: dict[str, CustomizationArtifactState] = {}
    for pair_id, entry in raw_entries.items():
        try:
            validate_pair_id(pair_id)
        except InvalidPairId:
            logging.error("Skipping state entry with invalid pair_id=%r", pair_id)
            continue
        if not isinstance(entry, dict):
            continue
        try:
            result[pair_id] = CustomizationArtifactState.from_dict(entry)
        except (KeyError, ValueError):
            logging.warning("Skipping malformed state entry for pair_id=%s", pair_id)
    return result


def save_state(state_dir: Path, state: dict[str, CustomizationArtifactState]) -> None:
    path = state_path(state_dir)
    envelope = {
        "schema_version": STATE_SCHEMA_VERSION,
        "customization_artifacts": {pair_id: ps.to_dict() for pair_id, ps in state.items()},
    }
    atomic_write_text(
        path,
        json.dumps(envelope, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )
