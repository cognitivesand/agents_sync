param(
  [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$AppName = "agents-sync"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvExe = Join-Path $ProjectDir ".venv\Scripts\agents-sync.exe"
$LauncherDir = Join-Path $env:LOCALAPPDATA "agents-sync\bin"
$LauncherPath = Join-Path $LauncherDir "agents-sync.cmd"
$HiddenLauncherPath = Join-Path $LauncherDir "agents-sync-hidden.vbs"
$LegacyHiddenLauncherPath = Join-Path $LauncherDir "agents-sync-hidden.ps1"
$LogDir = Join-Path $env:LOCALAPPDATA "agents-sync\logs"
$LogPath = Join-Path $LogDir "agents-sync.log"
$ConfigDir = Join-Path $env:APPDATA "agents-sync"
$ConfigPath = Join-Path $ConfigDir "config.toml"
$StateDir = Join-Path $env:LOCALAPPDATA "agents-sync\state"
$StatePath = Join-Path $StateDir "state.json"
$TaskName = "agents-sync"

function Assert-Command([string]$Name, [string]$InstallHint) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    Write-Error "$Name is required but was not found. $InstallHint"
  }
}

function Convert-ToTomlPath([string]$RawPath) {
  return $RawPath.Replace("\", "\\")
}

function Convert-ToVbScriptString([string]$RawValue) {
  return '"' + $RawValue.Replace('"', '""') + '"'
}

function Sync-Venv([string]$ProjectRoot) {
  Push-Location $ProjectRoot
  try {
    uv sync
  } finally {
    Pop-Location
  }
}

function Install-Launcher([string]$LauncherFile, [string]$VenvEntrypoint) {
  New-Item -ItemType Directory -Path (Split-Path -Parent $LauncherFile) -Force | Out-Null
  $content = @"
@echo off
"$VenvEntrypoint" %*
"@
  Set-Content -Path $LauncherFile -Value $content -Encoding Ascii
}

function Install-HiddenLauncher([string]$HiddenLauncherFile, [string]$VenvEntrypoint, [string]$CfgPath, [string]$LogFile) {
  New-Item -ItemType Directory -Path (Split-Path -Parent $HiddenLauncherFile) -Force | Out-Null
  New-Item -ItemType Directory -Path (Split-Path -Parent $LogFile) -Force | Out-Null

  $entrypointLiteral = Convert-ToVbScriptString $VenvEntrypoint
  $configLiteral = Convert-ToVbScriptString $CfgPath
  $logLiteral = Convert-ToVbScriptString $LogFile

  $content = @"
Option Explicit

Dim shell
Dim entrypoint
Dim configPath
Dim logFile
Dim command

Set shell = CreateObject("WScript.Shell")
entrypoint = $entrypointLiteral
configPath = $configLiteral
logFile = $logLiteral

If IsAlreadyRunning(entrypoint, configPath) Then
  WScript.Quit 0
End If

command = "%COMSPEC% /d /c call " & Chr(34) & entrypoint & Chr(34) & " --config " & Chr(34) & configPath & Chr(34) & " >> " & Chr(34) & logFile & Chr(34) & " 2>&1"
WScript.Quit shell.Run(command, 0, True)

Function IsAlreadyRunning(entrypointValue, configPathValue)
  On Error Resume Next

  Dim wmi
  Dim processes
  Dim process
  Dim commandLine

  IsAlreadyRunning = False
  Set wmi = GetObject("winmgmts:\\.\root\cimv2")
  If Err.Number <> 0 Then
    Err.Clear
    Exit Function
  End If

  Set processes = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name = 'agents-sync.exe' OR Name = 'python.exe'")
  If Err.Number <> 0 Then
    Err.Clear
    Exit Function
  End If

  For Each process In processes
    commandLine = ""
    If Not IsNull(process.CommandLine) Then
      commandLine = process.CommandLine
    End If
    If InStr(1, commandLine, entrypointValue, vbTextCompare) > 0 And InStr(1, commandLine, configPathValue, vbTextCompare) > 0 Then
      IsAlreadyRunning = True
      Exit Function
    End If
  Next
End Function
"@
  $unicodeWithBom = New-Object System.Text.UnicodeEncoding($false, $true)
  [System.IO.File]::WriteAllText($HiddenLauncherFile, $content, $unicodeWithBom)
}

function Remove-LegacyHiddenLauncher([string]$LegacyLauncherFile) {
  if (Test-Path $LegacyLauncherFile) {
    Remove-Item -LiteralPath $LegacyLauncherFile -Force
  }
}

function Ensure-Config([string]$ConfigFile, [string]$StateFile) {
  New-Item -ItemType Directory -Path (Split-Path -Parent $ConfigFile) -Force | Out-Null
  New-Item -ItemType Directory -Path (Split-Path -Parent $StateFile) -Force | Out-Null
  if ((-not (Test-Path $ConfigFile)) -or $Force) {
    $tomlStatePath = Convert-ToTomlPath $StateFile
    $cfg = @"
[agents-sync]
poll_interval_seconds = 2.0
state_path = "$tomlStatePath"

claude_agents_dir = "~/.claude/agents"
claude_skills_dir = "~/.claude/skills"

codex_agents_dir = "~/.codex/agents"
codex_skills_dir = "~/.agents/skills"
"@
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($ConfigFile, $cfg, $utf8NoBom)
  }
}

function Register-AgentsSyncTask([string]$Name, [string]$HiddenLauncherFile) {
  $actionArgs = "//B //NoLogo `"$HiddenLauncherFile`""
  $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument $actionArgs
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERNAME"
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
  $settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

  Register-ScheduledTask `
    -TaskName $Name `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Bidirectional sync of Claude Code agents and skills with Codex" `
    -Force | Out-Null

  Start-ScheduledTask -TaskName $Name
}

Assert-Command "python" "Install Python 3.12+ and reopen PowerShell."
Assert-Command "uv" "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
Assert-Command "Register-ScheduledTask" "The ScheduledTasks module is required on Windows 10/11."

Sync-Venv $ProjectDir

if (-not (Test-Path $VenvExe)) {
  Write-Error "Expected entrypoint not found after uv sync: $VenvExe"
}

Install-Launcher -LauncherFile $LauncherPath -VenvEntrypoint $VenvExe
Install-HiddenLauncher -HiddenLauncherFile $HiddenLauncherPath -VenvEntrypoint $VenvExe -CfgPath $ConfigPath -LogFile $LogPath
Remove-LegacyHiddenLauncher -LegacyLauncherFile $LegacyHiddenLauncherPath
Ensure-Config -ConfigFile $ConfigPath -StateFile $StatePath
Register-AgentsSyncTask -Name $TaskName -HiddenLauncherFile $HiddenLauncherPath

Write-Host "Installed $AppName"
Write-Host "Manual launcher: $LauncherPath"
Write-Host "Hidden launcher: $HiddenLauncherPath"
Write-Host "Config:          $ConfigPath"
Write-Host "Log:             $LogPath"
Write-Host "Task:            $TaskName"
