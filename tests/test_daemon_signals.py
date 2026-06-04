"""Daemon-loop coverage: signal handling, error budget, cancellable sleep."""
from __future__ import annotations

import threading
import time

import pytest

from agents_sync.daemon import _register_signal_if_available, watch
from agents_sync.sync import SyncResult


class _FakeSyncer:
    """Minimal stand-in for ``Syncer``. ``sync_once`` returns or raises
    according to a script of outcomes provided at construction time."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def sync_once(self) -> SyncResult:
        self.calls += 1
        if not self._outcomes:
            return SyncResult()
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_sync_result_compares_by_value_and_is_hashable():
    first_result = SyncResult(changed=1, failed=["p1"], blocked=["p2"])
    second_result = SyncResult(changed=1, failed=("p1",), blocked=("p2",))
    different_result = SyncResult(changed=1, failed=["p3"], blocked=["p2"])

    assert first_result == second_result
    assert first_result != different_result
    assert hash(first_result) == hash(second_result)
    assert {first_result: "seen"}[second_result] == "seen"
    assert first_result != 1
    with pytest.raises(TypeError):
        int(first_result)
    assert "__bool__" not in SyncResult.__dict__
    assert first_result.failed == ("p1",)
    assert first_result.blocked == ("p2",)


def test_register_signal_if_available_ignores_registration_errors(monkeypatch):
    def boom(signum: int, handler) -> None:
        raise ValueError("unsupported")

    monkeypatch.setattr("agents_sync.daemon.signal.signal", boom)

    _register_signal_if_available(2, lambda *_: None)


def test_watch_exits_zero_when_stop_event_is_set(monkeypatch):
    """Cancellable sleep observes stop within a single short interval."""
    monkeypatch.setattr("agents_sync.daemon._register_signal_if_available", lambda *a, **k: None)
    syncer = _FakeSyncer([SyncResult(changed=0)])
    stop = threading.Event()

    def stopper():
        time.sleep(0.05)
        stop.set()

    threading.Thread(target=stopper, daemon=True).start()
    started = time.monotonic()
    code = watch(syncer, interval_seconds=5.0, stop_event=stop)
    elapsed = time.monotonic() - started

    assert code == 0
    # Without cancellable sleep this would have taken ~5 seconds; with the
    # threading.Event wait, stop should land in well under a second.
    assert elapsed < 1.0


def test_watch_stays_up_despite_persistent_per_artifact_failures(monkeypatch):
    """FR-02 / RC-4: an artifact that fails on every poll must NOT down the
    daemon. Per-artifact failures never advance the exit budget."""
    monkeypatch.setattr("agents_sync.daemon._register_signal_if_available", lambda *a, **k: None)
    stop = threading.Event()
    syncer = _FakeSyncer([SyncResult(changed=0, failed=["p1"]) for _ in range(5)])

    def stopper():
        for _ in range(100):
            if syncer.calls >= 5:
                stop.set()
                return
            time.sleep(0.01)

    threading.Thread(target=stopper, daemon=True).start()
    code = watch(
        syncer,
        interval_seconds=0.0,
        max_consecutive_failures=3,
        stop_event=stop,
    )

    # Ran well past the old 3-failure budget and still exited cleanly on stop.
    assert code == 0
    assert syncer.calls >= 3


def test_persistent_per_artifact_failures_log_once(monkeypatch, caplog):
    """A persistently failing artifact is logged on transition, not every poll
    (NFR-12), so it is visible without re-spamming."""
    import logging

    monkeypatch.setattr("agents_sync.daemon._register_signal_if_available", lambda *a, **k: None)
    stop = threading.Event()
    syncer = _FakeSyncer([SyncResult(changed=0, failed=["p1"]) for _ in range(4)])

    def stopper():
        for _ in range(100):
            if syncer.calls >= 4:
                stop.set()
                return
            time.sleep(0.01)

    threading.Thread(target=stopper, daemon=True).start()
    with caplog.at_level(logging.WARNING):
        watch(syncer, interval_seconds=0.0, max_consecutive_failures=3, stop_event=stop)

    warnings = [r for r in caplog.records if "Per-artifact sync failures" in r.getMessage()]
    assert len(warnings) == 1


def test_watch_resets_exception_counter_after_a_returning_poll(monkeypatch):
    """A poll that returns resets the consecutive whole-poll-exception counter,
    so intermittent systemic errors do not accumulate to an exit."""
    monkeypatch.setattr("agents_sync.daemon._register_signal_if_available", lambda *a, **k: None)
    stop = threading.Event()
    syncer = _FakeSyncer(
        [
            OSError("transient"),
            OSError("transient"),
            SyncResult(changed=1),  # returns — resets the exception counter
            OSError("transient"),
            OSError("transient"),
        ]
    )

    def stopper():
        for _ in range(100):
            if syncer.calls >= 5:
                stop.set()
                return
            time.sleep(0.01)

    threading.Thread(target=stopper, daemon=True).start()
    code = watch(
        syncer,
        interval_seconds=0.0,
        max_consecutive_failures=3,
        stop_event=stop,
    )

    # Never 3 consecutive exceptions, so the budget is never hit.
    assert code == 0


def test_watch_exits_after_consecutive_whole_poll_exceptions(monkeypatch):
    """A systemic failure (sync_once raising) advances the exit budget."""
    monkeypatch.setattr("agents_sync.daemon._register_signal_if_available", lambda *a, **k: None)
    syncer = _FakeSyncer(
        [
            OSError("disk full"),
            OSError("disk full"),
            OSError("disk full"),
        ]
    )

    code = watch(
        syncer,
        interval_seconds=0.0,
        max_consecutive_failures=3,
    )

    assert code == 1
    assert syncer.calls == 3


def test_daemon_gc_tick_prunes_archive(tmp_path, monkeypatch):
    """The daemon's low-frequency GC tick prunes the archive (NFR-07)."""
    import datetime as _dt

    monkeypatch.setattr("agents_sync.daemon._register_signal_if_available", lambda *a, **k: None)
    state_dir = tmp_path / "state"
    side = state_dir / "archive" / "11111111-1111-4111-8111-111111111111" / "claude"
    side.mkdir(parents=True)
    old = _dt.datetime.now(tz=_dt.UTC) - _dt.timedelta(days=500)
    entry = side / f"CLAUDE.md.{old.strftime('%Y-%m-%dT%H-%M-%S-%fZ')}"
    entry.write_text("old", encoding="utf-8")

    class _GcSyncer:
        def __init__(self) -> None:
            self.state_dir = state_dir
            self.calls = 0

        def sync_once(self) -> SyncResult:
            self.calls += 1
            return SyncResult()

    syncer = _GcSyncer()
    stop = threading.Event()

    def stopper():
        for _ in range(100):
            if syncer.calls >= 1:
                stop.set()
                return
            time.sleep(0.01)

    threading.Thread(target=stopper, daemon=True).start()
    # gc_interval_seconds=0.0 -> GC runs every cycle.
    watch(syncer, interval_seconds=0.0, gc_interval_seconds=0.0, stop_event=stop)

    assert not entry.exists()
