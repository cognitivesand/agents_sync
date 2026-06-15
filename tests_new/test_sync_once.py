"""S22b — ``sync_once``: the read→plan→execute orchestration for one poll.

These exercise the real pipeline end to end through ``tmp_path`` tool roots: a
candidate agent surface is adopted (canonical minted, id injected, state
persisted) when two tools are available, and the two-tool destructive guard
(US-07 AC-5) is honoured when ``available_tool_count`` is below two. ``sync_once``
takes ``available_tool_count`` as an argument; ``count_available_tools`` computes
it (a tool is available when ≥1 of its resolved roots exists — the new-model
definition the S24 conformance cutover validates). ``make_periodic_poll`` threads
the state and digest cache across polls.
"""

from __future__ import annotations

from pathlib import Path

from agents_sync.canonical_store import list_canonical_ids
from agents_sync.domain_model.sync_state import SyncState
from agents_sync.runtime_config import RuntimeConfig
from agents_sync.sync_once import count_available_tools, make_periodic_poll, sync_once
from agents_sync.sync_state_store import load_sync_state


def _candidate_agent(name: str = "helper") -> str:
    """An id-less agent surface (no ``pair_id``) — a candidate for adoption."""
    return f"---\nname: {name}\n---\nHelp tersely.\n"


def _tool_workspace(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, Path]]:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    claude_dir = tmp_path / "claude" / "agents"
    cursor_dir = tmp_path / "cursor" / "agents"
    claude_dir.mkdir(parents=True)
    cursor_dir.mkdir(parents=True)
    resolved_paths = {"claude_agents_dir": claude_dir, "cursor_agents_dir": cursor_dir}
    return state_dir, claude_dir, cursor_dir, resolved_paths


def test_sync_once_adopts_a_candidate_and_persists_state(tmp_path: Path) -> None:
    state_dir, claude_dir, _cursor_dir, resolved_paths = _tool_workspace(tmp_path)
    (claude_dir / "helper.md").write_text(_candidate_agent())

    result, _observations, state = sync_once(
        state_dir, resolved_paths, SyncState(), {}, available_tool_count=2
    )

    [minted_id] = list_canonical_ids(state_dir)
    assert minted_id in (claude_dir / "helper.md").read_text()  # id injected into the surface
    assert minted_id in state.records  # returned state carries the new record
    assert minted_id in load_sync_state(state_dir).records  # and it was persisted to disk
    assert result.changed >= 1


def test_sync_once_two_tool_guard_suppresses_adoption_below_two(tmp_path: Path) -> None:
    state_dir, claude_dir, _cursor_dir, resolved_paths = _tool_workspace(tmp_path)
    (claude_dir / "helper.md").write_text(_candidate_agent())

    result, _observations, state = sync_once(
        state_dir, resolved_paths, SyncState(), {}, available_tool_count=1
    )

    assert list_canonical_ids(state_dir) == []  # destructive adoption dropped
    assert state.records == {}
    assert result.changed == 0


def test_count_available_tools_counts_tools_with_an_existing_root(tmp_path: Path) -> None:
    claude_dir = tmp_path / "claude" / "agents"
    cursor_dir = tmp_path / "cursor" / "agents"
    claude_dir.mkdir(parents=True)  # cursor_dir intentionally absent
    resolved_paths = {"claude_agents_dir": claude_dir, "cursor_agents_dir": cursor_dir}

    assert count_available_tools(resolved_paths) == 1

    cursor_dir.mkdir(parents=True)
    assert count_available_tools(resolved_paths) == 2


def test_make_periodic_poll_threads_state_across_polls(tmp_path: Path) -> None:
    state_dir, claude_dir, _cursor_dir, resolved_paths = _tool_workspace(tmp_path)
    (claude_dir / "helper.md").write_text(_candidate_agent())
    config = RuntimeConfig(
        poll_interval_seconds=2.0,
        state_path=state_dir / "state.json",
        secret_policy="secrets_refused",
        resolved_paths=resolved_paths,
    )
    poll = make_periodic_poll(config)

    first = poll()
    poll()

    # One artifact adopted on the first poll; re-polling threads the state so it is
    # never re-adopted — exactly one canonical, not one per poll.
    assert first.changed >= 1
    assert len(list_canonical_ids(state_dir)) == 1
