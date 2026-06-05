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
    AbsorbToolEdit,
    FreezeArtifact,
    IntentKind,
    ProjectToTools,
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
    # categorisation); the executor can read intent.kind without isinstance.
    absorb = AbsorbToolEdit(artifact_id=_INTENT_ARTIFACT_ID, source=_INTENT_SURFACE)
    project = ProjectToTools(artifact_id=_INTENT_ARTIFACT_ID, targets=(_INTENT_SURFACE,))
    freeze = FreezeArtifact(artifact_id=_INTENT_ARTIFACT_ID)

    assert absorb.kind is IntentKind.ABSORB_TOOL_EDIT
    assert project.kind is IntentKind.PROJECT_TO_TOOLS
    assert freeze.kind is IntentKind.FREEZE_ARTIFACT


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
