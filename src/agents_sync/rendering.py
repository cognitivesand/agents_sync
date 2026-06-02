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
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    DirectorySkillLayout,
    SharedKeyedMapLayout,
    SingleFileLayout,
)
from agents_sync.config import expand_path
from agents_sync.filesystem_windows_retry import retry_fs
from agents_sync.shared_keyed_map_io import apply_slot, read_slots
from agents_sync.state import (
    AgenticToolState,
    CustomizationArtifactState,
    atomic_write_text,
    ignored_tree_names,
    sha256_skill_tree_snapshot,
    sha256_text,
    target_slug,
)
from agents_sync.sync_types import RenderResult

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


def slot_aware_collision_key(path: Path, slot: str | None) -> tuple[str, str | None]:
    """Composite collision key for both per-file and shared-keyed-map
    artifacts. Two slots in the same shared file are distinct artifacts;
    two artifacts targeting the same (file, None) per-file path collide
    as before."""
    return (path_collision_key(path), slot)


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
                # mypy cannot infer the return type of a default-arg lambda passed
                # to a generic callable; the body returns None as retry_fs expects.
                lambda p=path: shutil.rmtree(p),  # type: ignore[misc]
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


def read_artifact_text(
    io: CustomizationTypeIO,
    path: Path,
    slot: str | None = None,
) -> str:
    """Read the artifact-metadata text for an artifact at `path`.

    For ``SharedKeyedMapLayout`` artifacts, ``slot`` must be supplied;
    the function reads the shared file, extracts the slot's value, and
    returns it serialised via the layout's format handler. For per-file
    artifacts ``slot`` must be ``None``.
    """
    layout = io.file_layout
    if isinstance(layout, SharedKeyedMapLayout):
        if slot is None:
            raise ValueError("SharedKeyedMapLayout requires a slot to read")
        slots, _ = read_slots(path, layout)
        return slots.get(slot, "")
    if isinstance(layout, SingleFileLayout):
        return path.read_text(encoding="utf-8")
    if isinstance(layout, DirectorySkillLayout):
        return (path / "SKILL.md").read_text(encoding="utf-8")
    raise ValueError(f"Unknown file layout: {type(layout).__name__}")


def write_artifact_inplace(
    io: CustomizationTypeIO,
    path: Path,
    text: str,
    slot: str | None = None,
) -> str | None:
    """Write ``text`` back to the artifact-metadata location at ``path``.

    For ``SharedKeyedMapLayout`` artifacts the write is a slot
    insert / replace inside the shared file; the prior slot text is
    returned so the caller can archive it (the shared file as a whole
    is never archived, only the changed slot). For per-file artifacts
    returns ``None``.
    """
    layout = io.file_layout
    if isinstance(layout, SharedKeyedMapLayout):
        if slot is None:
            raise ValueError("SharedKeyedMapLayout requires a slot to write")
        return apply_slot(
            path,
            layout,
            slot,
            text,
            expected_pair_id=io.extract_pair_id(text),
            allow_unpaired_existing=True,
        )
    if isinstance(layout, SingleFileLayout):
        atomic_write_text(path, text)
    elif isinstance(layout, DirectorySkillLayout):
        atomic_write_text(path / "SKILL.md", text)
    else:
        raise ValueError(f"Unknown file layout: {type(layout).__name__}")
    return None


class UnconfiguredRootError(RuntimeError):
    """A (tool, kind) cell was asked to render but has no configured root.

    With participation gated on ``ToolStatusTracker.is_kind_available`` this
    never fires in normal flow; it is a loud guardrail so a future caller that
    bypasses that gate fails fast here instead of crashing on ``Path(None)``.
    """


def render_to_agentic_tool(
    config: Mapping[str, Any],
    spec: AgenticToolSpec,
    kind: str,
    canonical: dict[str, Any],
    *,
    existing_path: Path | None,
    prior_text: str | None,
    source_dir: Path | None,
    existing_slot: str | None = None,
    allow_unpaired_existing_slot: bool = False,
) -> RenderResult:
    """Render ``canonical`` onto one target tool. Returns where it landed.

    ``prior_text`` lets renderers that preserve user-frontmatter ordering
    reuse the existing on-disk bytes. ``source_dir`` is the directory
    whose non-SKILL.md siblings must be staged forward (directory_skill
    only). ``existing_slot`` is the slot key for keyed-map targets that
    already have an entry under this pair_id; the renderer rewrites
    that slot rather than minting a new one.
    """
    io = spec.io[kind]
    slugger = io.slugify_name or target_slug
    slug = slugger(canonical["name"])
    layout = io.file_layout
    if isinstance(layout, SharedKeyedMapLayout):
        return _render_keyed_map_slot(
            config,
            io,
            canonical,
            slug,
            existing_slot=existing_slot,
            allow_unpaired_existing_slot=allow_unpaired_existing_slot,
            prior_text=prior_text,
        )
    raw_root = config.get(spec.config_dir_keys[kind])
    if raw_root is None:
        raise UnconfiguredRootError(
            f"{spec.name}/{kind} has no configured root "
            f"({spec.config_dir_keys[kind]}); cannot render"
        )
    root = expand_path(raw_root)
    if isinstance(layout, SingleFileLayout):
        return _render_single_file(
            io,
            canonical,
            root,
            slug,
            existing_path,
            prior_text,
        )
    if isinstance(layout, DirectorySkillLayout):
        return _render_directory_skill(
            io,
            canonical,
            root,
            slug,
            existing_path,
            prior_text,
            source_dir,
        )
    raise ValueError(f"Unknown file layout: {type(layout).__name__}")


def _render_keyed_map_slot(
    config: Mapping[str, Any],
    io: CustomizationTypeIO,
    canonical: dict[str, Any],
    slug: str,
    *,
    existing_slot: str | None,
    allow_unpaired_existing_slot: bool,
    prior_text: str | None,
) -> RenderResult:
    layout = io.file_layout
    assert isinstance(layout, SharedKeyedMapLayout)
    shared_path = expand_path(config[layout.shared_path_config_key])
    slot_key = existing_slot or str(canonical.get(layout.key_field, slug))
    slot_text = io.render(canonical, prior_text)
    pair_id = canonical.get("pair_id")
    prior_slot_text = apply_slot(
        shared_path,
        layout,
        slot_key,
        slot_text,
        expected_pair_id=str(pair_id) if pair_id else None,
        allow_unpaired_existing=allow_unpaired_existing_slot,
    )
    return RenderResult(
        path=shared_path,
        slot=slot_key,
        prior_slot_text=prior_slot_text,
    )


def _render_single_file(
    io: CustomizationTypeIO,
    canonical: dict[str, Any],
    root: Path,
    slug: str,
    existing_path: Path | None,
    prior_text: str | None,
) -> RenderResult:
    target = existing_path or single_file_target(root, io, slug)
    assert_target_available(target, existing_path)
    atomic_write_text(target, io.render(canonical, prior_text))
    return RenderResult(path=target)


def _render_directory_skill(
    io: CustomizationTypeIO,
    canonical: dict[str, Any],
    root: Path,
    slug: str,
    existing_path: Path | None,
    prior_text: str | None,
    source_dir: Path | None,
) -> RenderResult:
    target_dir = existing_path or (root / slug)
    assert_target_available(target_dir, existing_path)
    skill_md_text = io.render(canonical, prior_text)
    if source_dir is not None and target_dir != source_dir:
        stage_skill_dir(source_dir, target_dir, skill_md_text)
    else:
        target_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target_dir / "SKILL.md", skill_md_text)
    return RenderResult(path=target_dir)


def single_file_target(root: Path, io: CustomizationTypeIO, slug: str) -> Path:
    layout = io.file_layout
    if not isinstance(layout, SingleFileLayout):
        raise ValueError(f"SingleFileLayout required, got {type(layout).__name__}")
    if layout.fixed_file_name is not None:
        return root / layout.fixed_file_name
    return root / f"{slug}{layout.file_suffix}"


# ---------- state update ----------


def update_state_n_way(
    state: dict[str, CustomizationArtifactState],
    pair_id: str,
    kind: str,
    results: dict[str, RenderResult],
    agentic_tools: dict[str, AgenticToolSpec],
) -> None:
    """Record ``results`` (one per tool) into ``state[pair_id]``, computing
    digests.

    The recorded digest must be computed the same way the discovery walker
    computes it (``enumerator``), or a poll would see a phantom change: both
    hash the universal-newline-normalized text the daemon reads, so a CRLF
    artifact and its LF form are the same content. ``SharedKeyedMapLayout``
    hashes the slot text (re-read via ``read_slots``); ``SingleFileLayout``
    hashes the read artifact text; ``DirectorySkillLayout`` hashes the tree
    with ``SKILL.md`` taken from its read-text snapshot.
    """
    ps = state.setdefault(pair_id, CustomizationArtifactState(kind=kind))
    ps.kind = kind
    for tool_name, result in results.items():
        spec = agentic_tools[tool_name]
        io = spec.io[kind]
        layout = io.file_layout
        if isinstance(layout, SharedKeyedMapLayout):
            slots, _ = read_slots(result.path, layout)
            slot_text = slots.get(result.slot or "", "")
            digest = sha256_text(slot_text)
        elif isinstance(layout, SingleFileLayout):
            digest = sha256_text(read_artifact_text(io, result.path))
        elif isinstance(layout, DirectorySkillLayout):
            digest = sha256_skill_tree_snapshot(result.path, read_artifact_text(io, result.path))
        else:
            raise ValueError(f"Unknown file layout: {type(layout).__name__}")
        ps.agentic_tools[tool_name] = AgenticToolState(
            path=result.path,
            last_seen=digest,
            last_written=digest,
            slot=result.slot,
        )
