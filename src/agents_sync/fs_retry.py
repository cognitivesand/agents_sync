from __future__ import annotations

import random
import time
from typing import Callable, TypeVar


T = TypeVar("T")

_WINDOWS_TRANSIENT_WINERRORS = {
    5,   # ERROR_ACCESS_DENIED (often transient during replacement)
    32,  # ERROR_SHARING_VIOLATION
    33,  # ERROR_LOCK_VIOLATION
}


def is_transient_fs_error(exc: BaseException) -> bool:
    if not isinstance(exc, OSError):
        return False
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, "winerror", None)
    if winerror in _WINDOWS_TRANSIENT_WINERRORS:
        return True
    return False


def retry_fs(
    op: Callable[[], T],
    *,
    operation: str,
    attempts: int = 6,
    base_delay_seconds: float = 0.02,
    max_delay_seconds: float = 0.30,
) -> T:
    if attempts < 1:
        raise ValueError(f"attempts must be >= 1 for operation={operation}")

    for attempt in range(1, attempts + 1):
        try:
            return op()
        except Exception as exc:
            if attempt >= attempts or not is_transient_fs_error(exc):
                raise
            delay = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
            jitter = random.uniform(0.7, 1.3)
            time.sleep(delay * jitter)

    # Unreachable; loop either returns or raises.
    raise RuntimeError(f"retry_fs exhausted unexpectedly for operation={operation}")
