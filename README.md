# claude-codex-sync

Sync Claude Code user agents and skills into Codex locations.

## What it syncs

| Claude source | Codex target |
|---|---|
| `~/.claude/agents/*.md` | `~/.codex/agents/*.toml` |
| `~/.claude/skills/*/SKILL.md` | `~/.agents/skills/*/SKILL.md` |

The sync uses SHA256 hashes. If a source file or skill folder changes, it is re-exported.

## Install

Install `uv` first if needed.

Then:

```bash
chmod +x install.sh
./install.sh
```

Install and enable the user systemd service:

```bash
./install.sh --service
```

## Run

One-shot sync:

```bash
claude-codex-sync --once --config ~/.config/claude-codex-sync/config.toml
```

Watch mode:

```bash
claude-codex-sync --watch --config ~/.config/claude-codex-sync/config.toml
```

Prune generated targets when Claude sources are deleted:

```bash
claude-codex-sync --watch --prune --config ~/.config/claude-codex-sync/config.toml
```

## Notes

Claude-specific fields such as `tools`, `permissionMode`, `hooks`, `mcpServers`, and some skill metadata are preserved as review metadata when possible, but Codex may not enforce them directly.
