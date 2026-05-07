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

function Register-AgentsSyncTask([string]$Name, [string]$LauncherFile, [string]$CfgPath) {
  $action = New-ScheduledTaskAction -Execute $LauncherFile -Argument "--config `"$CfgPath`""
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERNAME"
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
  $settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
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
Ensure-Config -ConfigFile $ConfigPath -StateFile $StatePath
Register-AgentsSyncTask -Name $TaskName -LauncherFile $LauncherPath -CfgPath $ConfigPath

Write-Host "Installed $AppName"
Write-Host "Launcher: $LauncherPath"
Write-Host "Config:   $ConfigPath"
Write-Host "Task:     $TaskName"
