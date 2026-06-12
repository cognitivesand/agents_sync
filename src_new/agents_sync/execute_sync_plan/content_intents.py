"""Executor content family — absorb, project/reproject, rebuild (proposal §8).

Each handler is one per-artifact transaction: every displaced byte is archived
FIRST, and only if all archives landed are any overwrites performed and records
mutated (US-06 AC-6). The secret policy guards the absorb and render egress
points (NFR-15). An identical render is skipped — repeated polls with no user
change produce no writes and no archive entries (NFR-05/07).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agents_sync.artifact_archive import archive_copy
from agents_sync.atomic_file_writer import write_text_atomic
from agents_sync.canonical_store import load_canonical, save_canonical
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.plan.winner_selection import freshest
from agents_sync.domain_model.sync_plan import AbsorbToolEdit, RebuildCorruptCanonical
from agents_sync.domain_model.sync_state import ArtifactRecord, RecordedSurface
from agents_sync.domain_model.tool_surface import ToolSurface
from agents_sync.execute_sync_plan._shared import (
    ExecutionContext,
    IntentAbortError,
    target_file,
)
from agents_sync.read_tool_surfaces import surface_content_digest
from agents_sync.secret_policy import enforce_secret_policy
from agents_sync.translation import canonical_to_file


def absorb_tool_edit(intent: AbsorbToolEdit, execution: ExecutionContext) -> None:
    """Fold the winning surface's parsed content into the stored canonical."""
    observation = execution.observations_by_location.get(intent.source.location)
    if observation is None or not isinstance(observation.parsed, CanonicalDocument):
        raise IntentAbortError(f"absorb source has no parsed observation: {intent.source.location}")
    canonical = observation.parsed
    if not canonical.artifact_id:
        canonical = replace(canonical, artifact_id=intent.artifact_id)
    enforce_secret_policy(
        canonical, execution.secret_policy_value, artifact_label=intent.artifact_id
    )
    save_canonical(execution.state_dir, canonical)
    record = execution.records.get(intent.artifact_id, ArtifactRecord())
    execution.records[intent.artifact_id] = replace(
        record,
        name=canonical.name,
        canonical_digest=canonical.content_digest(),
        surfaces={
            **record.surfaces,
            intent.source.tool: RecordedSurface(
                location=intent.source.location,
                content_digest=observation.content_digest,
            ),
        },
    )
    execution.changed += 1


def project_canonical(
    artifact_id: str, targets: tuple[ToolSurface, ...], execution: ExecutionContext
) -> None:
    """Render the stored canonical onto ``targets`` as one per-artifact transaction:
    render all, archive all displaced bytes, and only then write."""
    canonical = load_canonical(execution.state_dir, artifact_id)
    if not isinstance(canonical, CanonicalDocument):
        raise IntentAbortError(f"no stored canonical to project for {artifact_id}")
    enforce_secret_policy(canonical, execution.secret_policy_value, artifact_label=artifact_id)
    render_files = [target_file(target) for target in targets]
    if len(set(render_files)) != len(render_files):
        # two targets sharing one file would clobber each other's render — a recipe
        # bug that must fail loud, not corrupt (watch-item until tools-as-data S20).
        raise ValueError(f"project targets share a render file for {artifact_id}")
    pending_writes: list[tuple[ToolSurface, Path, str]] = []
    for target in targets:
        render_file = target_file(target)
        prior_text = render_file.read_text(encoding="utf-8") if render_file.exists() else None
        new_text = canonical_to_file(canonical, target, prior_text)
        if new_text == prior_text:
            continue  # identical render: no write, no archive (NFR-05/07)
        if prior_text is not None:
            archive_copy(execution.state_dir, artifact_id, target.tool, render_file)
        pending_writes.append((target, render_file, new_text))
    # every displaced byte is archived — now, and only now, overwrite.
    record = execution.records.get(artifact_id, ArtifactRecord())
    written_surfaces = dict(record.surfaces)
    for target, render_file, new_text in pending_writes:
        write_text_atomic(render_file, new_text)
        written_surfaces[target.tool] = RecordedSurface(
            location=target.location,
            content_digest=surface_content_digest(new_text, target),
        )
    if pending_writes:
        execution.records[artifact_id] = replace(
            record,
            name=canonical.name or record.name,
            canonical_digest=canonical.content_digest(),
            surfaces=written_surfaces,
        )
        execution.changed += 1


def rebuild_corrupt_canonical(intent: RebuildCorruptCanonical, execution: ExecutionContext) -> None:
    """The stored canonical was lost (quarantined): rebuild it from the freshest
    parseable recorded surface (US-09 AC-4)."""
    record = execution.records.get(intent.artifact_id, ArtifactRecord())
    parseable = [
        observation
        for observation in (
            execution.observations_by_location.get(recorded.location)
            for recorded in record.surfaces.values()
        )
        if observation is not None and isinstance(observation.parsed, CanonicalDocument)
    ]
    if not parseable:
        raise IntentAbortError(
            f"no parseable surface to rebuild canonical for {intent.artifact_id}"
        )
    winner = freshest(parseable)
    canonical = winner.parsed
    assert isinstance(canonical, CanonicalDocument)
    if not canonical.artifact_id:
        canonical = replace(canonical, artifact_id=intent.artifact_id)
    enforce_secret_policy(
        canonical, execution.secret_policy_value, artifact_label=intent.artifact_id
    )
    save_canonical(execution.state_dir, canonical)
    execution.records[intent.artifact_id] = replace(
        record, name=canonical.name, canonical_digest=canonical.content_digest()
    )
    execution.changed += 1
