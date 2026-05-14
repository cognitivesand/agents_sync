"""Pure helpers that render canonical state onto a tool's on-disk artifact
and record the resulting paths and digests in sync state.

These functions take every dependency as an explicit parameter; they hold no
instance state and do not mutate the caller's objects (other than the
``state`` dict explicitly passed to ``update_state_n_way``). Keeping them
out of the Syncer class lets the orchestrator stay focused on control flow.
"""
from __future__ import annotations

import os
import shutil
import sys
import unicodedata
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import AgenticToolSpec, CustomizationTypeIO
from agents_sync.config import expand_path
from agents_sync.filesystem_windows_retry import retry_fs
from agents_sync.state import (
    AgenticToolState,
    CustomizationArtifactState,
    atomic_write_text,
    ignored_tree_names,
    sha256_file,
    sha256_tree,
    target_slug,
)


# ---------- path identity ----------

def path_collision_key(path: Path) -> str:
    """Normalise a path so that two visually-different strings that point to
    the same on-disk entry compare equal (NFC normalisation, case-folding
    on macOS / Windows, NFD-stripping on Linux)."""
    resolved = path.resolve()
    normalized = unicodedata.normalize("NFC", str(resolved))
    normcased = os.path.normcase(normalized)
    if sys.platform in {"darwin", "win32"}:
        return normcased.casefold()
    elif os.name != "nt" and normcased != normalized:
        return normcased
    return normalized


def assert_target_available(target: Path, existing_path: Path | None) -> None:
    """Refuse to overwrite a target that doesn't already belong to this pair."""
    if existing_path is not None and (
        path_collision_key(target) == path_collision_key(existing_path)
    ):
        return
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite unowned target path: {target}")


# ---------- directory-skill atomic staging ----------

def _clear_stale_paths(*paths: Path) -> None:
    """Remove leftover staging siblings (`.tmp` / `.old`) before atomic-swap."""
    for path in paths:
        if path.exists():
            retry_fs(
                lambda p=path: shutil.rmtree(p),
                operation=f"rmtree {path}",
            )


def _rename_with_rollback(tmp: Path, target: Path, *, backup: Path) -> None:
    """Replace `target` with `tmp`. If `target` already exists, move it aside to
    `backup` first and restore it on failure; otherwise rename `tmp` directly."""
    target_existed = target.exists()
    if target_existed:
        retry_fs(
            lambda: target.rename(backup),
            operation=f"rename {target} -> {backup}",
        )
    try:
        retry_fs(
            lambda: tmp.rename(target),
            operation=f"rename {tmp} -> {target}",
        )
    except Exception:
        if target_existed:
            retry_fs(
                lambda: backup.rename(target),
                operation=f"rollback {backup} -> {target}",
            )
        raise
    if target_existed:
        retry_fs(
            lambda: shutil.rmtree(backup),
            operation=f"cleanup {backup}",
        )


def stage_skill_dir(source: Path, target: Path, skill_md_content: str) -> None:
    """Stage a fresh copy of `source` as `target` and overwrite SKILL.md atomically."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    old = target.with_name(f".{target.name}.old")
    _clear_stale_paths(tmp, old)
    shutil.copytree(source, tmp, ignore=lambda _dir, names: ignored_tree_names(names))
    atomic_write_text(tmp / "SKILL.md", skill_md_content)
    _rename_with_rollback(tmp, target, backup=old)


# ---------- artifact rendering ----------

def write_artifact_inplace(io: CustomizationTypeIO, path: Path, text: str) -> None:
    """Write `text` back to the artifact-metadata location at `path`."""
    if io.storage == "single_file":
        atomic_write_text(path, text)
    else:
        atomic_write_text(path / "SKILL.md", text)


def render_to_agentic_tool(
    config: dict[str, Any],
    spec: AgenticToolSpec,
    kind: str,
    canonical: dict[str, Any],
    *,
    existing_path: Path | None,
    prior_text: str | None,
    source_dir: Path | None,
) -> Path:
    """Render `canonical` onto one target tool. Returns the resulting path.

    `prior_text` lets renderers that preserve user-frontmatter ordering reuse
    the existing on-disk bytes. `source_dir` is the directory whose
    non-SKILL.md siblings must be staged forward (directory_skill only).
    """
    io = spec.io[kind]
    root = expand_path(config[spec.config_dir_keys[kind]])
    slug = target_slug(canonical["name"])
    if io.storage == "single_file":
        target = existing_path or (root / f"{slug}{io.file_suffix}")
        assert_target_available(target, existing_path)
        atomic_write_text(target, io.render(canonical, prior_text))
        return target
    if io.storage == "directory_skill":
        target_dir = existing_path or (root / slug)
        assert_target_available(target_dir, existing_path)
        skill_md_text = io.render(canonical, prior_text)
        if source_dir is not None and target_dir != source_dir:
            stage_skill_dir(source_dir, target_dir, skill_md_text)
        else:
            target_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target_dir / "SKILL.md", skill_md_text)
        return target_dir
    raise ValueError(f"Unknown storage shape: {io.storage}")


# ---------- state update ----------

def update_state_n_way(
    state: dict[str, CustomizationArtifactState],
    pair_id: str,
    kind: str,
    paths: dict[str, Path],
    agentic_tools: dict[str, AgenticToolSpec],
) -> None:
    """Record `paths` (one per tool) into `state[pair_id]`, computing digests."""
    ps = state.setdefault(pair_id, CustomizationArtifactState(kind=kind))
    ps.kind = kind
    for tool_name, path in paths.items():
        spec = agentic_tools[tool_name]
        io = spec.io[kind]
        digest = (
            sha256_file(path) if io.storage == "single_file" else sha256_tree(path)
        )
        ps.agentic_tools[tool_name] = AgenticToolState(
            path=str(path),
            last_seen=digest,
            last_written=digest,
        )
