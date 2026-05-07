from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.state import PairState, slugify
from agents_sync.sync import PairInfo, Syncer


def test_slugify_avoids_reserved_windows_basenames():
    assert slugify("CON") == "con-item"
    assert slugify("nul") == "nul-item"
    assert slugify("LPT1") == "lpt1-item"


def test_state_owner_lookup_can_be_case_insensitive(syncer: Syncer, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("agents_sync.sync.os.path.normcase", lambda value: value.lower())
    codex_path = Path(syncer.codex_agents_dir) / "Alpha.toml"
    state = {
        "pair-1": PairState(
            kind="agent",
            claude_path=str(Path(syncer.claude_agents_dir) / "alpha.md"),
            codex_path=str(codex_path),
        )
    }

    owner = syncer._state_owner_for_path(Path(syncer.codex_agents_dir) / "alpha.toml", state)
    assert owner == "pair-1"


def test_case_only_target_collisions_are_blocked(syncer: Syncer, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("agents_sync.sync.os.path.normcase", lambda value: value.lower())
    discovery = {
        "pair-a": PairInfo(kind="agent"),
        "pair-b": PairInfo(kind="agent"),
    }
    targets = iter([
        Path(syncer.codex_agents_dir) / "Alpha.toml",
        Path(syncer.codex_agents_dir) / "alpha.toml",
    ])
    monkeypatch.setattr(syncer, "_planned_adoption_target", lambda info: next(targets))

    syncer._block_target_collisions(discovery, state={})

    assert discovery == {}
