param(
  [switch]$CleanupData
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TaskName = "agents-sync"
$LauncherPath = Join-Path $env:LOCALAPPDATA "agents-sync\bin\agents-sync.cmd"
$HiddenLauncherPath = Join-Path $env:LOCALAPPDATA "agents-sync\bin\agents-sync-hidden.vbs"
$ConfigDir = Join-Path $env:APPDATA "agents-sync"
$StateDir = Join-Path $env:LOCALAPPDATA "agents-sync"

function Unregister-AgentsSyncTask([string]$Name) {
  $existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
  if ($null -ne $existing) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false
  }
}

function Remove-Launcher([string]$LauncherFile) {
  if (Test-Path $LauncherFile) {
    Remove-Item -LiteralPath $LauncherFile -Force
  }
  $launcherDir = Split-Path -Parent $LauncherFile
  if (Test-Path $launcherDir) {
    $children = Get-ChildItem -Path $launcherDir -Force
    if ($children.Count -eq 0) {
      Remove-Item -LiteralPath $launcherDir -Force
    }
  }
}

function Remove-DataIfRequested([switch]$DoCleanup, [string]$ConfigRoot, [string]$StateRoot) {
  if (-not $DoCleanup) {
    return
  }
  if (Test-Path $ConfigRoot) {
    Remove-Item -LiteralPath $ConfigRoot -Recurse -Force
  }
  if (Test-Path $StateRoot) {
    Remove-Item -LiteralPath $StateRoot -Recurse -Force
  }
}

Unregister-AgentsSyncTask -Name $TaskName
Remove-Launcher -LauncherFile $LauncherPath
Remove-Launcher -LauncherFile $HiddenLauncherPath
Remove-DataIfRequested -DoCleanup:$CleanupData -ConfigRoot $ConfigDir -StateRoot $StateDir

Write-Host "Uninstalled agents-sync task and launcher."
if ($CleanupData) {
  Write-Host "Config/state directories were also removed."
} else {
  Write-Host "Config/state directories were left in place."
}
