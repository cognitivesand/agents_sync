"""Customization library export — one transportable zip of the canonical store (S23b).

A library export captures every canonical in the store plus a manifest, so a user's
agent/skill library survives a machine move (US-12). Two properties govern the
export:

- **Read-only against the source** (AC-1/AC-2): each canonical store file's bytes
  are read **once** for a coherent point-in-time snapshot of that entry; a file that
  will not parse is skipped, never quarantined. The export walks the canonical store
  (the library's source of truth, NFR-16) — it omits ``state.json`` (host-specific)
  and the on-disk archive (local audit history), so it never reads or writes state.
- **Secret policy at egress** (NFR-15): under ``secrets_refused`` a canonical
  carrying literal secret material is skipped with one structured WARNING (NFR-13)
  and never shipped, so ``manifest.contains_secret_literals`` stays ``false``
  (AC-12/AC-13); under ``secrets_accepted`` it ships verbatim and the flag is
  ``true`` (AC-14). The scan (``find_secret_literals``) is heuristic and covers the
  structured credential fields (``env``/``headers``/``auth.*`` and the like) — but the
  entry ships the *raw* store bytes, so a literal placed in prose (``name``/
  ``description``/``body``) is NOT detected and DOES ship. That scan-vs-ship gap is
  not an export bug: it is NFR-15's **documented residual** — credentials belong in
  ``env``/``headers``, where any literal is caught regardless of shape.

The zip is materialised atomically — built in a sibling temp file and renamed onto
the target — so a non-writable export path aborts with ``PortableLibraryError`` and
leaves no partial export behind (AC-4). The import half lives in ``_import``.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import socket
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from agents_sync.atomic_file_writer import move_file_atomic
from agents_sync.canonical_store import canonical_file_path, list_canonical_ids
from agents_sync.portable_library._shared import (
    CANONICAL_PREFIX,
    MANIFEST_NAME,
    PORTABLE_LIBRARY_SCHEMA_VERSION,
    PortableLibraryError,
    read_canonical_document,
)
from agents_sync.secret_policy import (
    ALLOWED_SECRET_POLICIES,
    SECRET_POLICY_REFUSED,
    SecretFinding,
    find_secret_literals,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportEnvironment:
    """The host/runtime facts the manifest records — injected at the boundary (AC-1)."""

    now: datetime
    source_host: str
    source_platform: str
    agents_sync_version: str


@dataclass(frozen=True)
class ExportReport:
    """What an export shipped: the path, the artifact count, and the secret outcome."""

    export_path: Path
    artifact_count: int
    contains_secret_literals: bool
    skipped_secret_artifacts: tuple[str, ...]


def export_library(
    state_dir: Path,
    export_path: Path,
    *,
    secret_policy: str = SECRET_POLICY_REFUSED,
    environment: ExportEnvironment | None = None,
) -> ExportReport:
    """Write a library export of every canonical in ``state_dir`` to ``export_path``.

    Read-only against ``state_dir``; applies ``secret_policy`` at egress (NFR-15) and
    materialises the zip atomically (AC-4). Raises ``PortableLibraryError`` when the
    export path is not writable, leaving no partial file behind."""
    if secret_policy not in ALLOWED_SECRET_POLICIES:
        raise ValueError(
            f"unknown secret_policy: {secret_policy!r} (allowed: {sorted(ALLOWED_SECRET_POLICIES)})"
        )
    resolved = environment or _local_environment()
    shipped, skipped_secret, contains_secret = _collect_entries(state_dir, secret_policy)
    manifest = _build_manifest(resolved, len(shipped), contains_secret)
    _write_zip_atomic(export_path, manifest, shipped)
    return ExportReport(
        export_path=export_path,
        artifact_count=len(shipped),
        contains_secret_literals=contains_secret,
        skipped_secret_artifacts=skipped_secret,
    )


def _collect_entries(
    state_dir: Path, secret_policy: str
) -> tuple[dict[str, bytes], tuple[str, ...], bool]:
    """Read each store canonical once (point-in-time, AC-2) and apply the secret
    egress. Returns (shipped ``{id: raw bytes}``, skipped-secret ids, whether any
    shipped entry carried secret literals)."""
    shipped: dict[str, bytes] = {}
    skipped_secret: list[str] = []
    contains_secret = False
    for artifact_id in list_canonical_ids(state_dir):
        raw = _read_entry_bytes(state_dir, artifact_id)
        document = None if raw is None else read_canonical_document(raw)
        if raw is None or document is None:
            _LOGGER.warning(
                "library export skipping unreadable canonical: artifact_id=%s", artifact_id
            )
            continue
        findings = find_secret_literals(document)
        if findings and not _ship_secret_bearing(artifact_id, findings, secret_policy):
            skipped_secret.append(artifact_id)
            continue
        contains_secret = contains_secret or bool(findings)
        shipped[artifact_id] = raw
    return shipped, tuple(skipped_secret), contains_secret


def _ship_secret_bearing(
    artifact_id: str, findings: tuple[SecretFinding, ...], secret_policy: str
) -> bool:
    """Log the secret finding (NFR-13) and report whether to ship it: never under
    ``secrets_refused`` (AC-13), verbatim under ``secrets_accepted`` (AC-14)."""
    field_paths = [finding.field_path for finding in findings]
    if secret_policy == SECRET_POLICY_REFUSED:
        _LOGGER.warning(
            "library export skipping secret-bearing canonical under secret_policy=%s: "
            "artifact_id=%s fields=%s",
            secret_policy,
            artifact_id,
            field_paths,
        )
        return False
    _LOGGER.warning(
        "library export shipping secret-bearing canonical under secret_policy=%s: "
        "artifact_id=%s fields=%s",
        secret_policy,
        artifact_id,
        field_paths,
    )
    return True


def _read_entry_bytes(state_dir: Path, artifact_id: str) -> bytes | None:
    """One atomic point-in-time read of the store file (AC-2); read-only — a corrupt
    file is never quarantined (AC-1). ``None`` on an I/O failure."""
    try:
        return canonical_file_path(state_dir, artifact_id).read_bytes()
    except OSError as error:
        _LOGGER.warning(
            "library export could not read canonical: artifact_id=%s (%s)", artifact_id, error
        )
        return None


def _build_manifest(
    environment: ExportEnvironment, artifact_count: int, contains_secret_literals: bool
) -> dict[str, Any]:
    return {
        "schema_version": PORTABLE_LIBRARY_SCHEMA_VERSION,
        "exported_at": environment.now.isoformat(),
        "source_host": environment.source_host,
        "source_platform": environment.source_platform,
        "agents_sync_version": environment.agents_sync_version,
        "artifact_count": artifact_count,
        "contains_secret_literals": contains_secret_literals,
    }


def _write_zip_atomic(
    export_path: Path, manifest: dict[str, Any], entries: Mapping[str, bytes]
) -> None:
    """Build the zip in a sibling temp file, then atomically rename it onto the
    target (AC-4). A non-writable path (missing parent, permission denied, disk full)
    raises ``PortableLibraryError`` and leaves no partial export."""
    try:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{export_path.name}.", suffix=".tmp", dir=export_path.parent
        )
    except OSError as error:
        raise PortableLibraryError(
            f"library export path is not writable: {export_path} ({error})"
        ) from error
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            for artifact_id, raw in sorted(entries.items()):
                archive.writestr(f"{CANONICAL_PREFIX}{artifact_id}.json", raw)
        move_file_atomic(temp_path, export_path)
    except OSError as error:
        temp_path.unlink(missing_ok=True)
        raise PortableLibraryError(
            f"library export failed writing {export_path}: {error}"
        ) from error
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _local_environment() -> ExportEnvironment:
    return ExportEnvironment(
        now=datetime.now(tz=UTC),
        source_host=socket.gethostname(),
        source_platform=platform.system(),
        agents_sync_version=_agents_sync_version(),
    )


def _agents_sync_version() -> str:
    try:
        return version("agents_sync")
    except PackageNotFoundError:
        return "0.0.0+unknown"
