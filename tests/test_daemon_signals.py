from __future__ import annotations

from agents_sync.daemon import _register_signal_if_available


def test_register_signal_if_available_ignores_registration_errors(monkeypatch):
    def boom(signum: int, handler) -> None:
        raise ValueError("unsupported")

    monkeypatch.setattr("agents_sync.daemon.signal.signal", boom)

    _register_signal_if_available(2, lambda *_: None)
