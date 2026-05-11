from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.fs_retry import retry_fs
from agents_sync.state import atomic_write_text


def test_atomic_write_text_uses_lf_newlines(tmp_path: Path):
    out = tmp_path / "data.txt"
    atomic_write_text(out, "a\nb\n")
    assert out.read_bytes() == b"a\nb\n"


def test_retry_fs_retries_permission_error_then_succeeds(monkeypatch: pytest.MonkeyPatch):
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError("locked")
        return "ok"

    monkeypatch.setattr("agents_sync.fs_retry.time.sleep", lambda _: None)

    assert retry_fs(flaky, operation="flaky-op", attempts=4) == "ok"
    assert attempts["count"] == 3


def test_retry_fs_does_not_retry_non_transient_errors(monkeypatch: pytest.MonkeyPatch):
    attempts = {"count": 0}

    def failing() -> None:
        attempts["count"] += 1
        raise FileNotFoundError("missing")

    monkeypatch.setattr("agents_sync.fs_retry.time.sleep", lambda _: None)

    with pytest.raises(FileNotFoundError):
        retry_fs(failing, operation="missing-op", attempts=4)
    assert attempts["count"] == 1
