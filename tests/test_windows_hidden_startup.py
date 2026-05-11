from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_script(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8-sig")


def test_windows_installer_registers_hidden_startup_launcher():
    script = read_script("install.ps1")

    assert '$HiddenLauncherPath = Join-Path $LauncherDir "agents-sync-hidden.vbs"' in script
    assert '$LegacyHiddenLauncherPath = Join-Path $LauncherDir "agents-sync-hidden.ps1"' in script
    assert '$LogPath = Join-Path $LogDir "agents-sync.log"' in script
    assert "function Install-HiddenLauncher" in script
    assert 'Set shell = CreateObject("WScript.Shell")' in script
    assert "If IsAlreadyRunning(entrypoint, configPath) Then" in script
    assert "Function IsAlreadyRunning(entrypointValue, configPathValue)" in script
    assert "Win32_Process WHERE Name = 'agents-sync.exe' OR Name = 'python.exe'" in script
    assert 'command = "%COMSPEC% /d /c call "' in script
    assert "2>&1" in script
    assert "WScript.Quit shell.Run(command, 0, True)" in script
    assert 'New-ScheduledTaskAction -Execute "wscript.exe"' in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "//B //NoLogo" in script
    assert '`"$HiddenLauncherFile`"' in script
    assert "Register-AgentsSyncTask -Name $TaskName -HiddenLauncherFile $HiddenLauncherPath" in script
    assert "New-ScheduledTaskAction -Execute $LauncherFile" not in script
    assert "Remove-LegacyHiddenLauncher -LegacyLauncherFile $LegacyHiddenLauncherPath" in script


def test_windows_uninstaller_removes_hidden_startup_launcher():
    script = read_script("uninstall.ps1")

    assert '$HiddenLauncherPath = Join-Path $LauncherDir "agents-sync-hidden.vbs"' in script
    assert '$LegacyHiddenLauncherPath = Join-Path $LauncherDir "agents-sync-hidden.ps1"' in script
    assert "Remove-Launcher -LauncherFile $LauncherPath" in script
    assert "Remove-Launcher -LauncherFile $HiddenLauncherPath" in script
    assert "Remove-Launcher -LauncherFile $LegacyHiddenLauncherPath" in script
