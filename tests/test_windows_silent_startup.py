from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_install_script() -> str:
    return (ROOT / "install.ps1").read_text(encoding="utf-8")


def _function_block(source: str, name: str) -> str:
    start = source.index(f"function {name}")
    next_function = source.find("\nfunction ", start + 1)
    if next_function == -1:
        return source[start:]
    return source[start:next_function]


def test_us_07_ac_8_windows_scheduled_task_uses_hidden_wscript_launcher() -> None:
    source = _read_install_script()
    register_task = _function_block(source, "Register-AgentsSyncTask")

    assert 'Join-Path $env:WINDIR "System32\\wscript.exe"' in register_task
    assert "New-ScheduledTaskAction -Execute $wscript" in register_task
    assert '//B //Nologo `"$HiddenLauncherFile`"' in register_task
    assert "$LauncherFile" not in register_task


def test_us_07_ac_8_windows_hidden_launcher_runs_without_visible_window_and_logs_output() -> None:
    source = _read_install_script()
    install_hidden_launcher = _function_block(source, "Install-HiddenLauncher")

    assert "agents-sync-hidden.vbs" in source
    assert "shell.Run(command, 0, True)" in install_hidden_launcher
    assert ">> \" & QuoteCmdArg(logFile) & \" 2>&1" in install_hidden_launcher
    assert "If IsAlreadyRunning(entrypoint, configPath) Then" in install_hidden_launcher
