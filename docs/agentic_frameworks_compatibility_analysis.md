# agents_sync — Agentic Frameworks Compatibility & Effort Analysis

Compiled against `docs/project_description.md`, `docs/architecture.md` (v0.4.1), `docs/agentic_tool_integration_protocol.md`, and `docs/agentic_frameworks_user_data_library.md`. Effort estimates assume the existing `AgenticToolSpec` / `CustomizationTypeIO` port and the constraint that the sync engine (`sync.py`, `adoption.py`, `discovery.py`, `tool_status.py`, `archive.py`, `state.py`, `rendering.py`) is not edited per new framework. "Identity" refers to the value an adapter's `extract_customization_artifact_id` can recover from the on-disk file — when none exists natively, an injected `customization_artifact_id` field is implied, which itself requires the framework's format to admit unknown keys without breaking.

---

## 1. Executive summary

The 20 frameworks divide cleanly into three bands relative to today's `customization_type` set (`agent`, `skill`).

- **Already in protocol shape (direct fit, agent + skill only): 4–5 frameworks.** Claude Code, opencode, OpenAI Codex CLI, Google Gemini CLI / Antigravity, and Gemini-CLI-style Junie subagents+skills all expose Markdown-with-YAML-frontmatter agents and `SKILL.md` skills, mostly under predictable `~/.<tool>/` roots. v0.4.1 already covers Claude/Codex/Antigravity/opencode for these two types.
- **Need new `customization_type` values to do useful work: 12 frameworks.** The pattern that recurs is unmistakable: every framework that has more than a single Markdown surface adds (in roughly this order of recurrence) **slash commands** (16/20 frameworks), **MCP server configs** (17/20), **rules / memory Markdown** (19/20 — `AGENTS.md` is now the de-facto cross-tool open file), **hooks** (8/20), and **modes / profiles** (5/20). Adding `slash_command`, `mcp_server`, `rules`, and (later) `hooks` and `mode` `customization_type` values covers all syncable user-authored surfaces on every framework except the four below.
- **Blocked or out of scope: 4 frameworks** as their primary customization surface. **Plandex** keeps plans/context server-side; only `custom-models.json` is local. **Zed**'s Prompt Library is LMDB-binary (page-layout-bound, architecture-bound — unsafe to byte-sync). **Cursor**'s most user-visible state (User Rules, in-app Modes, Memories before deprecation, Notepads, account model selection) lives in `state.vscdb` SQLite. **Cline** likewise places "Custom Instructions" and provider credentials in `state.vscdb`. Each of these *has* a syncable subset (Plandex models JSON, Zed `.rules` + `settings.json` profiles, Cursor `.cursor/rules/*.mdc` + `.cursor/commands/`, Cline `.clinerules/`), but the headline feature is unreachable from files.

**Recommended next `customization_type` additions, priority-ordered:**
1. `slash_command` (single-file Markdown with YAML frontmatter; covers Claude, opencode, Codex, Gemini CLI, Cursor, Roo, Kilo, Junie, Copilot, Q Developer, plus Aider-via-`alias`).
2. `mcp_server` (one canonical schema per server, transport-tagged `stdio` / `http` / `sse` / `streamable_http`; one file per server is the cleanest projection — Continue.dev already does this, others slice it out of a multi-server JSON or TOML table).
3. `rules` (a Markdown file with optional YAML frontmatter — covers `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursor/rules/*.mdc`, `.roo/rules/*.md`, `.kilocode/rules/*.md`, `.windsurf/rules/*.md`, `.aiassistant/rules/*.md`, `.junie/AGENTS.md`, Goose `.goosehints`, OpenHands microagents, Amp `AGENTS.md`).
4. `hooks` (single declarative hooks JSON-or-TOML *plus* auxiliary script files, mirroring `skill`'s folder layout — covers Claude, Codex, Cursor, Windsurf, Q Developer, Crush, Gemini CLI).
5. `mode` (Roo/Kilo `customModes` and Cursor `.cursor/modes.json` are the only mass demand; deferrable).

**Highest-leverage adapters to add next** (assuming the customization_types above land):
1. Gemini CLI / Antigravity full surface — already partially present.
2. Cursor — high user reach, but only the file half; SQLite half explicitly excluded.
3. opencode full surface (slash commands, MCP — already-known framework, low risk).
4. Codex CLI extension to hooks, slash commands, MCP — same root, same parser family.
5. Amazon Q Developer — `cli-agents/`, `prompts/`, `mcp.json`, `rules/` already conventionally laid out.

**Highest-risk frameworks for the project**: Plandex (server-side, almost nothing to sync), Zed (LMDB), JetBrains Junie/AI Assistant (XML per-IDE-version layer), Cursor (huge SQLite blob delta between what is and isn't on disk), Cline (same SQLite story), OpenHands (sandboxed container paths that break on host sync).

**On memory specifically**: the term is overloaded across the 20 frameworks (static instruction files, agent-auto-written stores, community memory-bank conventions, tool-backed key-value memory, session history). All file-syncable variants collapse into `rules`; no separate `memory` customization_type is required. See §2.8 for the full breakdown and the recommended `provenance` / `private` field additions on `rules` artifacts.

---

## 2. Cross-cutting findings

The following user-data categories recur across multiple frameworks. Each is analysed for whether it can be modelled as a single canonical schema, what passes into the `per_agentic_tool_only` / `per_agentic_tool_extra` bags, and whether it merits a new `customization_type`.

### 2.1 Slash commands

**Exposed by**: Claude Code, Codex CLI, Cursor, Gemini CLI / Antigravity, opencode, Roo Code, Kilo Code (via workflows), Junie, GitHub Copilot (`*.prompt.md`), Q Developer (`prompts/`), Continue.dev (`prompts/`), Sourcegraph Cody (`cody.json` `commands` map), Plandex (none), Aider (none), Crush (planned, issue #2219), OpenHands (none), Plandex (none), Windsurf (workflows == slash commands), Cline (workflows == slash commands), Zed (extension-only, not file-based — blocked).

**Canonical schema feasibility**: high. The common shape is `{name, description, argument-hint, allowed-tools, model, body}` with body supporting some interpolation grammar (`$ARGUMENTS`, `$1..N`, `!`-shell, `@`-file). Native files are uniformly Markdown with YAML frontmatter — except Gemini CLI which uses TOML and Cody which uses a single JSON dict keyed by command name (so the adapter has to split/join one map across N artifacts).

**`per_agentic_tool_only`**: `allowed-tools` syntax (Claude's `Bash(git:*)` vs opencode's glob `Bash` keys vs Cursor's flat list), `argument-hint` (Claude/Roo/Junie) vs `hint` (Copilot), `agent`/`mode` (opencode/Copilot) — these are tool-specific and should round-trip per tool. **`per_agentic_tool_extra`**: any unknown frontmatter key.

**Recommended new `customization_type`**: **`slash_command`**. `file_layout = AgentFileLayout(extension=".md")` for most frameworks; Gemini CLI is the only outlier and needs `extension=".toml"` plus a different parser branch. Cody is special-cased: it stores all commands in one JSON file (`~/.vscode/cody.json` keyed by command name), so the Cody adapter does map↔file splitting at the I/O layer the same way Plandex `custom-models.json` would.

### 2.2 MCP server configs

**Exposed by**: every framework above except Aider (none) and Plandex (none) and Zed-via-LMDB (well, Zed via `context_servers` in `settings.json` — possible). So 18/20.

**Canonical schema feasibility**: high if the canonical embraces the *transport* discriminator the entire ecosystem has converged on: `stdio` (with `command`, `args`, `env`, `cwd`, `timeout`) vs `http` / `streamable-http` / `streamable_http` (with `url`, `headers`) vs `sse` (`url`, `headers`). Every major framework spells it slightly differently — `transportType` (Cline), `type` (Claude/Q/Cursor/Goose/Junie/Roo), inline `transport = { type = "..." }` table (Codex), `httpUrl` vs `url` (Gemini CLI), `serverUrl` (Windsurf) — but the underlying fields are interchangeable.

**`per_agentic_tool_only`**: `disabled` (most), `autoApprove` / `alwaysAllow` (Cline, Roo, Kilo), `useLegacyMcpJson` (Q), `trust` (Gemini), `enabled` (Goose / Crush). **`per_agentic_tool_extra`**: any nonstandard transport keys (`bearer_token_env_var` Codex; `inputs` Copilot VS Code; `oauth` / `clientId` / `clientSecret` opencode).

**Recommended new `customization_type`**: **`mcp_server`**. Canonical projection: one MCP-server artifact per file even when the framework stores them in a multi-server JSON/TOML map. The adapter is responsible for slice/join. This *is* a new `file_layout` consideration — the read path may have to extract a single server out of a shared `mcp.json` / `mcp_settings.json` / `crush.json[mcp]` / `config.toml[mcp_servers.<name>]`, archive the prior shared file as the side effect, and write the merged file back atomically. That is more invasive than the current `single_file` / `directory_skill` layouts. **Open question (§5)**: do we add a new `file_layout = SharedKeyedMapLayout(file_path, map_key_path, key_field="name")` value, or do we make MCP-server adapters do this transparently behind the existing single-file IO contract?

**Secret handling**: `env`, `headers`, `auth.CLIENT_SECRET`, `api_key`, `bearer_token` *will* contain secrets on disk in many users' real setups. The sync core must redact-by-default, replacing literal tokens with placeholder env-var references (`${env:VAR}`) and noting the original variable name in `per_agentic_tool_only` so it can be unredacted on each host if the user opts in.

### 2.3 Rules / memory / instructions

**Exposed by**: every framework. The de-facto shared file is **`AGENTS.md`** (Codex, Claude via convention, Cursor, Copilot, Junie, opencode, Roo, Kilo, Crush, OpenHands, Amp, Windsurf, Aider via `CONVENTIONS.md` analogue, Goose via `.goosehints` analogue, Plandex none, Zed via `.rules` precedence walk). Pretty much every modern agent honours `AGENTS.md` for project scope and many honour `~/.claude/CLAUDE.md` and `~/.config/opencode/AGENTS.md` for user scope.

**Canonical schema feasibility**: very high — body is free-form Markdown, optional YAML frontmatter with `description`, `globs`, `applyTo`, `alwaysApply`, `trigger`. The only divergence is the *trigger semantics* (`alwaysApply`/`auto-attach`/`agent-requested`/`manual` in Cursor; `trigger: always_on|manual|model_decision|glob` in Windsurf; `trigger_type: always|keyword|manual` in OpenHands; Cursor's derived rule type table is the most expressive, others map down).

**`per_agentic_tool_only`**: trigger semantics field, `globs`, `regex` (Continue.dev). **`per_agentic_tool_extra`**: anything else.

**Recommended new `customization_type`**: **`rules`** (one Markdown file = one rule, single-file file_layout, extension `.md`). The same adapter can read user-scope `~/.<tool>/rules/` directories. **Open question (§5)**: how to handle the `AGENTS.md` shared-file case where Claude reads `~/.claude/CLAUDE.md`, opencode reads `~/.config/opencode/AGENTS.md`, Codex reads `~/.codex/AGENTS.md`, Crush reads project-root `AGENTS.md`, Amp reads `~/.config/amp/AGENTS.md`. Today these are five separate file_layouts pointing at five distinct paths with the same logical content; v0.4 will need either (a) shared-canonical-surface flagging in the adapter so we do not double-archive the same bytes, or (b) explicit per-tool symlink/copy semantics.

### 2.4 Hooks

**Exposed by** (with file-syncable definitions): Claude Code (`settings.json[hooks]`), Codex CLI (`hooks.json` or `config.toml[hooks]`), Cursor (`.cursor/hooks.json`), Windsurf (`hooks.json` user + project, plus `command`/`powershell` split), Q Developer (per-agent in agent JSON), Gemini CLI (`settings.json[hooks]`), Crush (`crush.json[hooks.PreToolUse]` only).

**Canonical schema feasibility**: medium. The event taxonomies differ: Claude has 12 events with matcher discriminators, Codex has 6, Cursor has 6, Windsurf has 12 (including transcript variants), Crush has only `PreToolUse`, Q has only 2 (`agentSpawn`, `userPromptSubmit`). A canonical that takes the union and renders the intersection per tool is workable but lossy when projecting a Claude-authored 12-event hook set onto Crush.

**`per_agentic_tool_only`**: every framework's `timeout` / `timeout_ms` / `timeout_sec` field, `matcher` syntax differences (regex vs literal vs glob), `cache_ttl_seconds` (Q only), `async` / `asyncRewake` (Claude). **`per_agentic_tool_extra`**: unknown event names.

Hooks also reference *executable script files* by `command`. Treating a hook as a folder customization_type — JSON-or-TOML descriptor + auxiliary scripts under `hooks/*.sh|.py|.ps1`, exactly like `skill` treats `SKILL.md` + `scripts/` — is the cleanest projection. The cross-OS `command` vs `powershell` split in Windsurf is the architectural template; Claude/Codex/Cursor adapters would need to learn that pattern.

**Recommended new `customization_type`**: **`hooks`** with `file_layout = HooksFileLayout(descriptor_name="hooks.json", scripts_subdir="scripts")`. Deferrable past v0.5 because of the event-taxonomy projection problem.

### 2.5 Modes / profiles / personas

**Exposed by**: Roo Code (`.roomodes` + global `custom_modes.yaml`), Kilo Code (`.kilocodemodes`, same schema), Cursor (`.cursor/modes.json`, plus SQLite half), Zed (`agent.profiles` inside `settings.json`), Goose (recipes-as-personas — no separate concept), opencode (just an agent attribute, `mode: primary|subagent|all`).

**Canonical schema feasibility**: medium. Roo/Kilo share schema, so two adapters get the same renderer. Cursor's `modes.json` is array-of-modes. Zed nests them inside `settings.json[agent.profiles]`. The interesting field — `groups`/`tools` — is hugely framework-specific (Roo's `read|edit|browser|command|mcp` group taxonomy is unique).

**Recommended new `customization_type`**: **`mode`**, lower priority. Useful for the Roo/Kilo pair and Cursor file half; tightly framework-specific everywhere else.

### 2.6 Settings / profile-style keys

Every framework has a `settings.json` (or `crush.json`, `opencode.json`, `config.toml`, `config.yaml`) with a long-tail set of keys that mix portable values (`model`, `theme`, `outputStyle`) with non-portable ones (`server.port`, `username`, `apiKeyHelper`, paths, OS-keychain references). This is **not** a candidate for a new `customization_type` in v0.4 — these files do not match the "one logical artifact = one file / one folder" abstraction the project depends on. Sync at the *key* level is a different problem (key extraction + merge) that needs either a new `file_layout` for "extract these specific JSON paths" or its own subsystem. Recommend deferring to v0.6+.

### 2.7 Other categories noted

- **Keybindings** (Claude `keybindings.json`, Zed `keymap.json`, opencode `keybinds`): would warrant `keybindings` customization_type only if real demand surfaces. Defer.
- **Themes** (opencode `themes/<name>.json`, Zed `themes/*.json`, Continue.dev color blocks): one-off, single-framework.
- **Plugins** (opencode `plugins/`, Claude `plugins/`): contains executable code; cross-machine sync of arbitrary JS/TS is a different trust model. Defer.
- **Recipes** (Goose only): a Goose-specific super-artifact that bundles instructions + extensions + parameters. Map to `agent` + `mcp_server` + `slash_command` mix; do not introduce a new type.

### 2.8 Memory — a refinement of `rules`, not a new customization_type

"Memory" is the most semantically overloaded term in the 20-framework set. Across the library doc it refers to at least five distinct on-disk shapes, only some of which are file-syncable. The conclusion — anticipated below in the recommendation — is that **no separate `memory` customization_type is needed**: every file-syncable shape collapses into `rules` with a small amount of provenance metadata. The five shapes are catalogued here so the per-framework tables in §3 can be read consistently.

**Shape A. Static user-authored instruction files.** Indistinguishable from rules. `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `CRUSH.md`, `.junie/AGENTS.md`, `~/.config/opencode/AGENTS.md`, Aider's `CONVENTIONS.md`, Goose's `.goosehints`. **Already covered by the proposed `rules` customization_type — no new work.**

**Shape B. Agent-auto-written memory derived from conversations.**
- **Windsurf Cascade Memories**: `~/.codeium/windsurf/memories/` keyed by *workspace-path hash*. Format is opaque and intentionally machine-local. **Blocked** — copying these between machines breaks the hash mapping and corrupts the store.
- **Cursor Memories**: deprecated and removed in 2.1.x (late 2025). Was SQLite-backed even when it existed. **Gone.**
- **Gemini CLI `/memory add`**: appends to `~/.gemini/GEMINI.md`. The append target is plain Markdown — already syncable through the `rules` adapter. **No new work.**
- **JetBrains Junie memory**: persisted under `.junie/` (project) and `~/.junie/` (user). The library doc explicitly flags the user-scope file as "private/per-machine" — exclude from sync by default.

**Shape C. Community memory-bank conventions.** Multi-file Markdown sets that look like memory because the agent reads them on every task.
- **Cline Memory Bank**: `<project>/memory-bank/{projectbrief,productContext,activeContext,systemPatterns,techContext,progress}.md` + an activation rule.
- **Roo / Kilo legacy Memory Bank**: same idea under `.roo/rules/memory-bank/` and `.kilocode/rules/memory-bank/`.

All are project-scope (currently out of v0.4 sync scope) and architecturally identical to N `rules` artifacts. **Covered by `rules`** without modification if anyone lifts them to user-scope.

**Shape D. Tool-backed key-value memory stores.** Files the *agent* writes via an explicit tool call.
- **Goose Memory Extension**: `~/.config/goose/memory/<category>.txt` (global) and `<project>/.goose/memory/<category>.txt` (project). Plain text, one logical record per file, the `memory` builtin extension writes here.
- **Claude Code memory tool** (Agent SDK, late 2025): the `memory` tool exposes a write/read API to a `/memories/*.md` directory the agent owns. Default backend writes plain Markdown to disk.

Both are agent-written, file-syncable Markdown/text keyed by category/filename. On-disk layout is identical to a `rules` directory. The semantic difference (agent-written vs. user-written) does not change the byte-level sync problem and does not justify a new `customization_type`.

**Shape E. Session/conversation history.** Out of scope across the board.
`~/.claude/projects/*`, `~/.gemini/checkpoints/`, `~/.local/share/goose/sessions/sessions.db`, `~/.openhands/conversations/`, Codex `sessions/`, Zed `threads.db`, Cursor `state.vscdb` chat logs, Plandex server-side plans, Cline `globalState` transcripts. Already excluded in the architecture; reaffirmed here.

**Per-framework memory state at a glance:**

| Framework | Memory shape(s) | Syncable as |
|---|---|---|
| Claude Code | A (`CLAUDE.md`) + D (`memory` tool → `/memories/*.md`) | `rules` |
| Codex CLI | A (`AGENTS.md`) | `rules` |
| Gemini CLI / Antigravity | A (`GEMINI.md`) + B (`/memory add` → same file) | `rules` |
| opencode | A (`AGENTS.md`, fallback `~/.claude/CLAUDE.md`) | `rules` (dedupe with Claude) |
| Cursor | B removed | nothing |
| Windsurf | B (workspace-hashed) | **blocked** |
| Cline | C (community Memory Bank) | `rules` (project-only) |
| Roo / Kilo | C (legacy Memory Bank) | `rules` (project-only) |
| Continue.dev | none | — |
| Aider | A (`CONVENTIONS.md`) | `rules` |
| Goose | A (`.goosehints`) + D (Memory Extension) | `rules` |
| OpenHands | A (microagents) | covered under `skill`/`rules` |
| GitHub Copilot | A (`copilot-instructions.md`, `*.instructions.md`) | `rules` |
| Sourcegraph Cody / Amp | A (Amp `AGENTS.md`) | `rules` |
| Zed | A (`.rules`) + LMDB Prompt Library | `rules` (file); LMDB **blocked** |
| Amazon Q Developer | A (`.amazonq/rules/`) + legacy `global_context.json` | `rules` |
| Junie / AI Assistant | A (`.junie/AGENTS.md`) + B (user-scope, exclude) | `rules` for A; B excluded |
| Plandex | none (server-side) | — |
| Crush | A (`AGENTS.md` / `CRUSH.md`) | `rules` |

**Recommendation: do not add a `memory` customization_type.** The `rules` customization_type already covers every file-syncable memory surface. Two refinements address the genuine differences:

1. **`provenance: "user" | "agent"`** field on `rules` artifacts in the canonical. Agent-written memories (Goose's `memory/`, Claude's `/memories/*.md`, Gemini's `/memory add`-appended block of `GEMINI.md`) get `provenance: "agent"` so the deputy / archive layer can treat them differently — conflict resolution still archives prior bytes per US-05, but overwrite policy can be more aggressive because the agent regenerates the content.
2. **`private: true`** flag for files the library doc explicitly marks per-machine (Windsurf hash-keyed memories, Junie user-scope memory, `.goosehints.local`). The sync engine skips these — pure declarative exclusion, no policy in the engine.

Both fields belong in the canonical document under the `rules` artifact, not as new file_layouts.

---

## 3. Per-framework analysis

### 3.1 Aider

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `~/.aider.conf.yml` | partial | M | none | absolute-path values, inline API keys | Flat YAML; not unit-shaped |
| `~/.aider.model.settings.yml` | partial | S | `name` per list entry | low | Per-model overrides, list keyed by `name` |
| `~/.aider.model.metadata.json` | partial | S | dict key (`<model id>`) | low | LiteLLM `model_info` shape |
| `CONVENTIONS.md` (user-scope) | direct (as `rules`) | XS once `rules` lands | path | low | Project-level usually committed; user-global path is what's interesting |
| `.aiderignore` | blocked | — | — | — | Project-only, lives in repo |
| `.env`, `oauth-keys.env` | blocked | — | — | secrets | Never sync |
| Slash commands | blocked | — | — | feature not supported | Aider has no user-defined slash commands |
| Hooks | blocked | — | — | feature not supported | No hook system |
| MCP | blocked | — | — | feature not supported | No MCP client |

**Adapter cost**: very low (S). Aider has the smallest customization surface of any of the 20: at most a `rules` customization_type adapter for the user-global `CONVENTIONS.md` analogue, plus a small "model settings" file that doesn't fit the protocol cleanly. The model settings/metadata files are list-keyed-by-`name` and dict-keyed-by-model-name respectively; they would be `partial` until we introduce a `keyed_map` file_layout. One-shot test feasibility: trivial — the artefacts are inert YAML/JSON, no execution. No architectural change required if we just ship the `rules` adapter and ignore the model files for v0.5.

### 3.2 Amazon Q Developer

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `cli-agents/<name>.json` | new-type-ish (agent-as-JSON) | M | `name` (== filename stem) | medium | Existing `agent` `customization_type` assumes Markdown; needs JSON-agent variant |
| `mcp.json` (`mcpServers`) | new-type | M | map key | high (env secrets, command paths) | Standard MCP schema, transport tagged |
| `prompts/*.md` | new-type (`slash_command`) | S | filename stem | low | Pure Markdown |
| `.amazonq/rules/*.md` | new-type (`rules`) | S | path | low | No global rules dir exists (#3451) |
| Hooks (inside agent JSON) | partial | M | positional | medium | Owned by agent artifact; needs nested handling |
| `settings.json` | partial | M | flat keys | medium | OS keychain entanglement |
| `cli-todo-lists/`, `previous-conversations/` | blocked | — | — | session state | Out of scope |

**Adapter cost (M)**. Q Developer's *agent format is JSON*, which is the first non-Markdown agent format in the project. The `agent` `customization_type`'s current contract assumes Markdown with YAML frontmatter; either we relax `file_layout` to allow an `extension=".json"` AgentFileLayout *and* a parser/renderer that knows the agent schema, or we introduce `agent_json` as a separate kind. The latter is cleaner. Hooks are nested under each agent — that interlocks the `agent` and `hooks` customization_types, which the protocol does not anticipate. Q is otherwise straightforward: paths are stable (`~/.aws/amazonq/`), Windows uses WSL2 so paths follow Linux, no SQLite or LMDB involvement. One-shot tests feasible. Architectural change: add JSON-agent variant.

### 3.3 Claude Code

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| Subagents `~/.claude/agents/*.md` | direct | already done | filename stem | none new | v0.4.1 |
| Skills `~/.claude/skills/<name>/SKILL.md` | direct | already done | folder name | OS-specific shebangs in `scripts/` | v0.4.1 |
| Slash commands `~/.claude/commands/*.md` | new-type | S | path under `commands/` | shell snippets in body | Markdown+YAML, easy |
| Output styles `~/.claude/output-styles/*.md` | new-type (variant of `slash_command`) | S | filename stem | low | Same shape as slash commands |
| Hooks (`settings.json[hooks]`) + `~/.claude/hooks/*.sh` | new-type | L | event+matcher+command tuple | OS-specific scripts | Needs descriptor + scripts pattern |
| MCP `~/.claude.json`, `<proj>/.mcp.json`, `settings.json[mcpServers]` | new-type | M | map key | high (env, paths) | 3 simultaneous file homes |
| CLAUDE.md memory | new-type (`rules`) | S | path | `@`-imports | Shared with opencode via `~/.claude/CLAUDE.md` fallback |
| Settings `~/.claude/settings.json` | partial | L | flat keys | secrets in `apiKeyHelper`, `env` | Key-level extraction; defer |
| Plugins `~/.claude/plugins/` | blocked-ish | — | manifest `name` | executable code | Defer |
| Keybindings `~/.claude/keybindings.json` | blocked-or-defer | — | `(context, keystroke)` | none | Single user-scope only |
| Status line `~/.claude/statusline.sh` | partial | S | path | absolute paths | Auxiliary to `settings.json` |
| Session/runtime under `~/.claude/projects/`, `~/.claude/todos/` | blocked | — | — | runtime state | Exclude |

**Adapter cost** for the *next wave* (`slash_command`, `mcp_server`, `rules`, `hooks` customization_types). Claude Code is the highest-fidelity reference framework — almost every cross-cutting surface in §2 was originally Claude-shaped — so its adapter naturally drives every new `customization_type`. The hardest piece is `~/.claude.json`: it is a single user-global JSON file that mixes user-scope MCP servers with per-project entries *and* session state, which violates the "one artifact, one file" assumption. Recommend reading `~/.claude.json[mcpServers]` and `~/.claude.json[projects.<path>.mcpServers]` only, treating the rest of the file as untouched. One-shot test feasible. Architectural change: the `mcp_server` customization_type's adapter needs a shared-keyed-map file_layout for `~/.claude.json` and `settings.json`.

### 3.4 Cline

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `.clinerules/` rule files | new-type (`rules`) | S | filename | rule-toggle state lives in SQLite | Project-only in scope |
| `~/Documents/Cline/Rules/` global rules | new-type (`rules`) | S | filename | path quirk (#5153) | Linux/WSL `~/Cline/Rules/` fallback |
| `.clinerules/workflows/` | new-type (`slash_command`) | S | filename | low | Same as Roo workflows |
| `cline_mcp_settings.json` global MCP | new-type (`mcp_server`) | M | map key | inside `globalStorage` SQLite-adjacent path | One file, JSON |
| `~/Documents/Cline/Workflows/` | new-type (`slash_command`) | S | filename | low | |
| Custom Instructions textbox | blocked | — | — | SQLite-blob | `state.vscdb` |
| API keys / provider config | blocked | — | — | secrets in SQLite | |
| `cline.*` settings.json keys | partial | M | key | low | Key-level extraction |
| Chat history / checkpoints | blocked | — | — | runtime | |

**Adapter cost (S–M)**. Cline's file-syncable surface is small (`.clinerules/`, `~/Documents/Cline/`, `cline_mcp_settings.json`). The big customization surfaces — "Custom Instructions", model selection, API keys — are all in `state.vscdb`. Document explicitly in the adapter README that ~70% of what Cline users think of as "their setup" is unreachable from disk. One-shot test feasible for the small subset. Architectural change: the `mcp_server` adapter must learn to extract one server out of a multi-server JSON file (same as §2.2).

### 3.5 Continue.dev

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `~/.continue/agents/*.yaml` | direct-ish (agent-as-YAML) | M | filename stem | inlined secrets | Different file format from Markdown agents |
| `~/.continue/models/*.yaml` | new-type (`model_config`?) or blocked | M | `name` | apiKey inline | One model per file; new type if we add it |
| `~/.continue/rules/*.md` | new-type (`rules`) | S | filename stem | globs workstation-specific | Markdown + YAML, easy |
| `~/.continue/prompts/*.prompt` | new-type (`slash_command`) | S | filename stem or `name` | handlebars templating | `.prompt` extension; need to register |
| `~/.continue/mcpServers/*.yaml` | new-type (`mcp_server`) | S | `name` | cwd, absolute command | One server per file — cleanest of any framework |
| `~/.continue/context/*.yaml` | partial | M | `provider+name` | http headers tokens | Continue-specific; per_agentic_tool_only |
| `~/.continue/docs/*.yaml` | partial | S | `name` | low | Defer |
| `~/.continue/data/*.yaml` | blocked-ish | — | — | telemetry destination | Defer |
| `~/.continue/config.yaml` | partial | M | singleton | inline secrets | Big monolithic config |
| `~/.continue/config.ts` | blocked | — | — | arbitrary code | Defer |

**Adapter cost (M)**. Continue.dev has the cleanest one-file-per-artifact directory tree in the whole library: agents, models, rules, prompts, MCP servers, contexts, docs, data all live in `<root>/<subdir>/<slug>.<ext>` with `name` as identity. It is the *reference layout* for what the `mcp_server` and `slash_command` customization_types should look like. The agent file format is full-`config.yaml`-shape YAML (not Markdown), so it needs a YAML-agent variant similar to Q Developer's JSON-agent variant — argues for a deliberate move of `file_layout` from "single Markdown file" to "single file, format-pluggable". One-shot test feasible. Architectural change: support YAML-bodied agents.

### 3.6 Crush

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| Agent Skills `~/.config/crush/skills/<n>/SKILL.md` | direct | S | folder name | shared `~/.claude/skills/` read | Spec-compliant; small adapter |
| `crush.json` mcp block | new-type (`mcp_server`) | M | map key | secrets | Standard schema, three transports |
| `crush.json` PreToolUse hooks | new-type (`hooks`) | M | matcher+command | single event only | Limited compared to Claude |
| `AGENTS.md`/`CRUSH.md` rules | new-type (`rules`) | S | path | shared cross-tool | Project-only |
| `crush.json` providers / models / lsp / options | blocked-or-defer | — | — | secrets, host-bound | Settings, defer |
| User slash commands | blocked | — | — | not implemented | Issue #2219 |
| SQLite session db, logs | blocked | — | — | runtime | |

**Adapter cost (S–M)**. Crush is mostly a single big `crush.json` plus the shared `~/.claude/skills/` and `~/.config/agents/skills/` skill roots. The skills adapter is essentially the same code as Claude's. The shared-skill-root issue is significant: Crush *reads* `~/.claude/skills/`, so syncing skills between Claude Code and Crush could mean syncing them to the same physical directory rather than two — that's a deduplication concern flagged in §5. One-shot test feasible. Architectural change: shared-on-disk-root dedupe rule across adapters.

### 3.7 Cursor

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `.cursor/rules/*.mdc` + `~/.cursor/rules/` | new-type (`rules`) | M | filename stem | `.mdc` not `.md` | Cursor's only file extension trap |
| `.cursor/commands/*.md` + `~/.cursor/commands/` | new-type (`slash_command`) | S | filename stem | none — no frontmatter | Easiest commands of any framework |
| `.cursor/mcp.json` + `~/.cursor/mcp.json` | new-type (`mcp_server`) | M | map key | env secrets, `${env:VAR}` | Standard schema |
| `.cursor/hooks.json` + `~/.cursor/hooks.json` | new-type (`hooks`) | L | event+ordinal | scripts referenced by relative path | 6 events |
| `.cursor/modes.json` | new-type (`mode`) | M | mode object `name` | tool catalog Cursor-specific | Array of modes, not map |
| `.cursor/environment.json`, `Dockerfile` | blocked | — | — | background-agent only | Cloud-coupled |
| `settings.json` `cursor.*` keys | partial | M | key | low | Key extraction |
| User Rules / Team Rules / Memories / Notepads / Docs | blocked | — | — | SQLite / cloud | Single biggest sync hazard |

**Adapter cost (M)**. Cursor's *file* surface is uniformly clean — `.mdc` rules, plain Markdown commands, JSON modes/MCP/hooks — but the *in-app* settings pane writes to `state.vscdb` SQLite. A Cursor adapter that ships today can only deliver maybe 30% of what a Cursor power user uses; the rest is cloud-bound. This is fine to document as a limitation, but it means Cursor is not a high-leverage adapter despite the framework's popularity. One-shot test feasible for the file half. Architectural change: none beyond the four new customization_types.

### 3.8 GitHub Copilot

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `*.instructions.md` user-profile | new-type (`rules`) | S | filename stem | `applyTo` glob | VS Code profile path per OS |
| `*.prompt.md` user-profile | new-type (`slash_command`) | S | `name` | `tools` references | `prompts/` shared with instructions/chatmodes |
| `*.chatmode.md` / `*.agent.md` user-profile | direct-ish (as `agent`) | M | filename stem | dual extension parsing | Already Markdown+YAML |
| `~/.copilot/mcp-config.json` (CLI) | new-type (`mcp_server`) | M | map key | secrets | Standard |
| `~/.copilot/agents/*.agent.md` | direct | S | filename stem | low | CLI-side agents |
| `~/.copilot/skills/<n>/SKILL.md` | direct | XS | folder | low | Spec-compliant skills |
| `~/.copilot/hooks/*` | new-type (`hooks`) | M | filename | scripts | |
| User `mcp.json` (VS Code) | new-type (`mcp_server`) | M | map key | inputs with passwords | |
| `AGENTS.md` | new-type (`rules`) | XS | path | shared | Repo, not user |
| Coding-agent cloud config | blocked | — | — | cloud-only | |
| `settings.json` `github.copilot.*` keys | partial | M | key | low | Key extraction |

**Adapter cost (M)**. Copilot is *two* frameworks bolted together — the VS Code half (rules/prompts/chatmodes under `prompts/`) and the `~/.copilot/` CLI half. The VS Code half is fully file-syncable; the CLI half is even better-shaped (clean `~/.copilot/{agents,skills,hooks}/` tree). The dual `.chatmode.md` + `.agent.md` extension toggle (Oct 2025 rename) is a minor renderer concern. The big risk is `inputs` blocks in `mcp.json` — VS Code prompts the user for passwords and stores them somewhere not in the JSON; do not try to resolve them. One-shot test feasible. Architectural change: agent customization_type accepts two extensions (or two file_layouts for the same kind) — minor.

### 3.9 Goose

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `recipes/*.yaml` | new-type (`recipe`?) | L | filename stem | Jinja2 templating | Bundles instructions+extensions+params |
| `config.yaml[extensions]` | new-type (`mcp_server`) | L | map key | secrets, `env_keys` reference | Six type values; the broadest taxonomy |
| `~/.goosehints` and project hints | new-type (`rules`) | S | path | `.local` per-machine | Free-form text |
| `memory/<category>.txt` | partial | S | filename | low | Memory Extension; informally Markdown |
| `permission.yaml` | blocked-or-defer | — | — | security policy | Careful merge required |
| `secrets.yaml` | blocked | — | — | secrets | Never sync |
| `scheduler/*.yaml` | blocked-or-defer | — | — | cron jobs | Defer |
| Sessions, logs | blocked | — | — | runtime | |

**Adapter cost (L)**. Goose's *recipe* is the project's first super-artifact: it embeds instructions, extensions, sub-recipes, response schemas, retry policy, settings — basically a Goose-flavored agent + MCP-server-list + slash-command rolled into one. Trying to project a recipe onto Claude Code (which has no equivalent) would require splitting it into an `agent` + N `mcp_server` artifacts and dropping the rest into `per_agentic_tool_only`. That projection is lossy. The cleaner path is to model recipes as a Goose-specific super-artifact that *doesn't* sync to other frameworks — but that violates the project's universalist premise. Recommend deferring Goose. The `extensions` block is the canonical example of why `mcp_server` needs to be a real customization_type. Architectural change: significant — sub-recipes (recipe referencing recipe) violate the canonical document model.

### 3.10 Google Gemini CLI & Antigravity

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `agents/<name>.md` (Gemini CLI) | direct (`agent`) | XS | filename stem | none | Already supported v0.4 for Antigravity-ish use |
| `antigravity/skills/<n>/SKILL.md` | direct (`skill`) | already done | folder name | none | v0.4 |
| `commands/<name>.toml` | new-type (`slash_command` TOML variant) | M | filename + namespace | TOML extension | Gemini CLI is the only TOML slash-command framework |
| MCP servers under `settings.json[mcpServers]` | new-type (`mcp_server`) | M | map key | secrets | `httpUrl` vs `url`; `trust` field |
| Hooks under `settings.json[hooks]` | new-type (`hooks`) | M | matcher+command | low | Standard event taxonomy |
| `GEMINI.md` user-global | new-type (`rules`) | S | path | `@`-imports | Shared with `CLAUDE.md` convention |
| Extensions `extensions/<n>/` | partial | L | `name` | bundles many things | Defer |
| `settings.json` itself | partial | M | flat keys | low | Defer (categorised post-Sept-2025) |
| `oauth_creds.json`, `installation_id`, `.env` | blocked | — | — | auth | Never sync |

**Adapter cost (M)**. Gemini CLI's slash commands are TOML, which is the only framework in the 20 that uses TOML for slash commands; one new parser path. Skills are already supported. Agents are Markdown+YAML, identical in shape to Claude Code. The bigger architectural question is whether `~/.gemini/antigravity/skills/` should be shared with `~/.claude/skills/` (as Crush does); per the library, Gemini CLI reads `~/.gemini/antigravity/skills/` but not Claude's directory — so no dedup risk here. One-shot test feasible. Architectural change: TOML slash command parser.

### 3.11 JetBrains Junie & AI Assistant

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `.junie/AGENTS.md` + project `AGENTS.md` | new-type (`rules`) | S | path | shared | Project-only mostly |
| `.junie/commands/*.md` + `~/.junie/commands/` | new-type (`slash_command`) | S | filename stem | low | Markdown+YAML |
| `.junie/skills/<n>/` + `~/.junie/skills/` | direct (`skill`) | S | folder name | low | Anthropic-shaped |
| `.junie/agents/<n>.md` | direct (`agent`) | S | filename stem | low | Same shape as Claude |
| `.junie/mcp/mcp.json` + `~/.junie/mcp/` | new-type (`mcp_server`) | M | map key | secrets | Standard schema |
| `~/.junie/allowlist.json` | blocked-or-defer | — | — | security policy | Careful merge |
| `~/.junie/config.json` | partial | M | flat keys | low | Settings |
| `.aiassistant/rules/*.md` | new-type (`rules`) | S | filename | low | AI Assistant side |
| AI Assistant Prompt Library | blocked | — | — | XML, per-IDE-version | Brittle |
| AI Assistant MCP (XML) | blocked | — | — | XML, per-IDE-version | Brittle |
| `options/llm.xml`, `junie.xml`, etc. | blocked | — | — | XML+JWT | Never sync |

**Adapter cost (M for Junie alone; AI Assistant XML half is blocked)**. The Junie file conventions are remarkably aligned with the Claude-Code-shaped layout: `.junie/commands/`, `.junie/skills/`, `.junie/agents/`, `.junie/mcp/mcp.json` — essentially the same adapter as Claude with path substitution. The user-scope `~/.junie/` is the interesting half because JetBrains has *separate* user-scope skill/command/MCP roots, unlike most VS Code extension forks. AI Assistant's Prompt Library lives in XML per-IDE-version directories and is documented in the library as "high sync risk"; treat as out of scope for now. The user-scope `allowlist.json` is a security boundary — recommend not syncing it automatically. One-shot test feasible. Architectural change: none beyond the four new customization_types.

### 3.12 Kilo Code

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `.kilocodemodes` / `custom_modes.yaml` | new-type (`mode`) | M | `slug` | low | Identical schema to Roo |
| `.kilocode/rules/`, `~/.kilocode/rules/` | new-type (`rules`) | S | path | low | Identical to Roo |
| `.kilocode/workflows/` | new-type (`slash_command`) | S | filename | shell | Same as Roo |
| `.kilocode/mcp.json` + global `mcp_settings.json` | new-type (`mcp_server`) | M | map key | secrets | Same as Roo |
| Skills `.kilocode/skills/<n>/` (newer) | direct (`skill`) | XS | folder | low | Emerging SKILL.md |
| `.kilocodeignore` | blocked | — | — | per-project | |
| `kilo.jsonc` (new CLI) | partial | M | flat keys | low | Unstable; watch |
| Settings `kilo-code.*` | partial | M | key | secrets | Key extraction |

**Adapter cost (S)** — *if and only if* the Roo Code adapter exists. The library doc is explicit: take the Roo adapter, rename `roo` → `kilocode`, `.roo` → `.kilocode`, point globalStorage at `kilocode.kilo-code`. The schemas are byte-for-byte identical. This is the cleanest reuse opportunity in the 20-framework set: ship Roo first, ship Kilo as a copy with a constants table. One-shot test trivial. Architectural change: none.

### 3.13 OpenAI Codex CLI

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `agents/*.toml` | direct (`agent` TOML variant) | already done | `name` | low | v0.4.1 |
| `skills/<n>/SKILL.md` | direct (`skill`) | already done | folder | none | v0.4.1 |
| `prompts/*.md` slash commands | new-type (`slash_command`) | S | filename stem | low | Marked deprecated in favor of skills |
| `[mcp_servers.<name>]` in config.toml | new-type (`mcp_server`) | M | TOML table key | env secrets | Older inline syntax also supported |
| `hooks.json` or `[hooks]` in config.toml | new-type (`hooks`) | M | event+matcher | scripts | Same shape as Claude, six events |
| `AGENTS.md` (user + project) | new-type (`rules`) | S | path | low | Markdown, no frontmatter |
| `config.toml` itself | partial | L | flat keys + tables | secrets in `model_providers[].env_key` | Settings, defer |
| `auth.json` | blocked | — | — | credentials | Never sync |
| `history.jsonl`, `sessions/`, `log/` | blocked | — | — | runtime | |
| `skills/.system/` | blocked | — | — | OpenAI-shipped | Exclude from sync |

**Adapter cost (S–M for next wave)**. Codex CLI is the second framework with a TOML-based agent format (Continue.dev is YAML, Q Developer is JSON, everyone else is Markdown). The `agents/*.toml` adapter already exists in v0.4.1. Adding slash commands, MCP servers, hooks, and rules is mostly a paths-and-formats exercise — all of these are well-defined in the official config schema (`config.schema.json`). The interesting wrinkle is MCP-server extraction from a TOML config: each server is `[mcp_servers.<name>]` which is a nested table, not a JSON map; the adapter's "extract one server from a shared file" path needs a TOML-aware variant. One-shot test feasible. Architectural change: extend the `mcp_server` shared-file slicer to handle TOML tables.

### 3.14 opencode (SST)

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `agents/<n>.md` user + project | direct (`agent`) | already done | filename stem | reserved names (build/plan/...) | v0.4.1 |
| `skills/<n>/SKILL.md` user + project | direct (`skill`) | already done | folder | shared with `~/.claude/skills/` | v0.4.1 |
| `commands/<n>.md` | new-type (`slash_command`) | S | filename stem | `!`-shell | Standard |
| `mcp` block in opencode.json | new-type (`mcp_server`) | M | map key | secrets | Two transports (`local`/`remote`) — different field names from rest |
| `AGENTS.md` user-global | new-type (`rules`) | S | path | shared with `~/.claude/CLAUDE.md` fallback | |
| `opencode.json` itself | partial | L | flat keys | secrets, host-bound | Defer |
| `themes/<n>.json` | blocked-or-defer | — | `name` | low | Cosmetic |
| `plugins/*.{js,ts}` | blocked | — | — | executable | |
| Auth, sessions | blocked | — | — | runtime | |

**Adapter cost (S–M)**. opencode's filesystem layout is the closest mirror to Claude Code's of any framework in the 20: `agents/`, `skills/`, `commands/` under one root, JSON `opencode.json` for everything else. The MCP block uses `type: "local"` / `type: "remote"` (different from everyone else's `stdio` / `http` / `sse` / `streamable-http`), so the canonical schema needs to absorb that as another transport-naming dialect. Reserved built-in agent names (`build`, `plan`, `general`, `explore`, `scout`) are notable — the sync core should refuse to create or rename onto these. One-shot test feasible. Architectural change: transport-name dialect handling in `mcp_server`.

### 3.15 OpenHands

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `.openhands/microagents/*.md` / `.openhands/skills/*.md` (V0+V1) | direct-ish (`skill` or `rules`) | M | `name` or filename | V0/V1 frontmatter drift | Project-only; no user-scope yet |
| `.agents/skills/<n>/SKILL.md` (V1) | direct (`skill`) | XS | folder | low | Spec-compliant |
| `AGENTS.md` | new-type (`rules`) | XS | path | low | Project-only |
| `config.toml[mcp]` | new-type (`mcp_server`) | M | `name` (stdio) or `url` (http/sse) | container-vs-host paths | Three transports with different identity fields |
| `settings.json` | partial | L | flat keys | many secrets | Defer |
| Custom slash commands | blocked | — | — | feature absent | Issue #343 |
| Hooks | blocked | — | — | feature absent | |
| `conversations/`, `sessions/`, `events/` | blocked | — | — | runtime | |
| `secrets.json` | blocked | — | — | secrets | |

**Adapter cost (M)**. OpenHands runs the agent inside a Docker sandbox; many on-disk paths in `settings.json` (`workspace_base`, `volumes`, `sandbox.base_container_image`) refer to container filesystem locations, not host. Stdio MCP servers' `command`/`args` resolve inside the container, so any host-absolute path the user writes in is wrong from the agent's point of view. This is unique among the 20 and means a Windsurf-style `command` vs `powershell` split is *not* the right abstraction here — the issue is host vs container, not Linux vs Windows. Recommend deferring beyond the simple cases. There is no host-scope microagents directory (#6404). One-shot test possible for the V1 SKILL.md path. Architectural change: defer non-skill OpenHands work to v0.6+.

### 3.16 Plandex

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `custom-models.json` | partial | M | `providers[].name` / `models[].modelId` / `modelPacks[].name` | `<account-id>` path varies | Single file with three keyed arrays |
| `auth.json` | blocked | — | — | token + per-machine host | Never sync |
| `.plandex-v2/` project pointer | blocked | — | — | per-clone server pointer | |
| `.plandexignore` | blocked | — | — | per-project | |
| MCP | blocked | — | — | feature absent | |
| Plans, conversation, autonomy config | blocked | — | — | server-side | |

**Adapter cost (S, but low value)**. Plandex stores almost everything on its server. The only meaningful local artifact is `custom-models.json`, and the path includes a per-machine `<account-id>` segment that must be rewritten on import. The file has three logical artifact types (provider, model, modelPack) keyed by `name`/`modelId`/`name` respectively — these would need a *new* customization_type or three (`model_provider`, `model`, `model_pack`) to do well. Recommendation: **deprioritise Plandex** until a "model registry" customization_type is justified by other frameworks demanding it (Aider's model metadata, Continue.dev's `models/` dir, parts of Goose). One-shot test trivial; no architectural change required if we ship this as a passthrough single-file artifact.

### 3.17 Roo Code

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| `.roomodes` + global `custom_modes.yaml` | new-type (`mode`) | M | `slug` | YAML anchors/comments | Mode + `groups` schema |
| `.roo/rules/`, `~/.roo/rules/` (+ mode-specific) | new-type (`rules`) | M | path | ordering by filename | Mode-specific subdir variant |
| `.roo/commands/`, `~/.roo/commands/` | new-type (`slash_command`) | S | filename stem | low | Standard |
| `.roo/skills/`, `~/.roo/skills/` (+ mode-specific) | direct (`skill`) | S | folder | symlinks supported | |
| `.roo/mcp.json` + global `mcp_settings.json` | new-type (`mcp_server`) | M | map key | secrets | |
| `roo-cline.*` settings.json keys | partial | M | key | secrets | Key extraction |
| `.rooignore`, `AGENTS.md` (project) | blocked | — | — | per-project | |
| `state.vscdb` SecretStorage | blocked | — | — | secrets | |

**Adapter cost (M)**. Roo Code is the canonical "mode + rule + workflow + skill + MCP" framework — it exposes every category in §2 except hooks. A complete Roo adapter is the most expressive test of the new customization_types. Identity fields are well-defined (`slug` for modes, filename for rules/commands, folder for skills, map key for MCP). The mode-specific rule subdirectory pattern (`.roo/rules-<modeSlug>/`) is the only schema feature that strains the current model — a rule has a `mode` parent, which means the canonical needs either a `mode` reference field on rules or a separate "rule-of-mode" file_layout. One-shot test feasible. Architectural change: rule-of-mode coupling — recommend deferring by treating mode-specific rules as `per_agentic_tool_only`.

### 3.18 Sourcegraph Cody (and Amp)

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| Cody `~/.vscode/cody.json` `commands` map | new-type (`slash_command`) | M | object key | `context.command` shell on import | Map-keyed; one file holds N commands |
| Cody Prompt Library | blocked | — | — | server-side | |
| Cody Rules | blocked | — | — | single string setting | `cody.chat.preInstruction` |
| Cody MCP via OpenCtx | partial | M | provider URL key | absolute file:// URIs, API keys in args | |
| `cody.*` settings.json keys | partial | M | key | secrets | Key extraction |
| Cody Context Filters | blocked | — | — | enterprise site config | |
| Amp `~/.config/amp/settings.json` | partial | M | `amp.*` keys | secrets | |
| Amp `amp.mcpServers` | new-type (`mcp_server`) | M | map key | secrets | Inside settings.json |
| Amp `AGENTS.md` user-global | new-type (`rules`) | S | path | shared cross-tool | |
| Amp toolbox scripts | partial | M | filename | executable | Defer |
| Amp threads, telemetry | blocked | — | — | runtime | |

**Adapter cost (M for each — two separate frameworks)**. Cody's `cody.json` is identical-in-shape to Plandex's `custom-models.json`: one file with N artifacts keyed by name, so the same shared-keyed-map file_layout helps. The big issue is `context.command` — Cody commands can include a shell command that runs at command-invocation time to gather context; importing such a command from another machine is essentially trusting executable code, so the adapter should surface it for explicit review. Amp is mostly the same shape as opencode but uses the `AGENTS.md` convention more aggressively. One-shot test feasible. Architectural change: shared-keyed-map file_layout (same one needed for Plandex and the multi-server MCP files).

### 3.19 Windsurf

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| Global rules `~/.codeium/windsurf/memories/global_rules.md` | new-type (`rules`) | S | singleton | 12k char budget | One file |
| `.windsurf/rules/*.md` | new-type (`rules`) | S | filename | budget | Project-only |
| `.windsurf/workflows/*.md` (slash commands) | new-type (`slash_command`) | S | `name` | low | Project-only |
| `.windsurf/skills/<n>/SKILL.md` + user-scope | direct (`skill`) | S | folder | low | |
| `mcp_config.json` user-scope | new-type (`mcp_server`) | M | map key | env secrets | `serverUrl` vs `url` |
| `hooks.json` user + project | new-type (`hooks`) | M | event+ordinal | `command`/`powershell` split | Best cross-OS hook model |
| `memories/` workspace-hashed | blocked | — | — | path-bound | Non-syncable |
| Settings (`windsurf.*`, `cascade.*`) | partial | M | key | secrets, version-coupled | Defer |
| Conversation history | blocked | — | — | opaque | |

**Adapter cost (M)**. Windsurf's hooks support is the best-shaped of any framework — it ships separate `command` (POSIX) and `powershell` (Windows) fields on every hook entry, which is exactly the model the canonical `hooks` customization_type should adopt. The character-budget rule (global + workspace = 12000 chars) is a sync concern: if we sync 20 rules to Windsurf they may collectively overflow. Recommend not enforcing the budget in agents_sync — let Windsurf truncate. One-shot test feasible. Architectural change: cross-OS command pair pattern in `hooks`.

### 3.20 Zed

| Feature | Compatibility | Effort | Identity | Risk | Notes |
|---|---|---|---|---|---|
| Agent profiles in `settings.json[agent.profiles]` | new-type (`mode`) | M | profile ID | tool names Zed-specific | Nested inside settings.json |
| `context_servers` in `settings.json` | new-type (`mcp_server`) | M | server ID key | secrets | Inside settings.json |
| Prompt Library `prompts-library-db.0.mdb` | blocked | — | UUID | LMDB binary | Page-layout / arch-bound; sync corrupts |
| `.rules` project file | new-type (`rules`) | S | path | precedence walk over many alias names | Cross-tool aliasing |
| Slash commands (extension-only) | blocked | — | — | Wasm binaries | Not file-syncable |
| `agent_servers` | partial | M | key | env, command | ACP-external agent registry |
| `language_models` | partial | M | provider key | API keys in keyring | Settings |
| `keymap.json` | blocked-or-defer | — | — | low | Keybindings |

**Adapter cost (M, but headline feature is blocked)**. Zed's central user-authored AI surface — the Rules Library — is LMDB. The library doc explicitly warns that byte-for-byte sync corrupts it (page layout depends on architecture and OS page size); the only safe path is exporting to Markdown via the third-party `rubiojr/zed-prompts` tool and round-tripping through that. Recommend explicitly *not* attempting to read or write the LMDB file. What remains is `settings.json` extraction for `agent.profiles`, `context_servers`, `agent_servers`, plus the project-level `.rules` Markdown. Zed is a low-leverage target; the file half is small and the LMDB half is unreachable. One-shot test feasible only for the file half. Architectural change: shared-keyed-map file_layout extraction from `settings.json`.

---

## 4. Recommended sequencing

Ordered by *new architectural surface introduced per framework*, then *user-reach proxies*, then *risk*. Frameworks marked **no protocol change** can ship before the new customization_types land; **needs new type** waits on the corresponding customization_type.

1. **Kilo Code (no protocol change for skill subset; needs `mode`, `rules`, `slash_command`, `mcp_server` for the rest).** Cheapest possible adapter: literally a constants rename of the Roo adapter. Pair with Roo.
2. **Roo Code (needs new types).** Highest expressivity per LOC: forces us to design `mode`, `rules`, `slash_command`, `mcp_server` against a real four-way schema. Once Roo works, Kilo Code is a copy. The combination dominates the VS Code-extension agentic-tool segment.
3. **Gemini CLI / Antigravity full adapter (needs `slash_command` TOML, `mcp_server`, `rules`).** Already partially shipped (Antigravity skills). Adds TOML-slash-command parser as the only new format wrinkle. Google reach proxy is significant — Antigravity is shipping.
4. **OpenAI Codex CLI extension (needs `slash_command`, `mcp_server`, `hooks`, `rules`).** Already has agent + skill v0.4.1 support. Adding the remaining four surfaces is a paths-and-parsers exercise against a well-documented config schema. Reach: OpenAI is the highest-volume code-CLI vendor.
5. **GitHub Copilot CLI (needs all four).** `~/.copilot/{agents,skills,hooks}/` is the cleanest CLI-side layout of any framework. Reach: highest of all 20 frameworks via the VS Code half. The repo-side surface lives in `.github/` and is already user-committed, so user-scope is what matters.
6. **Cursor file half (needs all four; explicit non-coverage note for the SQLite half).** Reach is huge but coverage is partial (~30%); document the gap. The Cursor adapter is mostly straight file IO once the new customization_types exist.
7. **opencode extension (needs `slash_command`, `mcp_server`, `rules`).** Already has agent + skill. Completing it closes the parity with Claude Code. The MCP transport-name dialect (`local`/`remote`) is a small renderer addition.
8. **Amazon Q Developer (needs `slash_command`, `mcp_server`, `rules`, plus JSON-agent variant).** Useful test of the JSON-agent kind. Reach via AWS users is meaningful.

Frameworks **not** in the next-8 list and the reason:

- **Aider** — surface too small to be worth a dedicated adapter beyond a one-off rules adapter.
- **Cline** — most of the customization surface is in `state.vscdb`; effort vs reach is poor.
- **Continue.dev** — clean layout but small user share relative to the above; revisit when `mcp_server` / `slash_command` adapters need a second reference implementation.
- **Crush** — small surface; close cousin of Claude Code via the shared `~/.claude/skills/` read path. Defer until the shared-on-disk-root dedup question is resolved.
- **Junie / AI Assistant** — Junie file half is direct fit but JetBrains user share is narrower; AI Assistant XML half is blocked. Defer.
- **Goose** — recipe-as-super-artifact violates the canonical model; defer until we decide whether `recipe` is its own customization_type.
- **OpenHands** — sandboxed-container path semantics break cross-host sync of MCP commands. Defer.
- **Plandex** — almost everything is server-side; not worth a dedicated adapter.
- **Cody / Amp** — Cody is file-thin (`cody.json` + settings keys), Amp duplicates opencode shape. Treat as v0.6+ work after the cross-cutting customization_types are settled.
- **Windsurf** — defer; once `hooks` lands, Windsurf is one of the better-shaped targets, but it's behind the user-share heavyweights (Cursor, Copilot, Codex, Claude).
- **Zed** — LMDB blocks the headline feature; the remainder is too small.

---

## 5. Open architectural questions

The analysis surfaced eight architectural questions the project must answer before adopting most of the recommendations above. None are blockers for v0.5; each is a fork in the road.

**Q1. Should `mcp_server` use a new `file_layout` for shared keyed maps, or hide the slicing inside each adapter?**
Most frameworks store all MCP servers in a single multi-server file (`mcp.json`, `mcp_settings.json`, `crush.json[mcp]`, `config.toml[mcp_servers.<name>]`, `~/.cursor/mcp.json`, `~/.continue/mcpServers/*.yaml` is the lone exception). Today's `AgentFileLayout` / `SkillFileLayout` both assume one artifact = one path. Two options:
- **(a) Add `SharedKeyedMapLayout(shared_path, key_field)`** to `agentic_tool_spec.py`, with the sync core aware that "writing one artifact" entails "read shared file, mutate one key, atomic-write back, archive old shared file" — and that concurrent edits to two MCP servers in different polls of the same shared file are race-prone (the existing self-healing-poll story should handle it, but the archive granularity needs to change from per-server to per-shared-file).
- **(b) Have each adapter pretend it owns N single files but transparently slice/join the shared file at read/write time.** The adapter does its own archiving of the shared file. This keeps the protocol untouched but pushes complexity per-framework.

Option (a) is the principled choice; (b) is YAGNI-cleaner today.

**Q2. How to handle MCP transport-name dialects (`stdio` / `http` / `sse` / `streamable-http` / `streamable_http` / `streamableHttp` / `local` / `remote` / `shttp`)?**
The canonical needs one set of transport names. Recommendation: pick the Claude/Cursor/Q-aligned spelling (`stdio`, `http`, `sse`, `streamable-http`) for the canonical and let each adapter map to/from. Stash the original spelling in `per_agentic_tool_extra` for round-trip stability.

**Q3. How to model dual-scope (user vs project) in the canonical when only user-level is in scope?**
The project description explicitly says project-scope is out of scope for now. Every modern framework has parallel user-scope and project-scope trees. Today the protocol implicitly assumes one root per framework per customization_type. When we add Roo's mode-specific rules (`.roo/rules-<mode>/`), Kilo's same, and Junie's `~/.junie/skills/` user-scope mirror, we need to decide whether to (a) treat user-scope and project-scope as two different adapter slots, (b) keep project-scope formally out of scope but let adapters read user-scope-only, or (c) extend the protocol to encode scope on each customization_artifact. (b) is consistent with the current scope statement; recommend keeping (b) until project-scope is explicitly added to the project description.

**Q4. How to dedupe shared on-disk surfaces (e.g. `~/.claude/skills/` read by Claude Code, opencode, Crush, and Copilot CLI)?**
Today each adapter has its own root. If Claude and opencode both target `~/.claude/skills/<formatter>/`, the sync core will archive and rewrite the same physical bytes twice per poll, and the canonical will record two `agentic_tools` entries for what is really one disk artifact. Options:
- Declare the framework that "owns" the physical path (Claude Code owns `~/.claude/skills/`), and have other adapters mark their read of that path as "alias" — they observe but never write.
- Add a `shared_with` field on `AgenticToolSpec` that the discovery layer uses to deduplicate.
- Use symlinks during install and have only one adapter touch the physical location.

The first is least invasive and matches existing conventions ("opencode reads `~/.claude/skills/` as a compatibility shim, not a primary surface").

**Q5. Should "hook scripts referenced by JSON" be modelled as auxiliary files in a `hooks` customization_type, mirroring skills' aux files?**
Claude Code's hooks descriptor references `~/.claude/hooks/load-context.sh` etc.; Cursor's hooks references `./.cursor/hooks/audit.sh`; Codex's references `.codex/hooks/pre_tool_use.py`; Windsurf splits `command` (POSIX) and `powershell` (Windows). The natural model is `HooksFileLayout(descriptor_name="hooks.json", scripts_subdir="hooks")` with auxiliary files propagated verbatim, exactly as `SkillFileLayout` works. Cross-OS commands need either two parallel script files (Windsurf model) or a single executable plus a shebang that works on both.

**Q6. Does `settings.json` key-level extraction need a new `file_layout`?**
A surprising number of frameworks treat their settings file as a *namespace* (`cline.*`, `cursor.*`, `kilo-code.*`, `roo-cline.*`, `github.copilot.*`, `windsurf.*`, `amp.*`) — many frameworks coexist in the same `~/.config/Code/User/settings.json` and the agents_sync adapter must only touch its namespace's keys. Today's `single_file` layout assumes the file is owned by one framework. Either we add `JSONNamespaceLayout(file_path, namespace_prefix)` or we declare key-level extraction out of scope and only sync standalone JSON/YAML/TOML files. Recommend the latter for v0.5; revisit when a framework's *only* useful surface is its `settings.json` keys.

**Q7. How should the project handle secret redaction in MCP server `env` / `headers` / `auth`?**
Real-world `mcp.json`/`crush.json`/`config.toml` files routinely contain literal API keys, GitHub PATs, Anthropic keys. Syncing them as-is is a security hazard; not syncing them at all loses information. Three positions:
- **Strict (recommended)**: detect literal high-entropy strings in `env` values, `headers["Authorization"]`, `bearer_token`, `apiKey`, `api_key`, `oauth.CLIENT_SECRET` and refuse to sync the artifact with a structured warning per US-03 AC-10. The user is expected to use `${env:VAR}` indirection.
- **Permissive**: sync as-is, document the risk.
- **Redacting**: replace literals with a placeholder env-var name, store the original variable name and the redaction in `per_agentic_tool_only` so the user can re-resolve manually.

This is a policy question, not just an architecture one, and the user stories don't currently address it.

**Q8. Where do JSON-bodied agents and YAML-bodied agents fit?**
Q Developer (`cli-agents/*.json`) and Continue.dev (`agents/*.yaml`) are full-fidelity agent definitions in formats other than Markdown+YAML. The current `agent` customization_type's contract is implicitly Markdown+YAML-frontmatter. Two paths:
- Generalize `AgentFileLayout` to carry `format: "markdown_yaml" | "json" | "yaml" | "toml"` and have each adapter implement only the parsers it needs.
- Treat each format as its own customization_type (`agent_md`, `agent_json`, `agent_yaml`, `agent_toml`). This explodes the customization_type set and prevents an agent authored in Claude Code from syncing to Continue.dev *as an agent*; they'd be different types.

The first is the right answer if cross-format sync is in scope (e.g. translate a Claude `code-reviewer.md` agent into a Continue.dev `code-reviewer.yaml`). The protocol's `parse`/`render` already handles that — what's missing is the file_layout's freedom over format. Recommend generalising `AgentFileLayout` rather than adding format-specific customization_types.

**Q9. How should agent-written vs. user-written `rules` artifacts be distinguished, and where does the `private` flag for per-machine files live?**
§2.8 argues that the five shapes of "memory" all collapse onto the `rules` customization_type once the canonical carries two extra fields: `provenance: "user" | "agent"` and `private: true|false`. Two design choices to settle:
- **Where the fields live**: on every `rules` canonical document directly, or in `per_agentic_tool_only` so they round-trip only on tools that recognise them? The first is correct because both fields are *engine-visible policy* (the engine decides differently based on them), not per-tool passthrough.
- **Who sets `provenance: "agent"`**: the adapter at parse time, based on the source path (e.g. anything under `~/.config/goose/memory/`, `~/.gemini/GEMINI.md`-after-`/memory add`-marker, Claude's `/memories/*.md`)? Or an explicit declaration in `AgenticToolSpec` mapping a source directory to a provenance? The latter is cleaner and audit-friendly.
- **What policy hangs off `provenance: "agent"`**: relaxed overwrite (the agent will regenerate), still archive prior bytes per US-05, possibly a lower priority in last-mtime-wins conflict resolution (a user edit on host A beats an agent regeneration on host B at the same minute). The exact policy should be specified in a follow-up to US-06.
- **What `private: true` does**: the engine skips the artifact end-to-end — no archive write, no canonical entry, no propagation. Pure declarative exclusion. Sources: Windsurf hash-keyed memories, Junie user-scope memory, `.goosehints.local`, anything an adapter marks `private` based on the source path.
