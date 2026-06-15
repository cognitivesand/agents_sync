"""Executor identity family — adopt (the SOLE mint), absorb-into-managed, rename, remove.

The same transactional discipline as the content family: pre-injection and
displaced bytes are archived before any overwrite; a removal archives the
surface's bytes (and the canonical, under the reserved ``_canonical`` side,
US-05 AC-5) before deleting; a rename relocates each projection to the new slug
with the old bytes archived (US-04). ``adopt_new_artifact`` is the single place
an artifact id is born (AD-2): the canonical is written before the record, so an
interruption leaves an orphan canonical the next poll heals (NFR-04).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agents_sync.artifact_archive import archive_copy, archive_move, archive_text
from agents_sync.atomic_file_writer import write_text_atomic
from agents_sync.canonical_store import canonical_file_path, load_canonical, save_canonical
from agents_sync.domain_model.artifact_identity import mint_artifact_id
from agents_sync.domain_model.artifact_naming import slugify_name
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.sync_plan import (
    AdoptNewArtifact,
    RemoveArtifact,
    RenameArtifact,
)
from agents_sync.domain_model.sync_state import ArtifactRecord, RecordedSurface
from agents_sync.domain_model.tool_surface import KeyedMapSlot, ToolSurface
from agents_sync.execute_sync_plan._shared import (
    ExecutionContext,
    IntentAbortError,
    recorded_targets,
    reject_shared_write_file,
    target_file,
)
from agents_sync.read_tool_surfaces import surface_content_digest
from agents_sync.secret_policy import enforce_secret_policy
from agents_sync.translation import (
    canonical_to_file,
    remove_surface_content,
    surface_fragment_text,
)


def adopt_new_artifact(intent: AdoptNewArtifact, execution: ExecutionContext) -> None:
    """Mint an id for the winning candidate group and inject it into every surface."""
    observation = execution.observations_by_location.get(intent.source.location)
    if observation is None or not isinstance(observation.parsed, CanonicalDocument):
        raise IntentAbortError(f"adopt source has no parsed observation: {intent.source.location}")
    minted_id = mint_artifact_id()
    canonical = replace(observation.parsed, artifact_id=minted_id)
    enforce_secret_policy(
        canonical, execution.secret_policy_value, artifact_label=str(intent.source.location)
    )
    surfaces = (intent.source, *intent.others)
    reject_shared_write_file(surfaces, minted_id)
    # archive every surface's pre-injection bytes first (US-03; NFR-01)
    pending_writes: list[tuple[ToolSurface, str]] = []
    for surface in surfaces:
        surface_file = target_file(surface)
        prior_text = surface_file.read_text(encoding="utf-8")
        _archive_surface_bytes(minted_id, surface, prior_text, execution)
        pending_writes.append((surface, canonical_to_file(canonical, surface, prior_text)))
    # the canonical lands before the record: an interruption heals as an orphan (NFR-04)
    save_canonical(execution.state_dir, canonical)
    recorded_surfaces: dict[str, RecordedSurface] = {}
    for surface, new_text in pending_writes:
        write_text_atomic(target_file(surface), new_text)
        recorded_surfaces[surface.tool] = RecordedSurface(
            location=surface.location,
            content_digest=surface_content_digest(new_text, surface),
        )
    execution.records[minted_id] = ArtifactRecord(
        name=canonical.name,
        canonical_digest=canonical.content_digest(),
        surfaces=recorded_surfaces,
    )
    execution.changed += 1


def rename_artifact(intent: RenameArtifact, execution: ExecutionContext) -> None:
    """Relocate every projection to the new slug, archiving the old bytes (US-04).

    Two phases (US-06 AC-6): read + archive EVERY surface first; only when all
    archives landed are any writes or unlinks performed."""
    stored = load_canonical(execution.state_dir, intent.artifact_id)
    if not isinstance(stored, CanonicalDocument):
        raise IntentAbortError(f"no stored canonical to rename for {intent.artifact_id}")
    canonical = replace(stored, name=intent.new_name)
    enforce_secret_policy(
        canonical, execution.secret_policy_value, artifact_label=intent.artifact_id
    )
    old_surfaces = recorded_targets(intent.artifact_id, execution)
    reject_shared_write_file(old_surfaces, intent.artifact_id)
    pending: list[tuple[ToolSurface, Path, str, Path | None]] = []
    for old_surface in old_surfaces:
        new_surface = _renamed_surface(old_surface, intent.new_name)
        old_file = target_file(old_surface)
        prior_text = old_file.read_text(encoding="utf-8")
        _archive_surface_bytes(intent.artifact_id, old_surface, prior_text, execution)
        if isinstance(old_surface.location, KeyedMapSlot):
            # one shared file: add the new slot, drop the old, write once, no unlink.
            with_new_slot = canonical_to_file(canonical, new_surface, prior_text)
            final_text = remove_surface_content(with_new_slot, old_surface)
            assert final_text is not None  # a slot surface always reassembles
            pending.append((new_surface, old_file, final_text, None))
        else:
            final_text = canonical_to_file(canonical, new_surface, prior_text)
            pending.append((new_surface, target_file(new_surface), final_text, old_file))
    # every old-slug byte is archived — now, and only now, relocate.
    record = execution.records.get(intent.artifact_id, ArtifactRecord())
    relocated: dict[str, RecordedSurface] = dict(record.surfaces)
    for new_surface, write_file, final_text, unlink_file in pending:
        write_text_atomic(write_file, final_text)
        if unlink_file is not None:
            unlink_file.unlink()  # the old-slug bytes are already archived
        relocated[new_surface.tool] = RecordedSurface(
            location=new_surface.location,
            content_digest=surface_content_digest(final_text, new_surface),
        )
    save_canonical(execution.state_dir, canonical)
    execution.records[intent.artifact_id] = replace(
        record,
        name=intent.new_name,
        canonical_digest=canonical.content_digest(),
        surfaces=relocated,
    )
    execution.changed += 1


def remove_artifact(intent: RemoveArtifact, execution: ExecutionContext) -> None:
    """Archive then remove the artifact's surviving projections and its canonical.

    Two phases (US-06 AC-6): archive EVERY surviving surface (copies — nothing is
    destroyed yet); only when all archives landed are deletions performed."""
    pending: list[tuple[Path, str | None]] = []  # (file, remaining text | None = delete file)
    for surface in recorded_targets(intent.artifact_id, execution):
        surface_file = target_file(surface)
        prior_text = surface_file.read_text(encoding="utf-8")
        _archive_surface_bytes(intent.artifact_id, surface, prior_text, execution)
        pending.append((surface_file, remove_surface_content(prior_text, surface)))
    # every surviving byte is archived — now, and only now, delete.
    for surface_file, remaining in pending:
        if remaining is None:
            surface_file.unlink()
        else:
            write_text_atomic(surface_file, remaining)
    stored_canonical = canonical_file_path(execution.state_dir, intent.artifact_id)
    if stored_canonical.exists():
        # a stale canonical can never be re-projected (NFR-16); bytes kept (US-05 AC-5)
        archive_move(execution.state_dir, intent.artifact_id, "_canonical", stored_canonical)
    execution.records.pop(intent.artifact_id, None)
    execution.changed += 1


def _archive_surface_bytes(
    artifact_id: str,
    surface: ToolSurface,
    prior_text: str,
    execution: ExecutionContext,
) -> None:
    """Archive the bytes this surface owns: a COPY of the whole file for a per-file
    surface (nothing destroyed — phase 2 owns deletions), the slot's serialization
    for a keyed-map slot."""
    location = surface.location
    if isinstance(location, KeyedMapSlot):
        archive_text(
            execution.state_dir,
            artifact_id,
            surface.tool,
            location.slot,
            location.file.suffix,
            surface_fragment_text(prior_text, surface),
        )
        return
    archive_copy(execution.state_dir, artifact_id, surface.tool, location)


def _renamed_surface(old_surface: ToolSurface, new_name: str) -> ToolSurface:
    """The surface relocated to the new slug: a new filename stem for a per-file
    surface, a new slot key (the raw name) for a keyed-map slot."""
    location = old_surface.location
    new_location: KeyedMapSlot | Path
    if isinstance(location, KeyedMapSlot):
        new_location = KeyedMapSlot(file=location.file, slot=new_name)
    else:
        new_location = location.with_name(f"{slugify_name(new_name)}{location.suffix}")
    return replace(old_surface, location=new_location)
