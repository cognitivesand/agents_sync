# agents_sync

## Purpose

`agents_sync` keeps user-authored agents, skills, rules, slash commands, and MCP servers in sync across multiple agentic_tools (for example Claude Code, Codex, GitHub Copilot, Cursor, Gemini CLI, Google Antigravity, and opencode) in both directions. Edit a customization in any configured agentic_tool, and within seconds the change propagates to every other agentic_tool that supports the same `customization_type`.

## Problem statement

Every agentic_tool stores its agents and skills under its own filesystem layout. For example:

- Claude Code: user-level agents at `~/.claude/agents/*.md`; user-level skills at `~/.claude/skills/<name>/SKILL.md`.
- Codex: user-level agents at `~/.codex/agents/*.toml`; user-level skills at `~/.codex/skills/<name>/SKILL.md`.
- Cursor: user-level agents at `~/.cursor/agents/*.md`; user-level skills at `~/.cursor/skills/<name>/SKILL.md`; rules, slash commands, and MCP servers under `~/.cursor/`.
- Google Antigravity: skills at `~/.gemini/antigravity/skills/<name>/SKILL.md` (no per-agent file format as of v0.4 release).
- opencode: user-level agents at `~/.config/opencode/agents/*.md`; user-level skills at `~/.config/opencode/skills/<name>/SKILL.md`.

Maintaining the same library of customizations across two or more such agentic_tools by hand is tedious and drifts.

Release history:

- v0.1 (`claude-codex-sync`): one-way translation, Claude → Codex; Claude-only metadata dropped into a JSON-in-body blob for manual review.
- v0.2: bidirectional, lossless sync between two agentic_tools (Claude Code, Codex) via a per-customization_artifact canonical JSON intermediate.
- v0.3: first-class Windows operations.
- v0.4: generalisation to **N agentic_tools** via the agentic-tool-integration protocol (`docs/agentic_tool_integration_protocol.md`). Each additional agentic_tool is a small, isolated spec factory plus config entries; no sync-algorithm changes are required.
- v0.4.1: opencode added for agents and skills; Codex custom agents restored under `~/.codex/agents/*.toml`.
- v0.5: three new agentic_tools (Cursor, Gemini CLI, GitHub Copilot) and three new customization_types (`rules`, `slash_command`, `mcp_server`). Antigravity remains the canonical owner of `~/.gemini/antigravity/skills/`; Gemini CLI also exposes `~/.gemini/skills/` as a normal `skill` root. A new top-level config key `secret_policy` (`secrets_refused` / `secrets_accepted`, default `secrets_refused`) governs how literal secrets in MCP-server `env`, `headers`, and `auth.*` fields are handled. The deprecated `mcp_server_secret_policy` key and its legacy values are accepted for one release as compatibility aliases, scheduled for removal in v0.6 (see `docs/mcp_server_secret_policy_deprecation_cleanup_plan.md`).

## Scope

In scope:

- Bidirectional sync of user-level customizations across N registered agentic_tools.
- N may be 1 (degenerate, no work), 2 (two-tool sync as in v0.3), or higher (multi-tool sync introduced in v0.4).
- Lossless round-trip via a per-customization_artifact canonical JSON intermediate; every agentic_tool is a projection of the canonical.
- Identity-preserving sync: a UUIDv4 `customization_artifact_id` is injected into every agentic_tool's copy of the artifact.
- Conflict resolution by last-modified time: when ≥ 2 agentic_tools diverge in one poll, the most recent wins and every loser's bytes are archived first (US-06).
- Data preservation: every operation that would overwrite or remove user content first archives the prior bytes under a deterministic, recoverable layout (US-05).
- Auto-adoption of new customization artifacts; first-boot reconciliation of multi-tool duplicates by `(customization_type, target_slug(name))` reconciliation key (US-03).
- Graceful absence: if a registered, enabled agentic_tool's root becomes missing or unreadable, the tool is marked `unavailable` and the transition is logged once. An `unavailable` tool never causes a removal to propagate to healthy tools (US-11).
- Explicit generated filenames for new counterparts; agents and skills use the bare slugified artifact name inside their distinct roots (e.g. `formatter/SKILL.md` for skills).
- Continuous daemon operation, plus one-shot CLI subcommands for portable export and import of the canonical library (US-12).
- Portable library snapshot: one-shot `export` and `import` subcommands that serialise the canonical store to a single archive file and restore it on another install (US-12).
- Background supervision:
  - Linux: `systemd --user` service.
  - Windows: per-user Task Scheduler task.

Out of scope (initially):

- Project-scoped customizations (e.g. `<project>/.claude/agents/`, `<workspace>/.agents/skills/`) — only user-level for now.
- Multi-user / multi-host sync (cloud, network filesystem).
- Sync of session state, conversation history, hooks state, or MCP server runtime data.
- A GUI; CLI only.
- inotify / fsevents / ReadDirectoryChangesW — periodic polling at a configurable interval is sufficient.
- Field-level merge of simultaneous edits — last-`mtime`-wins is the policy.
- Cursor's in-app settings pane state (`state.vscdb` SQLite), including the User Rules pane, in-app Custom Modes, account-stored Memories, Notepads, and per-account model selection. `agents_sync` syncs only Cursor's on-disk file surfaces (`.cursor/rules/*.mdc`, `.cursor/commands/`, `.cursor/mcp.json`, the user-scope mirrors). This limitation is intentional and structural: SQLite state is not addressable as files.

## Stakeholders

- **Primary user**: a developer running two or more agentic_tools on the same workstation, maintaining a personal set of agents and skills, wanting a single source of truth without manual translation across agentic_tools.
- **Personas** (used in user stories):
  - **Alice** — experienced power user; values efficiency, configurability, observability.
  - **Bob** — novice user; relies on sensible defaults and clear error messages.

## Goals

1. Editing a customization on any one agentic_tool propagates to every other participating agentic_tool within at most two polling intervals.
2. Renaming, editing, or reorganising a customization on any one agentic_tool preserves its `customization_artifact_id` and continues to propagate to the other agentic_tools: a rename is never mistaken for a delete-plus-create, and no duplicate customization_artifact is produced (US-04).
3. No user-authored content is ever destroyed; every overwrite or removal first archives the prior bytes under a deterministic, recoverable layout.
4. The tool runs unattended as a background user service/task and, as far as possible, recovers from transient errors without operator intervention.
5. Adding support for a new agentic_tool is a small, isolated change: one new spec factory under `src/agents_sync/tool_specs/<tool_name>.py`, registered in `default_agentic_tools()`, plus matching config defaults and CLI/config keys — with no edits to the sync engine. This is the v0.5 objective: the engine now carries enough generality that adding a post-v0.5 agentic_tool needs no engine change (only minimal additions if a new compatibility issue surfaces). Adding a new `customization_type` is a larger change — it must teach the engine how to store and reconcile the type via `agents_sync.agentic_tool_spec` (NFR-11) — and so is not covered by this no-engine-edit guarantee.
6. No user secret is ever silently propagated: literal credentials carried in a customization_artifact are handled per the configured `secret_policy`, which defaults to refusing to propagate them (NFR-15).

## Non-goals

- Modifying the agentic_tools themselves.
- Resolving simultaneous concurrent writes from a third-party tool to the same file mid-poll.
- Translating fields that have no semantic mapping across agentic_tools. Such fields are kept in the canonical's per-tool passthrough sections (`per_agentic_tool_only`, `per_agentic_tool_extra`) and re-emitted only on the agentic_tool they came from.

## Constraints

- Cross-platform user environment:
  - Linux supported via `systemd --user`.
  - Windows supported via per-user Task Scheduler.
  - macOS supported on a best-effort basis (background-install flow untested as of v0.4).
- Python 3.12+.
- `uv` for environment management.
- Single user, single workstation.

## Architectural sketch

```
agentic_tool_1 native format  ──parse──▶  canonical.json  ──render──▶  agentic_tool_2 native format
agentic_tool_1 native format  ◀──render──  canonical.json  ──parse──▶  agentic_tool_3 native format
                                                          ──render──▶  agentic_tool_N native format
```

Each agentic_tool is a projection of the canonical. On any change to an agentic_tool, the daemon reverse-projects the change into the canonical, then forward-projects to every other participating agentic_tool. Round-trip stability — `parse(render(c)) == c` over the agentic_tool-relevant subset of `c` — is what makes loop suppression sound.

Per-customization_artifact state is stored under the platform default state root (Linux `~/.local/state/agents-sync/`; Windows `%LOCALAPPDATA%\\agents-sync\\state\\`):

- `state.json` — versioned envelope: `{"schema_version": 3, "customization_artifacts": {<customization_artifact_id>: {"customization_artifact": ..., "agentic_tools": {<name>: {"path": ..., "digests": ...}}}}}`.
- `canonical/<customization_artifact_id>.json` — one canonical document per customization_artifact, including `per_agentic_tool_only` and `per_agentic_tool_extra` passthrough bags per agentic_tool.
- `archive/<customization_artifact_id>/<agentic_tool_name>/<filename>.<ISO-timestamp>` — preserved prior bytes.

The tool does not use an on-disk lock; concurrency safety is achieved by atomic writes and self-healing polls — see US-09 and NFR-03 / NFR-04.

## Glossary

Each entry pairs the technical identifier used in code, configs, ACs, and schemas with the first-person prose form used in user stories and the README.

- **`agentic_tool`** (prose: "my agentic_tools") — an external application that consumes user-authored, reusable files (e.g. Claude Code, Codex, Cursor, Google Antigravity, opencode). The user installs and uses agentic_tools directly; `agents_sync` does not modify them. In this codebase, the integration module for a given agentic_tool is itself called an `agentic_tool` — a 1:1 correspondence with the external tool, with no separate "side" or "peer" abstraction.
- **`agentic_tool` status** (prose: "available / unavailable / disabled") — at a given poll: `available` (configured, enabled, root reachable), `unavailable` (configured, enabled, root missing or unreadable), or `disabled` (turned off in config).
- **`user_customization`** (prose: "my customizations") — the umbrella term for the domain of user-authored customizations that `agents_sync` manages, across every `customization_type`. Used in user-facing prose and as a global concept. The concrete unit of synchronisation is the `customization_artifact` (below); a `user_customization` is what you mean colloquially when you say "I'm customising my agentic_tools."
- **`customization_artifact`** (prose: "a customization", "my agent", "my skill") — a specific managed instance: a user-authored customization identified by a UUIDv4 `customization_artifact_id` and present on N agentic_tools (N ≥ 1) as N renditions of the same content. It is the technical unit of synchronisation: every poll, sync, conflict, removal, and reconciliation operates over customization_artifacts.
- **`customization_type`** — the category of a customization_artifact. v0.5 registers five: `agent` (a single managed file per customization_artifact), `skill` (a managed folder containing a `SKILL.md` written by the agentic_tool's renderer, plus optional auxiliary files), `rules` (a single Markdown file per rule with optional YAML frontmatter), `slash_command` (a single Markdown or TOML file per command with optional frontmatter), and `mcp_server` (one MCP server definition per customization_artifact, projected to one slot inside a shared keyed-map file). An agentic_tool declares which customization_types it can read and write via `supported_customization_types`. Each customization_type has an associated `file_layout` (single file, folder, or shared keyed-map slot) describing how it is stored on disk.
- **Participating `agentic_tools` for a customization_artifact** — agentic_tools whose `supported_customization_types` include the customization_artifact's `customization_type` AND whose status is `available`. Denoted **N** (N ≥ 1 for the customization_artifact to exist; N ≥ 2 for any cross-tool sync to happen; ≥ 2 changed simultaneously for a conflict).
- **Changed `agentic_tools` for a customization_artifact at the current poll** — the subset of participating agentic_tools whose current digest differs from the `last_written` digest recorded in state. ≥ 2 changed = conflict; exactly 1 = one-way propagation; 0 = no-op.
- **Available `agentic_tools` at a given poll** — registered, enabled agentic_tools whose status is `available` (root reachable, readable, writable).
- **Canonical** — per-customization_artifact JSON document storing the union of fields from every agentic_tool; the lossless intermediate that drives every renderer. It carries the canonical content itself as well as a nested `metadata` block.
- **`last_modified`** — POSIX timestamp (float) of when a customization_artifact's user content was last changed, not when its files were last written. Carried in the canonical's `metadata` block.
- **`generation`** — host-local monotonic counter, incremented on each content change of a customization_artifact. Carried in the canonical's `metadata` block.
- **Render / parse** — project the canonical onto an agentic_tool's native format; or fold the native format back into the canonical.
- **Archive** — directory under the state root where prior versions of files are preserved before any destructive overwrite.
- **New customization_artifact** — a customization_artifact whose artifact metadata does not yet contain a `customization_artifact_id`, awaiting adoption or reconciliation. See US-03.
- **Artifact metadata** — the structured block on a customization_artifact that declares its identifying fields (`name`, `customization_artifact_id`, `description`, and any agentic_tool-specific fields). Physical form varies per agentic_tool: a YAML block delimited by `---` for `.md` files, the whole TOML document for `.toml` files, etc. Each agentic_tool module's `parse` and `render` functions are responsible for reading and writing it.
- **Reconciliation key** — `(customization_type, target_slug(name))`, used to group new customization_artifacts that represent the same logical user_customization across agentic_tools.
- **Slug** — the filesystem-friendly form of a customization_artifact's `name`; determines the basename of a rendered file. Agents and skills live in separate roots, so generated counterparts use the bare slug (e.g. `formatter/SKILL.md`).
- **Customization library** — the full set of canonical documents the daemon manages.
- **Customization library export** — the full canonical set packaged as a single transportable file (today a `.zip`) that another install can import.

## References

- Agentic-tool integration protocol (how to add a new agentic_tool): `docs/agentic_tool_integration_protocol.md`.
- User stories: `docs/stories/US-XX-*.md`.
- Requirements: `docs/project_requirements.md`.
- v0.4 implementation plan: `docs/v0.4_implementation_plan.md`.
- v0.4.1 implementation plan: `docs/v0.4.1_implementation_plan.md`.
