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
$ConfigDir = Join-Path $env:APPDATA "agents-sync"
$ConfigPath = Join-Path $ConfigDir "config.toml"
$StateDir = Join-Path $env:LOCALAPPDATA "agents-sync\state"
$StatePath = Join-Path $StateDir "state.json"
$LogDir = Join-Path $env:LOCALAPPDATA "agents-sync\logs"
$LogPath = Join-Path $LogDir "agents-sync.log"
$TaskName = "agents-sync"

function Assert-Command([string]$Name, [string]$InstallHint) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    Write-Error "$Name is required but was not found. $InstallHint"
  }
}

function Convert-ToTomlPath([string]$RawPath) {
  return $RawPath.Replace("\", "\\")
}

function Convert-ToVbsLiteral([string]$RawValue) {
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

function Install-HiddenLauncher([string]$LauncherFile, [string]$VenvEntrypoint, [string]$CfgPath, [string]$LogFile) {
  New-Item -ItemType Directory -Path (Split-Path -Parent $LauncherFile) -Force | Out-Null
  New-Item -ItemType Directory -Path (Split-Path -Parent $LogFile) -Force | Out-Null

  $entrypointLiteral = Convert-ToVbsLiteral $VenvEntrypoint
  $configLiteral = Convert-ToVbsLiteral $CfgPath
  $logLiteral = Convert-ToVbsLiteral $LogFile
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

command = QuoteCmdArg(shell.ExpandEnvironmentStrings("%COMSPEC%")) & " /d /c call " & QuoteCmdArg(entrypoint) & " --config " & QuoteCmdArg(configPath) & " >> " & QuoteCmdArg(logFile) & " 2>&1"
WScript.Quit shell.Run(command, 0, True)

Function QuoteCmdArg(value)
  QuoteCmdArg = Chr(34) & Replace(value, Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function

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
  Set-Content -Path $LauncherFile -Value $content -Encoding Ascii
}

function Ensure-Config([string]$ConfigFile, [string]$StateFile) {
  New-Item -ItemType Directory -Path (Split-Path -Parent $ConfigFile) -Force | Out-Null
  New-Item -ItemType Directory -Path (Split-Path -Parent $StateFile) -Force | Out-Null
  if ((-not (Test-Path $ConfigFile)) -or $Force) {
    $tomlStatePath = Convert-ToTomlPath $StateFile
    $opencodeAgentsPath = Convert-ToTomlPath (Join-Path $env:APPDATA "opencode\agents")
    $opencodeCommandsPath = Convert-ToTomlPath (Join-Path $env:APPDATA "opencode\commands")
    $opencodeSkillsPath = Convert-ToTomlPath (Join-Path $env:APPDATA "opencode\skills")
    $opencodeRulesPath = Convert-ToTomlPath (Join-Path $env:APPDATA "opencode")
    $cfg = @"
[agents-sync]
poll_interval_seconds = 2.0
state_path = "$tomlStatePath"

claude_agents_dir = "~/.claude/agents"
claude_commands_dir = "~/.claude/commands"
claude_skills_dir = "~/.claude/skills"
claude_rules_dir = "~/.claude"

codex_agents_dir = "~/.codex/agents"
codex_prompts_dir = "~/.codex/prompts"
codex_skills_dir = "~/.codex/skills"
codex_rules_dir = "~/.codex"

# Google Antigravity (skills only). Enabled by default once
# ~/.gemini/antigravity/skills exists. To disable, uncomment antigravity_enabled.
# On Antigravity v1.19.6 the directory is "global_skills" not "skills";
# override antigravity_skills_dir if you are on that version.
# antigravity_skills_dir = "~/.gemini/antigravity/skills"
# antigravity_enabled = false

# opencode (agents + commands + skills). Enabled by default once the roots exist or can
# be created. Some opencode builds report %USERPROFILE%\.config\opencode
# from opencode debug paths; override these paths if yours does.
# opencode_agents_dir = "$opencodeAgentsPath"
# opencode_commands_dir = "$opencodeCommandsPath"
# opencode_skills_dir = "$opencodeSkillsPath"
# opencode_rules_dir = "$opencodeRulesPath"
# opencode_enabled = false

# GitHub Copilot CLI agents and skills are enabled by default.
# VS Code user-profile instructions/prompts are path-configured because
# profile locations vary by install.
# copilot_cli_agents_dir = "~/.copilot/agents"
# copilot_cli_skills_dir = "~/.copilot/skills"
# copilot_vscode_user_instructions_dir = "C:/path/to/vscode/profile/instructions"
# copilot_vscode_user_prompts_dir = "C:/path/to/vscode/profile/prompts"
# copilot_enabled = false
"@
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($ConfigFile, $cfg, $utf8NoBom)
  }
}

function Register-AgentsSyncTask([string]$Name, [string]$HiddenLauncherFile) {
  $wscript = Join-Path $env:WINDIR "System32\wscript.exe"
  if (-not (Test-Path $wscript)) {
    $wscript = "wscript.exe"
  }
  $action = New-ScheduledTaskAction -Execute $wscript -Argument "//B //Nologo `"$HiddenLauncherFile`""
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
    -Description "Bidirectional sync of Claude Code, Codex, Antigravity, and opencode customizations" `
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
Install-HiddenLauncher -LauncherFile $HiddenLauncherPath -VenvEntrypoint $VenvExe -CfgPath $ConfigPath -LogFile $LogPath
Register-AgentsSyncTask -Name $TaskName -HiddenLauncherFile $HiddenLauncherPath

Write-Host "Installed $AppName"
Write-Host "Launcher:        $LauncherPath"
Write-Host "Hidden launcher: $HiddenLauncherPath"
Write-Host "Config:          $ConfigPath"
Write-Host "Log:             $LogPath"
Write-Host "Task:            $TaskName"
