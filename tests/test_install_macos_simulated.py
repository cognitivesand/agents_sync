"""Simulated execution checks for ``install-macos.sh``.

The test runs the installer end-to-end with a fake HOME and fake macOS
commands. It does not install a real LaunchAgent, but it verifies the files
the installer would write and the launchctl calls it would make.
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def test_macos_installer_writes_runtime_files_under_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    home.mkdir()

    uv_log = tmp_path / "uv.log"
    python_log = tmp_path / "python.log"
    launchctl_log = tmp_path / "launchctl.log"

    _write_executable(
        fake_bin / "uname",
        r"""
        #!/usr/bin/env bash
        if [[ "${1:-}" == "-s" ]]; then
          echo "Darwin"
          exit 0
        fi
        exec /usr/bin/uname "$@"
        """,
    )
    _write_executable(
        fake_bin / "id",
        r"""
        #!/usr/bin/env bash
        if [[ "${1:-}" == "-u" ]]; then
          echo "501"
          exit 0
        fi
        exec /usr/bin/id "$@"
        """,
    )
    _write_executable(
        fake_bin / "launchctl",
        r"""
        #!/usr/bin/env bash
        printf '%s\n' "$*" >> "${FAKE_LAUNCHCTL_LOG:?}"
        """,
    )
    _write_executable(
        fake_bin / "uv",
        r"""
        #!/usr/bin/env bash
        set -euo pipefail
        printf '%s\n' "$*" >> "${FAKE_UV_LOG:?}"

        if [[ "${1:-}" == "venv" ]]; then
          venv="${@: -1}"
          mkdir -p "${venv}/bin"
          cat > "${venv}/bin/python" <<'PY'
        #!/usr/bin/env bash
        printf '%s\n' "$*" >> "${FAKE_PYTHON_LOG:?}"
        exit 0
        PY
          chmod +x "${venv}/bin/python"
          exit 0
        fi

        if [[ "${1:-}" == "pip" && "${2:-}" == "install" ]]; then
          shift 2
          python_path=""
          while [[ "$#" -gt 0 ]]; do
            case "$1" in
              --python)
                python_path="$2"
                shift 2
                ;;
              --reinstall)
                shift
                ;;
              *)
                shift
                ;;
            esac
          done
          venv_bin="$(dirname "${python_path}")"
          mkdir -p "${venv_bin}"
          cat > "${venv_bin}/agents-sync" <<'SH'
        #!/usr/bin/env bash
        printf 'agents-sync fake entrypoint\n'
        SH
          chmod +x "${venv_bin}/agents-sync"
          exit 0
        fi

        exit 2
        """,
    )

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_UV_LOG": str(uv_log),
        "FAKE_PYTHON_LOG": str(python_log),
        "FAKE_LAUNCHCTL_LOG": str(launchctl_log),
    }

    result = subprocess.run(
        ["bash", str(ROOT / "install-macos.sh")],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Installed agents-sync" in result.stdout

    venv_dir = home / ".local/share/agents-sync/venv"
    launcher = home / ".local/bin/agents-sync"
    config = home / ".config/agents-sync/config.toml"
    plist_path = home / "Library/LaunchAgents/com.agents-sync.daemon.plist"

    assert (venv_dir / "bin/agents-sync").is_file()
    assert launcher.is_file()
    assert config.is_file()
    assert plist_path.is_file()

    launcher_text = launcher.read_text(encoding="utf-8")
    assert str(venv_dir / "bin/agents-sync") in launcher_text
    assert str(ROOT) not in launcher_text

    plist_text = plist_path.read_text(encoding="utf-8")
    assert str(ROOT) not in plist_text

    plist = plistlib.loads(plist_path.read_bytes())
    assert plist["WorkingDirectory"] == str(home)
    assert plist["ProgramArguments"] == [
        str(launcher),
        "--config",
        str(config),
    ]
    assert plist["StandardOutPath"] == str(home / "Library/Logs/agents-sync/agents-sync.log")
    assert plist["StandardErrorPath"] == str(
        home / "Library/Logs/agents-sync/agents-sync.err.log"
    )

    assert uv_log.read_text(encoding="utf-8").splitlines() == [
        f"venv --python 3.12 {venv_dir}",
        f"pip install --python {venv_dir}/bin/python --reinstall {ROOT}",
    ]
    assert python_log.read_text(encoding="utf-8").splitlines() == [
        f"{ROOT}/scripts/migrate_v0.4.py --yes",
    ]
    assert launchctl_log.read_text(encoding="utf-8").splitlines() == [
        f"bootout gui/501 {plist_path}",
        f"bootstrap gui/501 {plist_path}",
        "enable gui/501/com.agents-sync.daemon",
        "kickstart -k gui/501/com.agents-sync.daemon",
    ]
