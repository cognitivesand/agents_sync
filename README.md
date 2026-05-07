# agents_sync

Bidirectional sync of Claude Code user agents and skills with Codex. The daemon polls both sides at a configurable interval and propagates edits in both directions through a per-pair canonical JSON intermediate. Identity survives rename via injected `pair_id`s; data is preserved via timestamped archives; simultaneous edits resolve by last-`mtime`.

## What it syncs

| Claude source | Codex target |
|---|---|
| `~/.claude/agents/*.md` | `~/.codex/agents/*.toml` |
| `~/.claude/skills/*/SKILL.md` | `~/.agents/skills/*/SKILL.md` |

## Install

Install `uv` first if needed.

```bash
chmod +x install.sh
./install.sh
```

The script installs the `agents-sync` launcher under `~/.local/bin/`, seeds `~/.config/agents-sync/config.toml` if missing, and registers a systemd user service so the daemon runs continuously and survives reboots. `systemctl` and `uv` must be available; no other flags are needed.

## Run

The daemon is the only execution mode; there is no one-shot CLI invocation.

```bash
agents-sync --config ~/.config/agents-sync/config.toml
```

Stop it with `Ctrl-C` (or `systemctl --user stop agents-sync` if installed as a service).

## State layout

```
~/.local/state/agents-sync/
  state.json                                    pair_id -> {paths, digests}
  canonical/<pair_id>.json                      one canonical document per pair
  archive/<pair_id>/<side>/<filename>.<ISO>     preserved prior bytes
```

## Notes

- First sight of a Claude `.md` or skill `SKILL.md` without a `pair_id` triggers adoption: the original is archived, then `pair_id` is injected so the file's identity follows it across renames.
- First sight of a Codex `.toml` or skill folder without a `pair_id` is treated symmetrically: original archived, `pair_id` injected, Claude counterpart created.
- Removing one side of a pair archives the other side and drops the pair from state.
- The daemon fails closed when configured roots are missing or unreadable; a missing directory is never interpreted as "all files were deleted."
- Managed `pair_id`s must be canonical UUIDv4 strings. Malformed IDs, duplicate IDs, and target path collisions are skipped with errors instead of being adopted or overwritten.
- A v0.1 `claude-codex-sync` install at `~/.config/claude-codex-sync/` or `~/.local/state/claude-codex-sync/` is **not** auto-migrated; the daemon errors out and asks you to remove or move those paths first.

## Changelog

### 0.2.1

- Added fail-closed validation for configured sync roots.
- Rejected malformed or duplicate `pair_id` values before filesystem use.
- Added target collision checks for foreign artifact adoption.
- Added regression tests for v0.2.1 safety behavior.

## Documentation

- `docs/project_description.md` — purpose, scope, glossary.
- `docs/project_requirements.md` — FR / NFR.
- `docs/stories/US-XX-*.md` — user stories.
- `docs/v0.2_implementation_plan.md` — engineering plan.
- `docs/v0.2.1_remediation_plan.md` — safety remediation plan.

## License

MIT License. See `LICENSE`.
