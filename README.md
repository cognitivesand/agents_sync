# agents_sync

Bidirectional sync of Claude Code user agents and skills with Codex. The daemon polls both sides at a configurable interval and propagates edits in both directions through a per-pair canonical JSON intermediate. Identity survives rename via injected `pair_id`s; data is preserved via timestamped archives; simultaneous edits resolve by last-`mtime`.

## What it syncs

| Claude source | Codex target |
|---|---|
| `~/.claude/agents/*.md` | `~/.codex/agents/*.toml` |
| `~/.claude/skills/*/SKILL.md` | `~/.agents/skills/*/SKILL.md` |

Newly created counterparts use explicit generated names based on the item kind:

| Item name | Kind | Generated counterpart |
|---|---|---|
| `CI.yaml` | agent | `ci-yaml-agent.md` / `ci-yaml-agent.toml` |
| `formatter` | skill | `formatter-skill/SKILL.md` |

## Install

Install `uv` first if needed.

Linux/macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows:

```powershell
winget install --id=astral-sh.uv -e
# or:
powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Linux (systemd --user)

```bash
chmod +x install.sh
./install.sh
```

The script installs the `agents-sync` launcher under `~/.local/bin/`, seeds `~/.config/agents-sync/config.toml` if missing, and registers a systemd user service so the daemon runs continuously and survives reboots. `systemctl` and `uv` must be available; no other flags are needed.

### Windows (Task Scheduler, per-user)

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The script verifies `python` and `uv`, runs `uv sync`, writes a launcher under `%LOCALAPPDATA%\\agents-sync\\bin\\agents-sync.cmd`, seeds `%APPDATA%\\agents-sync\\config.toml` if missing, and registers a per-user scheduled task `agents-sync` triggered at logon.

Use `-Force` to regenerate the Windows config file:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Force
```

## Run

The daemon is the only execution mode; there is no one-shot CLI invocation.

```bash
agents-sync --config ~/.config/agents-sync/config.toml
```

Stop it with `Ctrl-C`.

Windows foreground run for debugging:

```powershell
& "$env:LOCALAPPDATA\agents-sync\bin\agents-sync.cmd" --config "$env:APPDATA\agents-sync\config.toml" --verbose
```

Linux service management:

```bash
systemctl --user status agents-sync.service
systemctl --user stop agents-sync.service
systemctl --user start agents-sync.service
journalctl --user -u agents-sync.service -f
```

Windows task management:

```powershell
Get-ScheduledTask -TaskName agents-sync
Stop-ScheduledTask -TaskName agents-sync
Start-ScheduledTask -TaskName agents-sync
```

Windows uninstall:

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
# Optional explicit cleanup of config/state:
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -CleanupData
```

## State layout

Linux default:

```
~/.local/state/agents-sync/
  state.json                                    pair_id -> {paths, digests}
  canonical/<pair_id>.json                      one canonical document per pair
  archive/<pair_id>/<side>/<filename>.<ISO>     preserved prior bytes
```

Windows default:

```
%LOCALAPPDATA%\agents-sync\state\
  state.json                                    pair_id -> {paths, digests}
  canonical\<pair_id>.json                      one canonical document per pair
  archive\<pair_id>\<side>\<filename>.<ISO>     preserved prior bytes
```

Windows config default:

```
%APPDATA%\agents-sync\config.toml
```

## Verify

Run the test suite:

```bash
uv run pytest
```

Manual smoke test:

1. Start the daemon in a foreground terminal.
2. Create a Claude agent under `~/.claude/agents/`.
3. Confirm the Codex `.toml` appears under `~/.codex/agents/`.
4. Edit the Codex `.toml` and confirm the Claude `.md` updates.
5. Remove one side and confirm the other side is removed after being archived.

## Notes

- First sight of a Claude `.md` or skill `SKILL.md` without a `pair_id` triggers adoption: the original is archived, then `pair_id` is injected so the file's identity follows it across renames.
- First sight of a Codex `.toml` or skill folder without a `pair_id` is treated symmetrically: original archived, `pair_id` injected, Claude counterpart created.
- Removing one side of a pair archives the other side and drops the pair from state.
- The daemon fails closed when configured roots are missing or unreadable; a missing directory is never interpreted as "all files were deleted."
- Managed `pair_id`s must be canonical UUIDv4 strings. Malformed IDs, duplicate IDs, and target path collisions are skipped with errors instead of being adopted or overwritten.
- A v0.1 `claude-codex-sync` install at `~/.config/claude-codex-sync/` or `~/.local/state/claude-codex-sync/` is not auto-migrated; the daemon errors out and asks you to remove or move those paths first.
- Windows-authored UTF-8 files with a BOM are tolerated for config, Claude Markdown, and Codex TOML inputs. The Windows installer writes its seeded config as UTF-8 without BOM.
- New rendered counterpart filenames include the item kind (`-agent` or `-skill`) unless the name already ends with that kind, so generated paths are easier to identify.

## Changelog

### 0.3.0

- Added first-class Windows install and background supervision (`install.ps1`, `uninstall.ps1`, scheduled task).
- Added platform-aware defaults for config/state paths.
- Added filesystem retry hardening for transient lock/share violations.
- Added Windows filename and path-collision safety checks.
- Added Linux + Windows CI matrix coverage.

### 0.2.1

- Added fail-closed validation for configured sync roots.
- Rejected malformed or duplicate `pair_id` values before filesystem use.
- Added target collision checks for foreign artifact adoption.
- Added regression tests for v0.2.1 safety behavior.

## Documentation

- `docs/project_description.md` - purpose, scope, glossary.
- `docs/project_requirements.md` - FR / NFR.
- `docs/stories/US-XX-*.md` - user stories.
- `docs/v0.2_implementation_plan.md` - engineering plan.
- `docs/v0.2.1_remediation_plan.md` - safety remediation plan.
- `docs/v0.3_implementation_plan.md` - Windows support plan.

## License

MIT License. See `LICENSE`.
