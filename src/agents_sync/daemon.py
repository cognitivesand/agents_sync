from __future__ import annotations

import logging
import signal
import time

from agents_sync.sync import Syncer


def watch(syncer: Syncer, interval_seconds: float) -> None:
    """Continuous sync loop. SIGINT and SIGTERM cause a clean exit."""
    stop = False

    def request_stop(signum: int, frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    logging.info("Watching Claude agents/skills with SHA256 polling")
    while not stop:
        try:
            changed = syncer.sync_once()
            if changed:
                logging.info("Sync completed: %d changed item(s)", changed)
        except Exception:
            logging.exception("Sync failed")
        time.sleep(interval_seconds)
    logging.info("Stopped")
