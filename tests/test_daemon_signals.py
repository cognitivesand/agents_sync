"""Daemon-loop coverage: signal handling, error budget, cancellable sleep."""
from __future__ import annotations

import threading
import time

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


def test_watch_exits_nonzero_after_consecutive_failures(monkeypatch):
    """An error budget exit lets a supervisor restart or alert."""
    monkeypatch.setattr("agents_sync.daemon._register_signal_if_available", lambda *a, **k: None)
    syncer = _FakeSyncer(
        [
            SyncResult(changed=0, failed=["p1"]),
            SyncResult(changed=0, failed=["p2"]),
            SyncResult(changed=0, failed=["p3"]),
        ]
    )

    code = watch(
        syncer,
        interval_seconds=0.0,
        max_consecutive_failures=3,
    )

    assert code == 1
    assert syncer.calls == 3


def test_watch_resets_failure_counter_after_clean_poll(monkeypatch):
    """A single clean poll resets the consecutive-failure counter."""
    monkeypatch.setattr("agents_sync.daemon._register_signal_if_available", lambda *a, **k: None)
    stop = threading.Event()
    syncer = _FakeSyncer(
        [
            SyncResult(changed=0, failed=["p1"]),
            SyncResult(changed=0, failed=["p2"]),
            SyncResult(changed=1),  # clean — resets counter
            SyncResult(changed=0, failed=["p3"]),
        ]
    )

    def stopper():
        # Let four polls run, then stop.
        for _ in range(10):
            if syncer.calls >= 4:
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

    # The clean poll at call #3 resets the counter, so we never hit the
    # error budget — exit on the stop event with code 0.
    assert code == 0


def test_watch_treats_whole_poll_exception_like_a_failure(monkeypatch):
    """An exception from ``sync_once`` advances the failure counter."""
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
