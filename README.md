# agents_sync

`agents_sync` is a bidirectional sync tool for keeping Claude Code agents and skills synchronized with Codex automatically.

Create or edit an agent in Claude Code, and the matching Codex file appears within a few seconds. Create or edit an agent in Codex, and the matching Claude Code file appears the same way.

The daemon runs in the background, preserves user content through archives, and keeps pairs stable across renames with `pair_id`s.

## Bidirectional Sync

`agents_sync` does not have a primary side. Claude Code and Codex can both be edited directly.

| Action | Result |
|---|---|
| Create or edit a Claude Code agent | Codex receives the matching `.toml` file |
| Create or edit a Codex agent | Claude Code receives the matching `.md` file |
| Create or edit a Claude Code skill | Codex receives the matching skill folder |
| Create or edit a Codex skill | Claude Code receives the matching skill folder |
| Remove one side of a synced pair | The other side is archived, then removed |

## What It Syncs

| Claude Code | Codex |
|---|---|
| `~/.claude/agents/*.md` | `~/.codex/agents/*.toml` |
| `~/.claude/skills/*/SKILL.md` | `~/.agents/skills/*/SKILL.md` |

## Quick Start

### Linux

Install `uv` if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install and start `agents_sync`:

```bash
chmod +x install.sh
./install.sh
```

Check that it is running:

```bash
systemctl --user status agents-sync.service
journalctl --user -u agents-sync.service -n 20
```

### Windows

Install `uv` if needed:

```powershell
winget install --id=astral-sh.uv -e
```

Install and start `agents_sync`:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Check that it is running:

```powershell
Get-ScheduledTask -TaskName agents-sync
Get-Content "$env:LOCALAPPDATA\agents-sync\logs\agents-sync.log" -Tail 20
```

The Windows installer registers a per-user scheduled task. It starts at logon without opening a terminal window.

## Daily Usage

After installation, there is nothing else to start manually.

On Linux, `agents_sync` runs as a `systemd --user` service.

On Windows, `agents_sync` starts through Task Scheduler when you log in.

You can create, edit, rename, or remove agents and skills from either side:

- Claude Code -> Codex changes are propagated.
- Codex -> Claude Code changes are propagated.
- Removals are propagated after the opposite side is archived.
- Existing sync pairs keep their identity through the injected `pair_id`.

## Check That It Is Running

### Linux

```bash
systemctl --user status agents-sync.service
journalctl --user -u agents-sync.service -n 20
```

### Windows

```powershell
Get-ScheduledTask -TaskName agents-sync
```

Expected state:

```text
Running
```

Recent logs:

```powershell
Get-Content "$env:LOCALAPPDATA\agents-sync\logs\agents-sync.log" -Tail 20
```

Expected log line:

```text
INFO Watching Claude agents/skills with SHA256 polling
```

## Generated File Names

When `agents_sync` creates a counterpart file, it uses explicit generated names that include the item kind.

| Item name | Kind | Generated counterpart |
|---|---|---|
| `CI.yaml` | agent | `ci-yaml-agent.md` / `ci-yaml-agent.toml` |
| `formatter` | skill | `formatter-skill/SKILL.md` |
| `review-agent` | agent | `review-agent.md` / `review-agent.toml` |

If a name already ends with `-agent`, `-agents`, `-skill`, or `-skills`, the kind is not duplicated.

Existing managed paths are preserved. Upgrading the tool does not rename already-synced files unexpectedly.

## Smoke Test

This test creates a temporary Claude agent, checks that Codex receives it, edits Codex, and checks that Claude receives the edit.

### Linux

```bash
mkdir -p ~/.claude/agents
cat > ~/.claude/agents/readme-smoke-agent.md <<'EOF'
---
name: readme-smoke-agent
description: README smoke test
---
You are a test agent.
EOF

sleep 4
cat ~/.codex/agents/readme-smoke-agent.toml
```

You should see a Codex TOML file containing `name`, `description`, `developer_instructions`, and a generated `pair_id`.

Clean up:

```bash
rm -f ~/.claude/agents/readme-smoke-agent.md
rm -f ~/.codex/agents/readme-smoke-agent.toml
```

### Windows

$name = "readme-smoke-agent"
$claudeFile = "$HOME\.claude\agents\$name.md"
$codexFile = "$HOME\.codex\agents\$name.toml"

$content = @'
---
name: readme-smoke-agent
description: README smoke test
---
You are a test agent.
'@

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($claudeFile, $content, $utf8NoBom)

Start-Sleep -Seconds 4
Get-Content $codexFile
```

Clean up:

```powershell
Remove-Item "$HOME\.claude\agents\readme-smoke-agent.md" -ErrorAction SilentlyContinue
Remove-Item "$HOME\.codex\agents\readme-smoke-agent.toml" -ErrorAction SilentlyContinue
```

## Run In Foreground For Debugging

The normal install runs the daemon in the background. Use foreground mode only when debugging.

### Linux

```bash
agents-sync --config ~/.config/agents-sync/config.toml --verbose
```

Stop with `Ctrl-C`.

### Windows

```powershell
& "$env:LOCALAPPDATA\agents-sync\bin\agents-sync.cmd" --config "$env:APPDATA\agents-sync\config.toml" --verbose
```

Stop with `Ctrl-C`.

## Manage The Background Service

### Linux

```bash
systemctl --user status agents-sync.service
systemctl --user stop agents-sync.service
systemctl --user start agents-sync.service
journalctl --user -u agents-sync.service -f
```

### Windows

```powershell
Get-ScheduledTask -TaskName agents-sync
Stop-ScheduledTask -TaskName agents-sync
Start-ScheduledTask -TaskName agents-sync
Get-Content "$env:LOCALAPPDATA\agents-sync\logs\agents-sync.log" -Tail 50
```

## Uninstall

### Linux

```bash
./uninstall.sh
```

### Windows

Remove the scheduled task and launchers:

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
```

Also remove config and state:

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -CleanupData
```

## Default Paths

| Platform | Config | State | Logs |
|---|---|---|---|
| Linux | `~/.config/agents-sync/config.toml` | `~/.local/state/agents-sync/` | `journalctl --user -u agents-sync.service` |
| Windows | `%APPDATA%\agents-sync\config.toml` | `%LOCALAPPDATA%\agents-sync\state\` | `%LOCALAPPDATA%\agents-sync\logs\agents-sync.log` |

State layout:

```text
state.json                                pair_id -> paths and digests
canonical/<pair_id>.json                  one canonical document per pair
archive/<pair_id>/<side>/<filename>.<ISO> preserved prior bytes
```

## Troubleshooting

### Windows: `uv` is not found

Install `uv`, then reopen PowerShell:

```powershell
winget install --id=astral-sh.uv -e
```

Alternative installer:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Windows: no terminal appears at startup

That is expected. The daemon runs hidden through Task Scheduler.

Check the task:

```powershell
Get-ScheduledTask -TaskName agents-sync
```

Check logs:

```powershell
Get-Content "$env:LOCALAPPDATA\agents-sync\logs\agents-sync.log" -Tail 50
```

### Windows: PowerShell-created files contain a UTF-8 BOM

`agents_sync` tolerates UTF-8 BOM input for:

- config TOML
- Claude Markdown files
- Codex TOML files

The Windows installer writes its seeded config as UTF-8 without BOM.

### A file was removed unexpectedly

Before overwriting or removing managed content, `agents_sync` archives prior bytes under the state archive directory.

Linux archive:

```text
~/.local/state/agents-sync/archive/
```

Windows archive:

```text
%LOCALAPPDATA%\agents-sync\state\archive\
```

## Notes

- The daemon polls both sides at a configurable interval.
- First sight of a Claude `.md`, Claude skill `SKILL.md`, Codex `.toml`, or Codex skill folder without a `pair_id` triggers adoption.
- Adoption archives the original, injects a `pair_id`, and creates the counterpart on the other side.
- Removing one side of a pair archives the other side and drops the pair from state.
- Missing or unreadable configured roots fail closed. A missing directory is never interpreted as "all files were deleted."
- Malformed `pair_id`s, duplicate IDs, and target path collisions are skipped with errors instead of being adopted or overwritten.
- A v0.1 `claude-codex-sync` install at `~/.config/claude-codex-sync/` or `~/.local/state/claude-codex-sync/` is not auto-migrated. The daemon errors out and asks you to remove or move those paths first.

## Changelog

### 0.3.0

- Added first-class Windows install and background supervision.
- Added hidden Windows startup through Task Scheduler without a visible terminal window.
- Added platform-aware defaults for config and state paths.
- Added filesystem retry hardening for transient Windows lock/share violations.
- Added Windows filename and path-collision safety checks.
- Added generated counterpart names that include the item kind.
- Added Linux and Windows CI coverage.

### 0.2.1

- Added fail-closed validation for configured sync roots.
- Rejected malformed or duplicate `pair_id` values before filesystem use.
- Added target collision checks for foreign artifact adoption.
- Added regression tests for v0.2.1 safety behavior.

## Documentation

- `docs/project_description.md` - purpose, scope, glossary.
- `docs/project_requirements.md` - functional and non-functional requirements.
- `docs/stories/US-XX-*.md` - user stories.
- `docs/v0.2_implementation_plan.md` - v0.2 engineering plan.
- `docs/v0.2.1_remediation_plan.md` - safety remediation plan.
- `docs/v0.3_implementation_plan.md` - Windows support plan.

## License

MIT License. See `LICENSE`.

