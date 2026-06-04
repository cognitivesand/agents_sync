"""Continuous-poll daemon loop with an error budget and cancellable sleep.

The loop wakes up every ``interval_seconds`` and calls ``Syncer.sync_once``.
The exit budget counts only *systemic* failures, never per-artifact ones (FR-02
fault isolation; bug 602c6d RC-4, amendment 012):

- **Clean poll** — ``sync_once`` returned. The systemic-exception counter is
  reset and the loop sleeps until the next interval (or until a signal arrives).
- **Per-artifact failure** — ``sync_once`` returned but ``SyncResult.failed``
  is non-empty. The faults are isolated and retried next poll; they are logged
  on *transition* (NFR-12) and do **not** advance the exit budget, so one stuck
  artifact can never down the daemon.
- **Whole-poll exception** — ``sync_once`` itself raised (a systemic fault).
  Logged at exception level; advances the exit budget. On
  ``max_consecutive_failures`` consecutive such polls the loop exits with a
  clear marker so a supervisor (systemd, launchd, ``schtasks``) can restart or
  alert.

Cancellation: ``request_stop`` flips a ``threading.Event``; both the
sleep and the loop predicate observe it, so SIGTERM/SIGINT is honoured
within a small fraction of a second regardless of the configured poll
interval. (Previously the loop slept for the full interval before
noticing the stop, which delayed shutdown by up to 30 s.)
"""
from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable

from agents_sync.sync import Syncer

DEFAULT_MAX_CONSECUTIVE_FAILURES = 5
"""Exit after this many consecutive *whole-poll exceptions* (systemic failures).
Per-artifact failures (``SyncResult.failed``) are isolated and never counted."""


def _register_signal_if_available(
    signum: int, handler: Callable[[int, object], None]
) -> None:
    try:
        signal.signal(signum, handler)
    except (AttributeError, OSError, ValueError):
        logging.debug("Skipping unsupported signal registration: %s", signum)


def watch(
    syncer: Syncer,
    interval_seconds: float,
    *,
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
    stop_event: threading.Event | None = None,
) -> int:
    """Run the continuous sync loop. Returns an exit code suitable for
    use as the process exit code:

    - ``0`` — clean exit on SIGINT/SIGTERM, or on the ``stop_event``.
    - ``1`` — exited because ``max_consecutive_failures`` was reached.

    ``stop_event`` is exposed for testing; in production it is ``None`` and
    the loop's own ``threading.Event`` is used.
    """
    stop = stop_event if stop_event is not None else threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop.set()

    _register_signal_if_available(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        _register_signal_if_available(signal.SIGTERM, request_stop)
    logging.info("Watching configured agent and skill roots with SHA256 polling")

    consecutive_exceptions = 0
    prev_failed: frozenset[str] = frozenset()
    exit_code = 0
    while not stop.is_set():
        try:
            result = syncer.sync_once()
        except Exception:
            # Systemic failure: the poll mechanism itself broke (unreadable state
            # dir, runtime config fault, ...). Only this advances the exit budget.
            logging.exception("Sync failed (whole-poll exception)")
            consecutive_exceptions += 1
        else:
            # A poll that returned is a healthy loop, even if some artifacts
            # failed: those faults are isolated (FR-02), retried next poll, and
            # never down the daemon (RC-4, amendment 012).
            consecutive_exceptions = 0
            current_failed = frozenset(result.failed)
            if current_failed and current_failed != prev_failed:
                # Log per-artifact failures on transition only (NFR-12), so a
                # persistently stuck artifact is visible without per-poll spam.
                logging.warning(
                    "Per-artifact sync failures (isolated, retried next poll): "
                    "failed=%d blocked=%d changed=%d pair_ids=%s",
                    len(result.failed), len(result.blocked), result.changed,
                    ", ".join(result.failed),
                )
            prev_failed = current_failed
            if not current_failed and result.changed:
                logging.info("Sync completed: %d changed item(s)", result.changed)

        if consecutive_exceptions >= max_consecutive_failures:
            logging.error(
                "Exiting after %d consecutive whole-poll exceptions; "
                "supervisor should restart and/or alert.",
                consecutive_exceptions,
            )
            exit_code = 1
            break

        # Cancellable sleep: returns True if stop was signalled, False on timeout.
        if stop.wait(interval_seconds):
            break

    logging.info("Stopped")
    return exit_code
