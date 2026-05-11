# agents_sync

## Purpose

`agents_sync` keeps Claude Code user-defined agents and skills in sync with their Codex equivalents in both directions. Edit on either side; the change propagates to the other within seconds.

## Problem statement

Claude Code stores user-level agents at `~/.claude/agents/*.md` and user-level skills at `~/.claude/skills/<name>/`. Codex stores its agent and skill equivalents at `~/.codex/agents/*.toml` and `~/.agents/skills/<name>/`. Maintaining the same set of agents and skills on both sides by hand is tedious and drifts. The first version of this tool (`claude-codex-sync` v0.1) translated one-way, Claude -> Codex, and dropped Claude-only metadata into a JSON-in-body blob for manual review. `agents_sync` v0.2 made sync bidirectional and lossless via a per-pair canonical JSON intermediate; v0.3 adds first-class Windows operations.

## Scope

In scope:

- Bidirectional sync of user-level agents and skills between Claude Code and Codex.
- Lossless round-trip via a per-pair canonical JSON intermediate.
- Identity-preserving sync via injected `pair_id` UUIDs on both sides.
- Conflict resolution by last-modified time when both sides diverge in the same poll.
- Data preservation: every operation that would overwrite or remove user content first archives the prior bytes.
- Auto-adoption of foreign artifacts (files created directly on either side without using the tool).
- Explicit generated filenames for new counterparts, with the item kind included in the slug.
- Continuous daemon operation (no one-shot CLI mode).
- Background supervision:
  - Linux: `systemd --user` service.
  - Windows: per-user Task Scheduler task using a hidden startup launcher.

Out of scope (initially):

- Project-scoped agents (`<project>/.claude/agents/`) - only user-level for now.
- Multi-user / multi-host sync (cloud, network filesystem).
- Sync of session state, conversation history, hooks state, or MCP server runtime data.
- A GUI; CLI only.
- inotify / fsevents / ReadDirectoryChangesW - periodic polling at a configurable interval is sufficient.
- Field-level merge of simultaneous edits - last-`mtime`-wins is the policy.

## Stakeholders

- **Primary user**: a developer running both Claude Code and Codex on the same workstation, maintaining a personal set of agents and skills, wanting a single source of truth without manual translation.
- **Personas** (used in user stories):
  - **Alice** - experienced power user; values efficiency, configurability, observability.
  - **Bob** - novice user; relies on sensible defaults and clear error messages.

## Goals

1. Editing on either side propagates to the other within at most two polling intervals.
2. Renaming, editing, or reorganizing agents on either side does not break the sync pair.
3. No user-authored content is ever destroyed; every overwrite or removal first archives the prior bytes under a deterministic, recoverable layout.
4. The tool runs unattended as a background user service/task and recovers from transient errors without operator intervention.

## Non-goals

- Modifying Claude Code or Codex themselves.
- Resolving simultaneous concurrent writes from a third-party tool to the same file mid-poll.
- Translating fields that have no semantic mapping between sides; such fields ride in passthrough buckets within the canonical and are emitted only on the side they came from.

## Constraints

- Cross-platform user environment:
  - Linux supported via `systemd --user`.
  - Windows supported via per-user Task Scheduler without a visible terminal at logon.
- Python 3.12+.
- `uv` for environment management.
- Single user, single workstation.

## Architectural sketch

```
Claude .md  --parse-->  canonical.json  --render-->  Codex .toml
Claude .md  <--render-- canonical.json  <--parse---  Codex .toml
```

Each side is a projection of the canonical. On any change to a side, the tool reverse-projects the change into the canonical, then forward-projects to the other side. Round-trip stability - `parse(render(c)) == c` - is what makes loop suppression sound.

Per-pair state is stored under the platform default state root (Linux `~/.local/state/agents-sync/`; Windows `%LOCALAPPDATA%\\agents-sync\\state\\`):

- `state.json` - thin index of `pair_id -> {paths, digests}`.
- `canonical/<pair_id>.json` - one canonical document per pair.
- `archive/<pair_id>/<side>/<filename>.<ISO-timestamp>` - preserved prior bytes.

The tool does not use an on-disk lock; concurrency safety is achieved by atomic writes and self-healing polls - see US-09 and NFR-03 / NFR-04.

## Glossary

- **Pair**: a logical agent or skill that exists on both sides, identified by a UUIDv4 `pair_id` injected into both sides' files.
- **Canonical**: a per-pair JSON document storing the union of fields from both sides; the lossless intermediate that drives both renderers.
- **Render**: project the canonical into a side-specific file (Claude `.md` or Codex `.toml`).
- **Parse**: the inverse of render; read a side-specific file and update the canonical.
- **Archive**: the directory under the state root where prior versions of files are preserved before any destructive overwrite.
- **Foreign artifact**: a file on either side without a `pair_id`, awaiting adoption.
- **Slug**: the filesystem-friendly form of an agent or skill `name`; determines the basename of a rendered file. New generated counterparts include the item kind, for example `ci-yaml-agent.toml` or `formatter-skill/SKILL.md`.

## References

- User stories: `docs/stories/US-XX-*.md`
- Requirements: `docs/project_requirements.md`
