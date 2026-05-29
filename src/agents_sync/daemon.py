"""Continuous-poll daemon loop with an error budget and cancellable sleep.

The loop wakes up every ``interval_seconds`` and calls ``Syncer.sync_once``.
Three kinds of outcome are distinguished:

- **Clean poll** — ``SyncResult.failed`` is empty. The consecutive-failure
  counter is reset and the loop sleeps until the next interval (or until a
  signal arrives, whichever is first).
- **Per-pair failure** — ``sync_once`` returned but ``SyncResult.failed``
  is non-empty. Logged. The consecutive-failure counter advances; if it
  hits ``max_consecutive_failures`` the loop exits with a clear marker so a
  supervisor (systemd, launchd, ``schtasks``) can restart or alert.
- **Whole-poll exception** — ``sync_once`` itself raised. Logged at
  exception level. The consecutive-failure counter advances on the same
  policy as a per-pair failure.

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
"""Exit after this many consecutive polls with at least one failed pair."""


def _register_signal_if_available(signum: int, handler: Callable) -> None:
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

    consecutive_failures = 0
    exit_code = 0
    while not stop.is_set():
        try:
            result = syncer.sync_once()
        except Exception:
            logging.exception("Sync failed (whole-poll exception)")
            consecutive_failures += 1
        else:
            if result.failed:
                logging.error(
                    "Sync poll had failures: failed=%d blocked=%d changed=%d",
                    len(result.failed), len(result.blocked), result.changed,
                )
                consecutive_failures += 1
            else:
                if result.changed:
                    logging.info(
                        "Sync completed: %d changed item(s)", result.changed,
                    )
                consecutive_failures = 0

        if consecutive_failures >= max_consecutive_failures:
            logging.error(
                "Exiting after %d consecutive failed polls; "
                "supervisor should restart and/or alert.",
                consecutive_failures,
            )
            exit_code = 1
            break

        # Cancellable sleep: returns True if stop was signalled, False on timeout.
        if stop.wait(interval_seconds):
            break

    logging.info("Stopped")
    return exit_code
