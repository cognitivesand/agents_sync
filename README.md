# agents_sync

`agents_sync` is a bidirectional bridge between Claude Code and Codex.

It keeps your custom agents and skills in sync automatically, so you can build your AI workflow once and use it from both tools. Create or edit something in Claude Code, and it appears in Codex. Create or edit it in Codex, and it comes back to Claude Code.

The daemon runs quietly in the background, protects your content with archives, and keeps files connected even when they are renamed.

## What It Syncs

`agents_sync` synchronizes the personal agents and skills you use with Claude Code and Codex.

| What you edit | Where Claude Code stores it | Where Codex stores it |
|---|---|---|
| Agents | `~/.claude/agents/*.md` | `~/.codex/agents/*.toml` |
| Skills | `~/.claude/skills/*/SKILL.md` | `~/.agents/skills/*/SKILL.md` |

In plain terms:

- Agents are reusable AI personas or workflows.
- Skills are reusable instruction folders.
- You can edit either Claude Code's version or Codex's version.
- `agents_sync` keeps the matching file or folder updated on the other side.

```mermaid
flowchart LR
    Claude["Claude Code\nagents + skills"]
    Sync["agents_sync\nbackground daemon"]
    Codex["Codex\nagents + skills"]
    Archive["Archive\nbefore overwrite or removal"]

    Claude <-->|bidirectional sync| Sync
    Sync <-->|bidirectional sync| Codex
    Sync --> Archive
```

## Bidirectional Sync

`agents_sync` does not have a primary side. Claude Code and Codex can both be edited directly.

| Action | Result |
|---|---|
| Create or edit a Claude Code agent | Codex receives the matching `.toml` file |
| Create or edit a Codex agent | Claude Code receives the matching `.md` file |
| Create or edit a Claude Code skill | Codex receives the matching skill folder |
| Create or edit a Codex skill | Claude Code receives the matching skill folder |
| Remove one side of a synced pair | The other side is archived, then removed |

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

### macOS

macOS support has not been tested yet.

The sync logic is expected to be portable, but the current background install flow is only documented and validated for Linux and Windows.

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

