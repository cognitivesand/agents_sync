from __future__ import annotations

import logging
import signal
import time

from agents_sync.sync import Syncer


def _register_signal_if_available(signum: int, handler) -> None:
    try:
        signal.signal(signum, handler)
    except (AttributeError, OSError, ValueError):
        logging.debug("Skipping unsupported signal registration: %s", signum)


def watch(syncer: Syncer, interval_seconds: float) -> None:
    """Continuous sync loop. SIGINT and SIGTERM cause a clean exit."""
    stop = False

    def request_stop(signum: int, frame: object) -> None:
        nonlocal stop
        stop = True

    _register_signal_if_available(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        _register_signal_if_available(signal.SIGTERM, request_stop)
    logging.info("Watching configured agent and skill roots with SHA256 polling")
    while not stop:
        try:
            changed = syncer.sync_once()
            if changed:
                logging.info("Sync completed: %d changed item(s)", changed)
        except Exception:
            logging.exception("Sync failed")
        time.sleep(interval_seconds)
    logging.info("Stopped")
