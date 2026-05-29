"""State store — pair_id-keyed index + filesystem helpers."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents_sync.filesystem_windows_retry import retry_fs
from agents_sync.identity import InvalidPairId, validate_pair_id

STATE_SCHEMA_VERSION = 3


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
    """Per-agentic-tool slice of one customization artifact's state.

    ``slot`` is set only for artifacts whose ``file_layout`` is a
    ``SharedKeyedMapLayout`` (v0.5+ ``mcp_server`` artifacts). When set,
    ``path`` is the shared keyed-map file and ``slot`` is the key within
    the map identifying this artifact's entry. When ``None``, ``path``
    is the per-file artifact path as it has been since v0.2.

    ``path`` is a :class:`Path` in memory (it is one everywhere else in
    the engine — Phase 3.4 removes the legacy ``str`` exception that
    forced every caller to wrap reads in ``Path(...)``). On-disk
    serialisation still uses the string form so the JSON schema is
    unchanged.
    """

    path: Path
    last_seen: str | None = None
    last_written: str | None = None
    slot: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "path": str(self.path),
            "last_seen": self.last_seen,
            "last_written": self.last_written,
        }
        if self.slot is not None:
            data["slot"] = self.slot
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgenticToolState:
        return cls(
            path=Path(data["path"]),
            last_seen=data.get("last_seen"),
            last_written=data.get("last_written"),
            slot=data.get("slot"),
        )


@dataclass
class CustomizationArtifactState:
    """One managed customization artifact, projected across N agentic tools.

    ``last_modified`` is a wall-clock POSIX timestamp (seconds, float) updated
    every time the daemon writes new bytes for this pair. ``generation`` is a
    monotonic in-process counter that the daemon bumps on every write to this
    pair; it is the primary discriminator for the ``mtime_wins`` collision
    strategy at import time (US-12), with ``last_modified`` as the tiebreaker
    when comparing entries from different hosts. A ``None`` ``last_modified``
    predates the field; ``generation`` defaults to ``0`` and is treated as
    "no edits seen yet" for comparison.

    Cross-host clock skew (NTP rewind, VM resume, Windows local-time bug)
    therefore cannot, on its own, cause ``mtime_wins`` to overwrite a newer
    same-host edit with an older import — the local entry's generation always
    advances on each write and the import snapshot carries the generation it
    had at export time. Mixing edits across hosts whose clocks disagree is
    still the user's responsibility for the wall-clock tiebreaker.
    """

    kind: str  # "agent" | "skill" — serialized as "customization_type"
    agentic_tools: dict[str, AgenticToolState] = field(default_factory=dict)
    last_modified: float | None = None
    generation: int = 0

    def bump(self, *, now: float) -> None:
        """Record a write to this pair: advance generation, set last_modified."""
        self.generation += 1
        self.last_modified = now

    def to_dict(self) -> dict[str, Any]:
        return {
            "customization_type": self.kind,
            "last_modified": self.last_modified,
            "generation": self.generation,
            "agentic_tools": {
                name: at.to_dict() for name, at in self.agentic_tools.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CustomizationArtifactState:
        raw_tools = data.get("agentic_tools") or {}
        if not isinstance(raw_tools, dict):
            raise ValueError("agentic_tools must be a mapping")
        raw_last_modified = data.get("last_modified")
        last_modified: float | None
        if raw_last_modified is None:
            last_modified = None
        else:
            try:
                last_modified = float(raw_last_modified)
            except (TypeError, ValueError) as exc:
                raise ValueError("last_modified must be a number") from exc
        raw_generation = data.get("generation", 0)
        try:
            generation = int(raw_generation) if raw_generation is not None else 0
        except (TypeError, ValueError) as exc:
            raise ValueError("generation must be an integer") from exc
        return cls(
            kind=data["customization_type"],
            agentic_tools={
                name: AgenticToolState.from_dict(entry)
                for name, entry in raw_tools.items()
                if isinstance(entry, dict)
            },
            last_modified=last_modified,
            generation=generation,
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


def target_slug(value: str) -> str:
    """Return the filesystem-friendly form of an artifact `name`.

    The slug is the basename a daemon-projected counterpart will use on every
    agentic tool — sync is symmetric across tools, so an artifact named X
    lives at <root>/X (skill) or <root>/X.<ext> (agent) regardless of which
    tool currently holds the source. Agents and skills live in distinct
    config-keyed roots, so no kind-suffix is needed to disambiguate them.
    """
    return slugify(value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_ignored_tree_path(path: Path) -> bool:
    return path.name in _IGNORED_TREE_FILE_NAMES or path.name.startswith(
        _IGNORED_TREE_FILE_PREFIXES
    )


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
    """Write ``content`` to ``path`` atomically and crash-consistently.

    Steps: write to a unique temp file in the same directory, ``fsync`` the
    file before close, ``os.replace`` onto the target, then ``fsync`` the
    parent directory so the rename itself is durable on a crash.

    The unique temp suffix (``.{name}.{pid}.{uuid4}.tmp``) prevents two
    concurrent writers from clobbering each other's staging file: a fixed
    suffix would race on the inode of the temp itself.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    data = content.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        retry_fs(
            lambda: tmp.replace(path),
            operation=f"replace {path}",
        )
    except Exception:
        # Best-effort cleanup of the staging file; the user's data is still
        # safe (the rename never landed).
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    """``fsync`` the parent directory so a ``rename`` survives a power loss.

    No-op on Windows where ``os.open`` cannot open a directory; the rename
    itself is durable via the journal on NTFS/ReFS.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except (OSError, PermissionError):
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def state_path(state_dir: Path) -> Path:
    return state_dir / "state.json"


def load_state(state_dir: Path) -> dict[str, CustomizationArtifactState]:
    """Read ``state.json`` at the current ``STATE_SCHEMA_VERSION`` (v3).

    v0.4.1 introduced schema v3 (per-pair ``last_modified`` + per-tool
    ``slot``); v0.5 added the monotonic ``generation`` field. Older
    envelopes (v1, v2) are not migrated — v0.x was a pre-1.0 cutover and
    state-rebuild was always the documented recovery. This function only
    accepts the current schema_version constant; mismatches log at INFO
    and return an empty state.

    Anomalies are differentiated so the operator can tell silent rebuilds
    from genuine partial-write recovery:

    - **Absent** (no file): return ``{}`` quietly. This is the normal
      first-boot path.
    - **Wrong schema version** (older v0.x cutover): log INFO, rebuild
      empty (the documented v0.4 policy for our two pre-1.0 users).
    - **Corrupt** (unparseable JSON or wrong top-level shape): move the
      offending file to ``state_dir/quarantine/state-<timestamp>.json``,
      log ERROR with the quarantine path, then rebuild empty. The user
      can inspect the quarantined file to recover by hand.
    """
    path = state_path(state_dir)
    if not path.exists():
        return {}
    raw_text = _read_text_for_recovery(path)
    if raw_text is None:
        _quarantine_corrupt(state_dir, path, reason="unreadable bytes")
        return {}
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        _quarantine_corrupt(state_dir, path, reason="JSON parse error")
        return {}
    if not isinstance(data, dict):
        _quarantine_corrupt(state_dir, path, reason="root is not a JSON object")
        return {}
    schema_version = data.get("schema_version")
    if schema_version != STATE_SCHEMA_VERSION:
        logging.info(
            "state.json schema_version=%r is not %d; rebuilding from scratch: %s",
            schema_version, STATE_SCHEMA_VERSION, path,
        )
        return {}
    raw_entries = data.get("customization_artifacts")
    if not isinstance(raw_entries, dict):
        _quarantine_corrupt(
            state_dir, path,
            reason="customization_artifacts missing or not an object",
        )
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


def _read_text_for_recovery(path: Path) -> str | None:
    """Read ``path`` as UTF-8, returning ``None`` on read or decode failure
    or when the file exceeds :data:`parser_bounds.MAX_PARSE_BYTES`."""
    # Lazy import — parser_bounds depends on markdown_yaml_metadata_block at module load
    # time, and state.py is imported early in the chain.
    from agents_sync.parser_bounds import ParserBoundsExceeded, read_text_bounded

    try:
        return read_text_bounded(path, label=str(path))
    except ParserBoundsExceeded:
        logging.exception("State file exceeds parser bounds: %s", path)
        return None
    except (OSError, UnicodeDecodeError):
        logging.exception("Could not read %s", path)
        return None


def _quarantine_corrupt(state_dir: Path, source: Path, *, reason: str) -> None:
    """Move ``source`` into ``state_dir/quarantine/`` so the user can recover.

    Best-effort: a quarantine failure is logged but does not propagate (the
    caller still has to return an empty state so the daemon can make
    forward progress). The source file is removed after a successful move.
    """
    quarantine_dir = state_dir / "quarantine"
    try:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        timestamp = f"{int(_monotonic_ms()):d}"
        dest = quarantine_dir / f"{source.name}.{timestamp}.corrupt"
        retry_fs(
            lambda: source.replace(dest),
            operation=f"quarantine {source}",
        )
        logging.error(
            "Quarantined corrupt %s (%s) -> %s. "
            "Rebuilding from scratch; inspect the quarantined file to recover.",
            source, reason, dest,
        )
    except OSError:
        logging.exception(
            "Quarantine failed for %s (%s); leaving the file in place. "
            "Rebuilding from scratch — please remove or fix %s by hand.",
            source, reason, source,
        )


def _monotonic_ms() -> int:
    """Millisecond-precision monotonic counter for quarantine filenames."""
    import time as _time

    return int(_time.monotonic_ns() // 1_000_000)


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
