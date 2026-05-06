# agents_sync

Bidirectional sync of Claude Code user agents and skills with Codex.

**Phase 1** is a structural rename of `claude-codex-sync` v0.1: the package, console script, and install paths become `agents_sync` / `agents-sync`, and the source is split into focused modules. Runtime behaviour is unchanged from v0.1 (one-way Claude → Codex). Phase 2 introduces a per-pair canonical JSON intermediate; bidirectional sync lands in Phase 3. See `docs/v0.2_implementation_plan.md` for the full plan.

## What it currently does (Phase 1)

| Claude source | Codex target |
|---|---|
| `~/.claude/agents/*.md` | `~/.codex/agents/*.toml` |
| `~/.claude/skills/*/SKILL.md` | `~/.agents/skills/*/SKILL.md` |

The sync uses SHA-256 hashes. If a source file or skill folder changes, it is re-exported.

## Install

Install `uv` first if needed.

```bash
chmod +x install.sh
./install.sh
```

Install and enable the user systemd service:

```bash
./install.sh --service
```

## Run

One-shot sync (Phase 1 only — removed in Phase 4):

```bash
agents-sync --once --config ~/.config/agents-sync/config.toml
```

Watch mode:

```bash
agents-sync --watch --config ~/.config/agents-sync/config.toml
```

Prune generated targets when Claude sources are deleted:

```bash
agents-sync --watch --prune --config ~/.config/agents-sync/config.toml
```

## Notes

Claude-specific fields such as `tools`, `permissionMode`, `hooks`, `mcpServers`, and some skill metadata are currently preserved as a "review metadata" block inside the rendered Codex output. Phase 2 moves this fidelity into a per-pair canonical JSON document and removes the in-output blob.

## Documentation

- `docs/project_description.md` — purpose, scope, glossary.
- `docs/project_requirements.md` — FR / NFR.
- `docs/stories/US-XX-*.md` — user stories.
- `docs/v0.2_implementation_plan.md` — engineering plan.
