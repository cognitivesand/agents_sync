"""Static-text checks on ``install-macos.sh``.

These assertions do not execute launchd. They keep the macOS installer from
reintroducing a runtime dependency on the source checkout path.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read_install_script() -> str:
    return (ROOT / "install-macos.sh").read_text(encoding="utf-8")


def test_macos_installer_launcher_uses_private_user_venv_not_source_venv() -> None:
    source = _read_install_script()

    assert 'INSTALL_DIR="${HOME}/.local/share/${APP_NAME}"' in source
    assert 'VENV_DIR="${INSTALL_DIR}/venv"' in source
    assert 'uv pip install --python "${VENV_DIR}/bin/python" --reinstall "${PROJECT_DIR}"' in source
    assert 'VENV_DIR="${PROJECT_DIR}/.venv"' not in source
    assert 'exec "${PROJECT_DIR}/.venv/bin/${APP_NAME}"' not in source
    assert "uv sync" not in source


def test_macos_launchagent_uses_home_working_directory_not_source_checkout() -> None:
    source = _read_install_script()

    assert "<key>WorkingDirectory</key>" in source
    assert '<string>$(xml_escape "${HOME}")</string>' in source
    assert '<string>$(xml_escape "${PROJECT_DIR}")</string>' not in source
