"""Unit tests for the sync-plan vocabulary (rebuild S4).

`IntentKind` is the closed set of decisions the pure planner (S5–S8) emits and the
executor (S19) performs — named exactly per proposal §6. `SyncResult` is the
immutable per-poll outcome the daemon reports: `changed` is a plain count, while
`failed` / `blocked` / `frozen` / `diagnosed` carry the artifact identities the
spec needs by identity — the failure budget (FR-02), the freeze set (FR-11), and
the one-diagnostic-per-bad-surface dedupe (NFR-13). Only the vocabulary + result
value object are built yet (YAGNI): the per-intent payload dataclasses grow with
their emitter in S5–S8. The contract under test — a spec-pinned closed intent
vocabulary and a hashable result with correct value semantics — is load-bearing:
the executor switches on the vocabulary and transition-only logging dedupes on the
result's identity tuples.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from agents_sync.domain_model.sync_plan import (
    AbsorbIntoManaged,
    AbsorbToolEdit,
    AdoptNewArtifact,
    FreezeArtifact,
    IntentKind,
    ProjectToTools,
    RebuildCorruptCanonical,
    RejectCollision,
    RemoveArtifact,
    RenameArtifact,
    ReportUnadoptable,
    ReprojectCanonical,
    SyncPlan,
    SyncResult,
)
from agents_sync.domain_model.tool_surface import SurfaceFormat, ToolSurface

_INTENT_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
_INTENT_SURFACE = ToolSurface(
    tool="claude",
    kind="agent",
    location=Path("/u/.claude/agents/reviewer.md"),
    surface_format=SurfaceFormat(dialect="markdown_frontmatter"),
)

# The 11 intents the proposal §6 table names — the closed contract S5–S8 emit and
# S19 performs. Pinned here so adding, dropping, or renaming an intent is a
# deliberate test change, not a silent drift caught later in the planner/executor.
_SPEC_INTENT_NAMES = frozenset(
    {
        "ADOPT_NEW_ARTIFACT",
        "ABSORB_TOOL_EDIT",
        "ABSORB_INTO_MANAGED",
        "PROJECT_TO_TOOLS",
        "RENAME_ARTIFACT",
        "REMOVE_ARTIFACT",
        "REPROJECT_CANONICAL",
        "FREEZE_ARTIFACT",
        "REBUILD_CORRUPT_CANONICAL",
        "REJECT_COLLISION",
        "REPORT_UNADOPTABLE",
    }
)

# A result with every field at a distinct non-default value, so a per-field
# override below proves each field independently participates in equality.
_POPULATED_RESULT_KWARGS: dict[str, object] = {
    "changed": 1,
    "failed": ("failed-a",),
    "blocked": ("blocked-b",),
    "frozen": ("frozen-c",),
    "diagnosed": ("diagnosed-d",),
}


def test_intent_kind_is_exactly_the_eleven_spec_intents() -> None:
    # Pins the vocabulary to proposal §6: a dropped, added, or renamed intent
    # fails here, not silently downstream in the planner or executor.
    assert {member.name for member in IntentKind} == _SPEC_INTENT_NAMES


def test_sync_result_defaults_to_an_empty_poll() -> None:
    # An idle poll changed nothing and recorded no failure, block, freeze, or
    # diagnosis — the daemon's "nothing happened" baseline.
    result = SyncResult()

    assert result.changed == 0
    assert result.failed == ()
    assert result.blocked == ()
    assert result.frozen == ()
    assert result.diagnosed == ()


def test_sync_result_stores_each_outcome_without_crossing_fields() -> None:
    result = SyncResult(**_POPULATED_RESULT_KWARGS)  # type: ignore[arg-type]

    assert result.changed == 1
    assert result.failed == ("failed-a",)
    assert result.blocked == ("blocked-b",)
    assert result.frozen == ("frozen-c",)
    assert result.diagnosed == ("diagnosed-d",)


def test_equal_sync_results_are_hashable_and_dedupe_in_a_set() -> None:
    one = SyncResult(changed=1, failed=("x",))
    same = SyncResult(changed=1, failed=("x",))

    assert one == same
    assert hash(one) == hash(same)
    assert len({one, same}) == 1


@pytest.mark.parametrize(
    "difference",
    [
        {"changed": 2},
        {"failed": ("other",)},
        {"blocked": ("other",)},
        {"frozen": ("other",)},
        {"diagnosed": ("other",)},
    ],
)
def test_sync_results_differing_in_one_outcome_are_unequal(
    difference: dict[str, object],
) -> None:
    # Each outcome must participate in equality; a field excluded from `__eq__`
    # would let two materially different polls compare equal.
    baseline = SyncResult(**_POPULATED_RESULT_KWARGS)  # type: ignore[arg-type]
    varied = SyncResult(**{**_POPULATED_RESULT_KWARGS, **difference})  # type: ignore[arg-type]

    assert baseline != varied


def test_sync_result_is_immutable() -> None:
    result = SyncResult()

    with pytest.raises(FrozenInstanceError):
        result.changed = 5  # type: ignore[misc]


def test_each_intent_payload_tags_itself_with_its_kind() -> None:
    # The IntentKind enum is each payload's discriminator (for logging / SyncResult
    # categorisation); the executor can read intent.intent_kind without isinstance.
    absorb = AbsorbToolEdit(artifact_id=_INTENT_ARTIFACT_ID, source=_INTENT_SURFACE)
    project = ProjectToTools(artifact_id=_INTENT_ARTIFACT_ID, targets=(_INTENT_SURFACE,))
    freeze = FreezeArtifact(artifact_id=_INTENT_ARTIFACT_ID)

    assert absorb.intent_kind is IntentKind.ABSORB_TOOL_EDIT
    assert project.intent_kind is IntentKind.PROJECT_TO_TOOLS
    assert freeze.intent_kind is IntentKind.FREEZE_ARTIFACT


def test_intent_payloads_carry_their_subject() -> None:
    absorb = AbsorbToolEdit(artifact_id=_INTENT_ARTIFACT_ID, source=_INTENT_SURFACE)
    project = ProjectToTools(artifact_id=_INTENT_ARTIFACT_ID, targets=(_INTENT_SURFACE,))

    assert absorb.artifact_id == _INTENT_ARTIFACT_ID
    assert absorb.source == _INTENT_SURFACE
    assert project.targets == (_INTENT_SURFACE,)


def test_intent_payloads_are_immutable_value_objects() -> None:
    one = FreezeArtifact(artifact_id=_INTENT_ARTIFACT_ID)

    assert one == FreezeArtifact(artifact_id=_INTENT_ARTIFACT_ID)
    assert one != FreezeArtifact(artifact_id="22222222-2222-4222-9222-222222222222")
    with pytest.raises(FrozenInstanceError):
        one.artifact_id = "x"  # type: ignore[misc]


def test_rename_and_remove_intents_are_tagged_immutable_value_objects() -> None:
    rename = RenameArtifact(artifact_id=_INTENT_ARTIFACT_ID, new_name="auditor")
    remove = RemoveArtifact(artifact_id=_INTENT_ARTIFACT_ID)

    assert rename.intent_kind is IntentKind.RENAME_ARTIFACT
    assert rename.new_name == "auditor"
    assert remove.intent_kind is IntentKind.REMOVE_ARTIFACT
    with pytest.raises(FrozenInstanceError):
        remove.artifact_id = "x"  # type: ignore[misc]


def test_canonical_authority_intents_are_tagged_immutable_value_objects() -> None:
    reproject = ReprojectCanonical(artifact_id=_INTENT_ARTIFACT_ID)
    rebuild = RebuildCorruptCanonical(artifact_id=_INTENT_ARTIFACT_ID)

    assert reproject.intent_kind is IntentKind.REPROJECT_CANONICAL
    assert rebuild.intent_kind is IntentKind.REBUILD_CORRUPT_CANONICAL
    with pytest.raises(FrozenInstanceError):
        reproject.artifact_id = "x"  # type: ignore[misc]


def test_sync_plan_holds_its_intents_in_order() -> None:
    # The container the planner returns and the executor walks: an ordered tuple of
    # intents (proposal §6). Order is preserved so the executor sees them as planned.
    freeze = FreezeArtifact(artifact_id=_INTENT_ARTIFACT_ID)
    project = ProjectToTools(artifact_id=_INTENT_ARTIFACT_ID, targets=(_INTENT_SURFACE,))

    plan = SyncPlan(intents=(freeze, project))

    assert plan.intents == (freeze, project)


def test_sync_plan_defaults_to_no_intents() -> None:
    assert SyncPlan().intents == ()


def test_sync_plan_is_immutable() -> None:
    plan = SyncPlan(intents=(FreezeArtifact(artifact_id=_INTENT_ARTIFACT_ID),))

    with pytest.raises(FrozenInstanceError):
        plan.intents = ()  # type: ignore[misc]


def test_absorb_into_managed_is_a_tagged_immutable_value_object() -> None:
    # Carries the winning managed id and the candidate group's surfaces whose bytes are
    # absorbed under it (US-03 AC-6); both fields participate in equality.
    absorb = AbsorbIntoManaged(artifact_id=_INTENT_ARTIFACT_ID, sources=(_INTENT_SURFACE,))

    assert absorb.intent_kind is IntentKind.ABSORB_INTO_MANAGED
    assert absorb == AbsorbIntoManaged(_INTENT_ARTIFACT_ID, (_INTENT_SURFACE,))
    assert absorb != AbsorbIntoManaged("22222222-2222-4222-9222-222222222222", (_INTENT_SURFACE,))
    assert absorb != AbsorbIntoManaged(_INTENT_ARTIFACT_ID, ())
    with pytest.raises(FrozenInstanceError):
        absorb.sources = ()  # type: ignore[misc]


def test_reject_collision_is_a_tagged_immutable_value_object() -> None:
    # Carries the colliding artifact ids and the (kind, slug) reconciliation key they
    # share, so the executor can emit a structured error (US-04 AC-5, US-03 AC-8).
    other_id = "22222222-2222-4222-9222-222222222222"
    collision = RejectCollision(
        artifact_ids=(_INTENT_ARTIFACT_ID, other_id),
        reconciliation_key=("agent", "reviewer"),
    )

    assert collision.intent_kind is IntentKind.REJECT_COLLISION
    assert collision == RejectCollision((_INTENT_ARTIFACT_ID, other_id), ("agent", "reviewer"))
    # Both fields participate in equality — a value object differing in either is unequal.
    assert collision != RejectCollision((_INTENT_ARTIFACT_ID,), ("agent", "reviewer"))
    assert collision != RejectCollision((_INTENT_ARTIFACT_ID, other_id), ("agent", "auditor"))
    with pytest.raises(FrozenInstanceError):
        collision.artifact_ids = ()  # type: ignore[misc]


def test_candidate_intents_are_tagged_immutable_value_objects() -> None:
    # AdoptNewArtifact carries the winning source surface plus the already-present
    # others; ReportUnadoptable carries the unparseable surface (no id yet for either).
    adopt = AdoptNewArtifact(source=_INTENT_SURFACE, others=())
    report = ReportUnadoptable(surface=_INTENT_SURFACE)

    assert adopt.intent_kind is IntentKind.ADOPT_NEW_ARTIFACT
    assert adopt.source == _INTENT_SURFACE
    assert report.intent_kind is IntentKind.REPORT_UNADOPTABLE
    with pytest.raises(FrozenInstanceError):
        report.surface = _INTENT_SURFACE  # type: ignore[misc]
