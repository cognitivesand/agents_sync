"""Simulated case-only-collision tests.

This file used to be named ``test_windows_slug_collision.py``, which
overpromised: the case-insensitive lookups monkeypatch
``os.path.normcase`` rather than relying on real NTFS case-folding. They
pin the *logic* of the case-only collision detector but they do **not**
exercise the inode-shared-between-two-names behaviour real NTFS / APFS
exhibits (audit slice 10 · CQ-12).
"""
from __future__ import annotations

import pytest

from agents_sync.state import (
    AgenticToolState,
    CustomizationArtifactState,
    slugify,
    target_slug,
)
from agents_sync.sync import CustomizationArtifactInfo, Syncer


def test_slugify_avoids_reserved_windows_basenames():
    assert slugify("CON") == "con-item"
    assert slugify("nul") == "nul-item"
    assert slugify("LPT1") == "lpt1-item"


def test_target_slug_returns_bare_slugified_name():
    """v0.4: target_slug drops the -skill / -agent suffix introduced in v0.3.
    Counterparts use the bare slug because agents and skills live in
    distinct config-keyed roots, so kind disambiguation is unnecessary."""
    assert target_slug("CI.yaml") == "ci-yaml"
    assert target_slug("formatter") == "formatter"
    assert target_slug("review-agent") == "review-agent"


def test_state_owner_lookup_can_be_case_insensitive(
    syncer: Syncer, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("agents_sync.rendering.os.path.normcase", lambda value: value.lower())
    codex_path = syncer.tool_root("codex", "skill") / "Alpha"
    state = {
        "pair-1": CustomizationArtifactState(
            kind="skill",
            agentic_tools={
                "claude": AgenticToolState(
                    path=syncer.tool_root("claude", "skill") / "alpha",
                ),
                "codex": AgenticToolState(path=codex_path),
            },
        )
    }

    owner = syncer.discovery.state_owner_for_path(
        syncer.tool_root("codex", "skill") / "alpha", state
    )
    assert owner == "pair-1"


def test_case_only_target_collisions_are_blocked(syncer: Syncer, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("agents_sync.rendering.os.path.normcase", lambda value: value.lower())
    discovery = {
        "pair-a": CustomizationArtifactInfo(kind="skill"),
        "pair-b": CustomizationArtifactInfo(kind="skill"),
    }
    from agents_sync.sync_types import PlannedTarget
    targets = iter([
        PlannedTarget(syncer.tool_root("codex", "skill") / "Alpha"),
        PlannedTarget(syncer.tool_root("codex", "skill") / "alpha"),
    ])
    monkeypatch.setattr(
        syncer.discovery, "_planned_adoption_targets", lambda info: [next(targets)]
    )

    blocked = syncer.discovery.block_target_collisions(discovery, state={})

    assert discovery == {}
    assert blocked == {"pair-a", "pair-b"}
