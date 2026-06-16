"""The poll daemon: drive one injected ``sync_once`` per cycle on a fixed
interval, with a systemic-only failure budget (FR-02), a low-frequency archive GC
tick (NFR-07/08), clean SIGINT/SIGTERM shutdown (US-07 AC-2), transient-exception
recovery (US-07 AC-3), and transition-only logging (NFR-12/13). Returns a distinct
process exit code (NFR-10).

``sync_once`` and ``run_gc`` are injected callables: the read→plan→execute
pipeline is wired into ``sync_once`` at cutover (S24), and ``run_gc`` is the
archive GC closure the CLI supplies. The loop owns only timing, the failure
budget, the GC cadence, signal handling, and logging — not what a poll does.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable

from agents_sync.domain_model.sync_plan import SyncResult
from agents_sync.runtime_config import EXIT_OK, EXIT_RUNTIME_FAILURE

_LOGGER = logging.getLogger(__name__)

# A *systemic* failure is a whole-poll exception; this many consecutive ones in a
# row downs the daemon (FR-02). Per-artifact failures never advance the count.
DEFAULT_MAX_CONSECUTIVE_FAILURES = 5
# The archive GC runs on a low-frequency tick, not every poll (NFR-07/08).
DEFAULT_GC_INTERVAL_SECONDS = 24 * 60 * 60


def _install_stop_signals(stop: threading.Event) -> None:
    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, request_stop)
        except (OSError, ValueError):
            # Not the main thread, or the platform lacks this signal — the
            # stop_event remains the shutdown path.
            _LOGGER.debug("signal %s not installable; relying on stop_event", sig)


def _log_failure_transition(failed: tuple[str, ...], previous: tuple[str, ...]) -> tuple[str, ...]:
    if failed and failed != previous:
        _LOGGER.warning("per-artifact sync failures this poll: %s", ", ".join(failed))
    return failed


def _run_gc_safely(run_gc: Callable[[], None]) -> None:
    try:
        run_gc()
    except Exception:
        # FR-02: a GC fault never downs the daemon.
        _LOGGER.exception("archive GC tick failed (non-fatal)")


def watch(
    sync_once: Callable[[], SyncResult],
    *,
    poll_interval_seconds: float,
    stop_event: threading.Event | None = None,
    run_gc: Callable[[], None] | None = None,
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
    gc_interval_seconds: float = DEFAULT_GC_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Run the continuous sync loop, returning a process exit code: ``EXIT_OK`` on
    a clean stop (SIGINT/SIGTERM or ``stop_event``), ``EXIT_RUNTIME_FAILURE`` when
    ``max_consecutive_failures`` whole-poll exceptions occur in a row.

    ``stop_event`` is exposed for testing; production passes ``None`` and the loop
    owns its own event."""
    stop = stop_event if stop_event is not None else threading.Event()
    _install_stop_signals(stop)

    consecutive_exceptions = 0
    previous_failed: tuple[str, ...] = ()
    last_gc = clock()

    while not stop.is_set():
        try:
            result = sync_once()
        except Exception:
            consecutive_exceptions += 1
            _LOGGER.exception(
                "sync poll raised (systemic failure %d/%d)",
                consecutive_exceptions,
                max_consecutive_failures,
            )
            if consecutive_exceptions >= max_consecutive_failures:
                return EXIT_RUNTIME_FAILURE
        else:
            consecutive_exceptions = 0
            previous_failed = _log_failure_transition(result.failed, previous_failed)

        if run_gc is not None and clock() - last_gc >= gc_interval_seconds:
            last_gc += gc_interval_seconds
            _run_gc_safely(run_gc)

        if stop.wait(poll_interval_seconds):
            break

    return EXIT_OK
