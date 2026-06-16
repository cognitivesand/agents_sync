"""S22a — ``poll_daemon.watch``: the poll loop's mechanics.

The loop drives one injected ``sync_once`` per cycle with a systemic-only failure
budget (FR-02), a low-frequency GC tick (NFR-07/08), clean stop-event/SIGINT
shutdown (US-07 AC-2), transient-exception recovery (US-07 AC-3), transition-only
logging (NFR-12), and the distinct exit codes (NFR-10). ``sync_once`` and the GC
action are injected, so the loop is tested without the real read→plan→execute
pipeline (wired at cutover, S24) or a real archive.
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Iterator

import pytest

from agents_sync.domain_model.sync_plan import SyncResult
from agents_sync.poll_daemon import DEFAULT_MAX_CONSECUTIVE_FAILURES, watch
from agents_sync.runtime_config import EXIT_OK, EXIT_RUNTIME_FAILURE


@pytest.fixture(autouse=True)
def _restore_signal_handlers() -> Iterator[None]:
    """``watch`` installs SIGINT/SIGTERM handlers; snapshot and restore them so the
    loop's signal wiring does not leak across tests."""
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    yield
    for sig, handler in saved.items():
        if handler is not None:
            signal.signal(sig, handler)


class _ScriptedPoll:
    """An injected ``sync_once`` that replays a fixed script of outcomes, then
    sets the stop event so the loop terminates. Each outcome is a ``SyncResult``
    to return or an ``Exception`` instance to raise."""

    def __init__(self, outcomes: list[SyncResult | Exception], stop: threading.Event) -> None:
        self._outcomes = outcomes
        self._stop = stop
        self.calls = 0

    def __call__(self) -> SyncResult:
        outcome = self._outcomes[self.calls]
        self.calls += 1
        if self.calls >= len(self._outcomes):
            self._stop.set()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _ClockAdvancingPoll:
    """An injected ``sync_once`` that advances a shared monotonic clock by a fixed
    step each cycle (so the GC tick can be tested deterministically), then stops
    after ``cycles`` calls."""

    def __init__(
        self, clock_box: list[float], step: float, cycles: int, stop: threading.Event
    ) -> None:
        self._clock_box = clock_box
        self._step = step
        self._cycles = cycles
        self._stop = stop
        self.calls = 0

    def __call__(self) -> SyncResult:
        self.calls += 1
        self._clock_box[0] += self._step
        if self.calls >= self._cycles:
            self._stop.set()
        return SyncResult()


def test_stop_set_before_loop_runs_no_poll_and_returns_ok() -> None:
    stop = threading.Event()
    stop.set()
    poll = _ScriptedPoll([SyncResult()], stop)

    code = watch(poll, poll_interval_seconds=0, stop_event=stop)

    assert code == EXIT_OK
    assert poll.calls == 0


def test_clean_stop_returns_exit_ok() -> None:
    stop = threading.Event()
    poll = _ScriptedPoll([SyncResult()], stop)

    code = watch(poll, poll_interval_seconds=0, stop_event=stop)

    assert code == EXIT_OK
    assert poll.calls == 1


def test_per_artifact_failures_never_exhaust_the_budget() -> None:
    # FR-02: a per-artifact failure (result.failed) must not down the daemon,
    # even when it persists well past the systemic-failure budget.
    stop = threading.Event()
    persistent = [
        SyncResult(failed=("artifact-x",)) for _ in range(DEFAULT_MAX_CONSECUTIVE_FAILURES + 2)
    ]
    poll = _ScriptedPoll(persistent, stop)

    code = watch(poll, poll_interval_seconds=0, stop_event=stop)

    assert code == EXIT_OK
    assert poll.calls == DEFAULT_MAX_CONSECUTIVE_FAILURES + 2


def test_consecutive_systemic_exceptions_exhaust_budget_with_runtime_failure() -> None:
    stop = threading.Event()
    poll = _ScriptedPoll([RuntimeError("poll blew up")] * 3, stop)

    code = watch(poll, poll_interval_seconds=0, stop_event=stop, max_consecutive_failures=3)

    assert code == EXIT_RUNTIME_FAILURE
    assert poll.calls == 3


def test_systemic_exception_counter_resets_after_a_returning_poll() -> None:
    # US-07 AC-3: a returning poll clears the consecutive-exception count, so a
    # transient exception that recovers never accumulates toward the budget.
    stop = threading.Event()
    script: list[SyncResult | Exception] = [
        RuntimeError("x"),
        RuntimeError("x"),
        SyncResult(),
        RuntimeError("x"),
        RuntimeError("x"),
    ]
    poll = _ScriptedPoll(script, stop)

    code = watch(poll, poll_interval_seconds=0, stop_event=stop, max_consecutive_failures=3)

    assert code == EXIT_OK
    assert poll.calls == 5


def test_failure_set_is_logged_once_per_transition(caplog: pytest.LogCaptureFixture) -> None:
    # NFR-12: log a per-artifact failure set on the transition, not every poll.
    stop = threading.Event()
    one_failing = SyncResult(failed=("a",))
    two_failing = SyncResult(failed=("a", "b"))
    poll = _ScriptedPoll([one_failing, one_failing, two_failing], stop)

    with caplog.at_level(logging.WARNING):
        watch(poll, poll_interval_seconds=0, stop_event=stop)

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 2
    # NFR-12/13: each transition logs its own failure set — () -> ('a',) then
    # ('a',) -> ('a','b') — verified by id content, not the template wording.
    assert "a" in warnings[0].getMessage()
    assert "a, b" in warnings[1].getMessage()


def test_gc_tick_fires_only_after_the_interval_elapses() -> None:
    # NFR-07/08: GC runs on a low-frequency tick, not every poll.
    stop = threading.Event()
    clock_box = [0.0]
    gc_calls: list[float] = []
    poll = _ClockAdvancingPoll(clock_box, step=4.0, cycles=3, stop=stop)

    watch(
        poll,
        poll_interval_seconds=0,
        stop_event=stop,
        run_gc=lambda: gc_calls.append(clock_box[0]),
        gc_interval_seconds=10.0,
        clock=lambda: clock_box[0],
    )

    # step 4 over a 10s interval: cumulative elapsed first crosses 10 on the 3rd poll.
    assert gc_calls == [12.0]


def test_gc_fault_does_not_stop_the_daemon() -> None:
    # FR-02: a GC error is non-fatal — the daemon keeps polling.
    stop = threading.Event()
    gc_runs = 0

    def failing_gc() -> None:
        nonlocal gc_runs
        gc_runs += 1
        raise OSError("archive volume disappeared")

    poll = _ScriptedPoll([SyncResult(), SyncResult()], stop)

    code = watch(
        poll,
        poll_interval_seconds=0,
        stop_event=stop,
        run_gc=failing_gc,
        gc_interval_seconds=0,
    )

    assert code == EXIT_OK
    assert poll.calls == 2
    assert gc_runs >= 1  # the GC closure was invoked and raised, exercising the swallow path


@pytest.mark.parametrize("delivered_signal", [signal.SIGINT, signal.SIGTERM])
def test_delivered_signal_stops_the_daemon_cleanly(delivered_signal: signal.Signals) -> None:
    # US-07 AC-2: on SIGINT/SIGTERM the loop stops cleanly with EXIT_OK. This
    # exercises the real production chain (stop_event=None -> loop owns its event ->
    # _install_stop_signals installs real handlers -> an OS-delivered signal sets
    # the event), with no internal mocking. raise_signal delivers synchronously on
    # the calling thread, so the handler runs before sync_once returns.
    # fail loud: installing real handlers requires the main thread.
    assert threading.current_thread() is threading.main_thread()

    calls = 0

    def sync_once_then_signal() -> SyncResult:
        nonlocal calls
        calls += 1
        signal.raise_signal(delivered_signal)
        return SyncResult()

    code = watch(sync_once_then_signal, poll_interval_seconds=0, stop_event=None)

    assert code == EXIT_OK
    assert calls == 1
