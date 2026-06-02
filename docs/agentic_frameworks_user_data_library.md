# Agentic Frameworks — User-Data Library

A field guide to where 20 popular agentic frameworks store **user-authored** customization on disk: agents/subagents, skills, slash commands, MCP servers, hooks, memory/rules, settings, and adjacent surfaces. Compiled for the `agents_sync` project to inform which paths, formats, and identity fields a sync adapter must handle for each tool, and which surfaces are intentionally cloud-only or per-machine state and therefore out of sync scope.

Scope per framework:

- exact paths (Linux / macOS / Windows) for every user-authored artifact;
- file format (Markdown + YAML frontmatter, JSON, JSONC, TOML, YAML, XML);
- full documented schema and a minimal example;
- the identity field that distinguishes one artifact from another;
- whether the artifact is scoped to the user, the project, or both;
- sync risks (secrets, absolute paths, host-specific binaries, cloud-only state, schema drift).

Out of scope across all entries: session transcripts, runtime caches, auth tokens, OS-keychain entries. Where a feature is cloud-only (admin policy, account-stored settings panels, hosted prompt libraries) it is called out explicitly so a sync adapter does not pretend it can move what the vendor does not expose on disk.

## Table of contents

1. [Aider](#aider)
2. [Amazon Q Developer](#amazon-q-developer)
3. [Claude Code](#claude-code)
4. [Cline](#cline)
5. [Continue.dev](#continuedev)
6. [Crush (Charmbracelet)](#crush-charmbracelet)
7. [Cursor](#cursor)
8. [GitHub Copilot](#github-copilot)
9. [Goose (Block)](#goose-block)
10. [Google Gemini CLI & Antigravity](#google-gemini-cli--antigravity)
11. [JetBrains Junie & AI Assistant](#jetbrains-junie--ai-assistant)
12. [Kilo Code](#kilo-code)
13. [OpenAI Codex CLI](#openai-codex-cli)
14. [opencode (SST)](#opencode-sst)
15. [OpenHands (All Hands AI)](#openhands-all-hands-ai)
16. [Plandex](#plandex)
17. [Roo Code](#roo-code)
18. [Sourcegraph Cody (and Amp)](#sourcegraph-cody-and-amp)
19. [Windsurf (Codeium)](#windsurf-codeium)
20. [Zed](#zed)

---

## Aider

Aider (`aider.chat`, `github.com/Aider-AI/aider`) is a terminal AI pair programmer that runs against a Git working tree. It is unusual among agentic tools in that it has **no plugin system, no MCP client, no hook system, and no user-defined slash command system**. User customization is concentrated in a small set of dotfiles that live in either the user's home directory or the project's Git root. The surface area is small, but because every customization file uses the same `~/.aider.*` vs `<repo>/.aider.*` duality, the sync rules must be applied per-file rather than as a single directory tree.

### Coding conventions — `CONVENTIONS.md`

No fixed path; the convention is to put a `CONVENTIONS.md` (or any Markdown file) at the project root and load it as a read-only context file.

- **Load mechanism**: `aider --read CONVENTIONS.md` on the CLI, or `/read CONVENTIONS.md` in-chat. Read-only files are eligible for prompt caching.
- **Auto-load**: in `.aider.conf.yml`, set the `read:` key — single value (`read: CONVENTIONS.md`) or list. A user-level `~/.aider.conf.yml` can auto-load a global conventions file; a `<repo>/.aider.conf.yml` can pin a project-specific one.
- **Format**: free-form Markdown, no schema.
- **Path per OS**: `<repo>/CONVENTIONS.md` on Linux/macOS/Windows.
- **Identity**: none — opaque text to Aider.
- **Scope**: usually committed to the repo (project scope); personal global versions live under `~/` and are referenced by absolute path.
- **Sync risk**: project-committed conventions are already version-controlled; only a user's personal global conventions file is interesting to a sync tool.

### Config — `.aider.conf.yml`

- **Paths** (search order, last wins): `~/.aider.conf.yml` → `<git-root>/.aider.conf.yml` → `<cwd>/.aider.conf.yml`. Same filename on every OS. Extension must be `.yml`, not `.yaml` (issue #3974). `--config <path>` overrides discovery.
- **Format**: YAML. Every CLI flag (`--foo-bar`) maps to a YAML key (`foo-bar:`). Lists accept block or flow form.

Representative schema (subset of ~100 keys):

```yaml
# Main model
model: claude-3-5-sonnet-20241022
weak-model: gpt-4o-mini
editor-model: null
edit-format: diff             # whole | diff | diff-fenced | udiff | architect
architect: false
auto-accept-architect: true

# API access (prefer .env for secrets)
openai-api-key: null
anthropic-api-key: null
openai-api-base: null
api-key: []                   # list of provider=key
set-env: []                   # list of KEY=VAL
verify-ssl: true

# Files & context
read: [CONVENTIONS.md]
file: []
aiderignore: .aiderignore

# Model metadata override files
model-settings-file: .aider.model.settings.yml
model-metadata-file: .aider.model.metadata.json
alias: []                     # ["fast:gpt-4o-mini", ...]

# History & caching
input-history-file: .aider.input.history
chat-history-file: .aider.chat.history.md
llm-history-file: null
restore-chat-history: false
max-chat-history-tokens: null
cache-prompts: false

# Git
auto-commits: true
dirty-commits: true
attribute-author: true
attribute-committer: true
attribute-co-authored-by: false
git-commit-verify: false
commit-prompt: null
gitignore: true

# UX
dark-mode: false
pretty: true
stream: true
voice-language: en
encoding: utf-8

# Telemetry
analytics: null
analytics-disable: false
```

- **Identity**: none — flat key/value.
- **Scope**: `~/.aider.conf.yml` = user-global; `<repo>/.aider.conf.yml` = project (typically committed).
- **Sync risks**: (a) `*-api-key` keys belong in `.env`, not YAML — sync must redact; (b) absolute path values (e.g. `read: /home/me/CONVENTIONS.md`) do not translate across hosts; (c) `~/.aider.conf.yml` and `<repo>/.aider.conf.yml` are merged at load time, so a sync tool should treat them as two separate artifacts.

### Env file — `.env`

- **Paths** (search order): `~/.aider/oauth-keys.env`, `~/.env`, `<git-root>/.env`, `<cwd>/.env`. Same locations on all OSes; later files override earlier.
- **Format**: dotenv. Every YAML key is mirrored as `AIDER_<UPPER_SNAKE>` (e.g. `AIDER_MODEL`). Provider-native names also work: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, etc.
- **Scope**: `~/.env` and `~/.aider/oauth-keys.env` are user-global; the others are project.
- **Sync risks**: these files almost always contain secrets. Exclude or encrypt by default. OAuth tokens in `~/.aider/oauth-keys.env` are device-bound — exclude.

### Model settings & metadata

Two distinct files, both discoverable in `~/`, `<git-root>/`, or `<cwd>/`; overridable by `--model-settings-file` / `--model-metadata-file`.

- **`~/.aider.model.settings.yml`** — YAML list of per-model behavior overrides. Each list element keys on `name:` (identity field). Documented fields: `name`, `edit_format`, `weak_model_name`, `editor_model_name`, `editor_edit_format`, `use_repo_map`, `send_undo_reply`, `lazy`, `overeager`, `reminder`, `examples_as_sys_msg`, `extra_params`, `cache_control`, `caches_by_default`, `use_system_prompt`, `use_temperature`, `streaming`, `accepts_images`, `accepts_settings`, `reasoning_tag`, `remove_reasoning`, `system_prompt_prefix`.

```yaml
- name: openai/Qwen/Qwen2.5-72B-Instruct
  edit_format: whole
  use_repo_map: true
  use_temperature: true
  streaming: true
  extra_params:
    max_tokens: 4096
```

- **`~/.aider.model.metadata.json`** — JSON dict in LiteLLM's `model_info` schema (`max_input_tokens`, `max_output_tokens`, `input_cost_per_token`, `output_cost_per_token`, `litellm_provider`, `mode`). Keyed by model name (identity = dict key).
- **Scope**: typically user-global.
- **Sync risk**: contents are portable; merge by `name`.

### Session state (out of sync scope)

`<git-root>/.aider.chat.history.md`, `<git-root>/.aider.input.history`, `<git-root>/.aider.llm.history`, `<git-root>/.aider.tags.cache.v3/` (repo-map cache). Session/runtime artifacts — exclude.

### Custom slash commands, hooks, MCP — **not supported**

Aider has a fixed set of slash commands and **does not support user-defined slash commands** (issues #4235, #3616). The only "alias" mechanism is the `alias:` key in `.aider.conf.yml`, which maps short names to model identifiers — not a command system.

Aider has **no hook system**. The only adjacent feature is `git-commit-verify` (default `false`), which lets project-level git hooks fire on Aider's commits. Those hooks belong to Git, not Aider.

Aider has **no native MCP client**. The `disler/aider-mcp-server` project goes the other way (exposes Aider as a tool to MCP clients).

### Other on-disk user-authored items

- `<git-root>/.aiderignore` — `.gitignore`-syntax denylist for repo-map and `/add` glob expansion. Plain text. Project scope. Typically committed.
- `~/.aider/oauth-keys.env` — OpenRouter OAuth token cache. Device-bound; exclude.
- `~/.aider/analytics.json` — UUID + opt-in flag. Out of customization scope.

Aider deliberately does **not** ship per-tool subdirectories. The entire sync surface is: `~/.aider.conf.yml`, `<repo>/.aider.conf.yml`, `~/.aider.model.settings.yml`, `~/.aider.model.metadata.json`, opt-in `~/.env`, `<repo>/CONVENTIONS.md` (path conventional), and `<repo>/.aiderignore`.

### Sources

- [YAML config file](https://aider.chat/docs/config/aider_conf.html)
- [Configuration](https://aider.chat/docs/config.html)
- [Options reference](https://aider.chat/docs/config/options.html)
- [Config with .env](https://aider.chat/docs/config/dotenv.html)
- [API Keys](https://aider.chat/docs/config/api-keys.html)
- [Advanced model settings](https://aider.chat/docs/config/adv-model-settings.html)
- [Specifying coding conventions](https://aider.chat/docs/usage/conventions.html)
- [Git integration](https://aider.chat/docs/git.html)
- [In-chat commands](https://aider.chat/docs/usage/commands.html)
- [Aider-AI/conventions](https://github.com/Aider-AI/conventions)
- [sample.aider.conf.yml](https://github.com/Aider-AI/aider/blob/main/aider/website/assets/sample.aider.conf.yml)
- [Issue #4235 — custom slash commands](https://github.com/aider-ai/aider/issues/4235)
- [Issue #3616 — user-defined command aliases](https://github.com/Aider-AI/aider/issues/3616)
- [Issue #3974 — `.yml` vs `.yaml`](https://github.com/Aider-AI/aider/issues/3974)
- [disler/aider-mcp-server](https://github.com/disler/aider-mcp-server)

---

## Amazon Q Developer

Amazon Q Developer CLI (`q` / `q chat`, formerly Fig, repo at `github.com/aws/amazon-q-developer-cli`) is the focus of this section. The companion JetBrains / VS Code "Amazon Q Developer" agent shares the on-disk surface for rules (`.amazonq/rules/`) and IDE-side MCP configuration but does not consume the CLI agent JSON files. All user-authored CLI data lives under two roots: `~/.aws/amazonq/` (global) and `<project>/.amazonq/` (project). The CLI is officially supported on macOS and Linux; Windows users run it under WSL2, so the Linux paths apply.

A migration is in progress: the original "profiles + `global_context.json`" model has been superseded by **custom agents** (GA July 2025). `global_context.json` is no longer read; `profiles/<name>/context.json` is read only via legacy fallback. New work targets agents, but a sync tool must round-trip legacy files because they remain on disk for many users.

### Rules (`.amazonq/rules/`)

Project rules are plain Markdown files loaded automatically when `q chat` starts inside that directory tree. The CLI globs `.amazonq/rules/**/*.md` recursively. Sub-directories are allowed for organisation; only the `.md` extension is semantic.

```
<project>/.amazonq/rules/coding-standards.md
<project>/.amazonq/rules/frontend/react.rule.md
<project>/.amazonq/rules/security/secrets.md
```

A rule file is just Markdown — no frontmatter, no schema:

```markdown
# Python Style
- Use 4-space indentation.
- Prefer f-strings over `.format()`.
- All public functions must have type hints.
```

There is **no officially supported global rules directory**. The feature request (`aws/amazon-q-developer-cli#3451`) asks for `~/.amazonq/rules/**/*.md`; not landed. Workaround: reference rule files from an agent's `resources` array. Identity: file path (basename). Scope: project. Sync risk: low.

### Custom agents (`cli-agents/<name>.json`)

Custom agents are the modern unit of customization. JSON, validated against `https://raw.githubusercontent.com/aws/amazon-q-developer-cli/refs/heads/main/schemas/agent-v1.json`.

- **Global**: `~/.aws/amazonq/cli-agents/<name>.json`
- **Workspace**: `<project>/.amazonq/cli-agents/<name>.json`

Workspace agents override globals of the same name. `q chat --agent <name>` selects an agent; `q agent create <name>` scaffolds one.

Top-level fields:

| Field | Type | Notes |
|---|---|---|
| `$schema` | string | Optional. |
| `name` | string | Identifier; must match filename stem. |
| `description` | string | Human-readable summary. |
| `prompt` | string\|null | System-prompt instructions. |
| `model` | string | Optional. |
| `mcpServers` | object | Per-agent MCP servers; same shape as `mcp.json`. |
| `tools` | string[] | Built-ins by name (`fs_read`, `execute_bash`, …), MCP tools as `@<server>` or `@<server>/<tool>`. |
| `allowedTools` | string[] | Tools that bypass per-invocation trust prompt. |
| `toolAliases` | object | Remap colliding tool names. |
| `toolsSettings` | object | Per-tool config (e.g., `execute_bash.allowedCommands` regex list). |
| `resources` | string[] | `file://` URIs (glob-supported) auto-attached. |
| `hooks` | object | See Hooks. |
| `useLegacyMcpJson` | boolean | When true, merges the global and workspace `mcp.json`. |

```json
{
  "$schema": "https://raw.githubusercontent.com/aws/amazon-q-developer-cli/refs/heads/main/schemas/agent-v1.json",
  "name": "python-reviewer",
  "description": "Reviews Python PRs with project conventions",
  "prompt": "You review Python code against PEP 8 and project rules.",
  "model": "claude-sonnet-4",
  "mcpServers": {
    "git": { "command": "uvx", "args": ["mcp-server-git"] }
  },
  "tools": ["fs_read", "execute_bash", "@git"],
  "allowedTools": ["fs_read", "@git/git_status", "@git/git_diff"],
  "toolAliases": { "@git/git_status": "status" },
  "toolsSettings": {
    "execute_bash": { "allowedCommands": ["^pytest", "^ruff "] }
  },
  "resources": [
    "file://README.md",
    "file://docs/**/*.md",
    "file://.amazonq/rules/**/*.md"
  ],
  "hooks": {
    "agentSpawn": [{ "command": "git branch --show-current" }],
    "userPromptSubmit": [
      { "command": "git status --porcelain", "timeout_ms": 5000, "cache_ttl_seconds": 30 }
    ]
  },
  "useLegacyMcpJson": false
}
```

Identity: `name` (must equal filename stem). Sync risks: medium — `resources` paths may be machine-specific if absolute; `mcpServers.command` often hard-codes interpreter paths.

### MCP servers (`mcp.json`)

Two legacy-format files:

- **Global**: `~/.aws/amazonq/mcp.json`
- **Workspace**: `<project>/.amazonq/mcp.json`

When both exist, `mcpServers` maps merge as a union; workspace wins on collision. Consumed by an agent only when `"useLegacyMcpJson": true` (default for the implicit "default" agent). Best practice: inline `mcpServers` inside the agent JSON.

| Field | Type | Notes |
|---|---|---|
| `command` | string | stdio binary (mutually exclusive with `url`). |
| `args` | string[] | CLI args. |
| `env` | object | Supports `${VAR}` expansion. |
| `timeout` | int | Per-request timeout (ms); default 60000. |
| `disabled` | boolean | |
| `type` | enum | `stdio` (default), `sse`, or `streamable-http`. |
| `url` | string | For `sse` / `streamable-http`. |
| `headers` | object | HTTP header map. |

```json
{
  "mcpServers": {
    "git": {
      "command": "uvx",
      "args": ["mcp-server-git"],
      "env": { "GIT_AUTHOR_NAME": "${USER}" },
      "timeout": 30000,
      "disabled": false
    },
    "findadomain": {
      "type": "streamable-http",
      "url": "https://api.findadomain.dev/mcp",
      "headers": { "Authorization": "Bearer ${FINDADOMAIN_TOKEN}" }
    }
  }
}
```

Remote transport (`type: "streamable-http"` and `sse`) added September 2025. Identity: server name (object key). Sync risks: high — `command` paths and `env` secrets are workstation-specific.

### Hooks

Hooks live inside agent JSON under the top-level `hooks` key. Two events:

- `agentSpawn` — fires once at agent start; stdout injected for the whole session.
- `userPromptSubmit` — fires before every user message; stdout injected for that one prompt.

```json
"hooks": {
  "agentSpawn": [{ "command": "git branch --show-current", "timeout_ms": 5000 }],
  "userPromptSubmit": [
    {
      "command": "find . -name '*.py' | wc -l",
      "timeout_ms": 3000,
      "max_output_size": 10240,
      "cache_ttl_seconds": 60
    }
  ]
}
```

Fields: `command` (required), `timeout_ms` (default 30000), `max_output_size` (bytes, default 10240), `cache_ttl_seconds` (default 0). No global hooks file — every hook is scoped to one agent.

### Saved prompts (slash-command library)

Reusable prompts as Markdown files, invoked via `@<prompt-name>` and listed via `/prompts`.

- **Global**: `~/.aws/amazonq/prompts/*.md`
- **Workspace**: `<project>/.amazonq/prompts/*.md` (intermittent CLI support — see issue #2243)

Plain Markdown, no required frontmatter. Identity: filename stem. Sync risks: low.

### Context / memory (legacy)

Pre-agents, context was managed under `~/.aws/amazonq/profiles/<profile>/context.json` plus a top-level `~/.aws/amazonq/global_context.json`:

```json
{ "paths": ["README.md", "docs/**/*.md"], "hooks": {} }
```

`global_context.json` is **no longer read**; `profiles/<name>/context.json` is read only via legacy `/profile`. Treat as read-only legacy; migrate to agent `resources`.

### Profiles (legacy)

`~/.aws/amazonq/profiles/<name>/` — directory per profile. Officially superseded by custom agents (see `legacy-profile-to-agent-migration.html`).

### Settings (`q settings`)

`q settings <key> <value>` manipulates a JSON settings file. Located via `q settings open`; typically `~/.local/share/amazon-q/settings.json` (Linux/WSL) or `~/Library/Application Support/amazon-q/settings.json` (macOS). Keys are flat dotted strings (`chat.editMode`, `telemetry.enabled`, `chat.defaultAgent`). Sync risk: medium — some keys host-bound; auth tokens live in the OS keychain (not here).

### Other user-authored on-disk artefacts

- **TODO lists**: `<project>/.amazonq/cli-todo-lists/*.md` — mostly transient.
- **Saved conversations**: `<project>/.amazonq/previous-conversations/conversation-on-<date>.md` — opt-in.
- **Auth / SSO tokens**: `~/.aws/sso/cache/` and OS keychain — **do not sync**.
- **Logs**: `$TMPDIR/qlog/` or `$XDG_RUNTIME_DIR`/`/tmp` — exclude.

Sync-worthy: `~/.aws/amazonq/{cli-agents,prompts,rules,mcp.json}` and matching `<project>/.amazonq/` trees, plus the resolved `settings.json`. Flag `profiles/` and `global_context.json` as read-only legacy.

### Sources

- [Custom agents](https://docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/command-line-custom-agents.html)
- [Custom agents — Configuration reference](https://docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/command-line-custom-agents-configuration.html)
- [Custom agents — Defining](https://docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/command-line-custom-agents-defining.html)
- [The Agent Format](https://aws.github.io/amazon-q-developer-cli/agent-format.html)
- [Built-in Tools](https://aws.github.io/amazon-q-developer-cli/built-in-tools.html)
- [Profile-to-Agent migration](https://aws.github.io/amazon-q-developer-cli/legacy-profile-to-agent-migration.html)
- [Project rules](https://docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/command-line-project-rules.html)
- [Global rules feature request (#3451)](https://github.com/aws/amazon-q-developer-cli/issues/3451)
- [MCP configuration in the CLI](https://docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/command-line-mcp-config-CLI.html)
- [Understanding MCP configuration files](https://docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/command-line-mcp-understanding-config.html)
- [Amazon Q announces remote MCP servers](https://aws.amazon.com/about-aws/whats-new/2025/09/amazon-q-developer-remote-mcp-servers/)
- [Manage prompts](https://docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/command-line-prompts.html)
- [Local prompts CLI issue #2243](https://github.com/aws/amazon-q-developer-cli/issues/2243)
- [Configure Amazon Q settings](https://docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/command-line-settings.html)
- [amazon-q-developer-cli (GitHub)](https://github.com/aws/amazon-q-developer-cli)

---

## Claude Code

Claude Code is Anthropic's official CLI agent. User-authored config lives under `~/.claude/` on Linux/macOS and `%USERPROFILE%\.claude\` on Windows, plus per-project `<project>/.claude/`. Paths below use POSIX form; on Windows replace `~` with `%USERPROFILE%` and `/` with `\`. JSON files are UTF-8, no comments. Markdown files use YAML frontmatter delimited by `---`.

### Subagents

User: `~/.claude/agents/<slug>.md`. Project: `<project>/.claude/agents/<slug>.md`. Scanned recursively, so `agents/review/foo.md` is valid.

Frontmatter:

```yaml
---
name: string            # required, kebab-case slug. Identity = this field
description: string     # required, natural-language trigger description
tools: string|list      # optional; omitted = inherits all parent tools
model: string           # optional, e.g. "sonnet", "opus", "haiku"
color: enum             # optional: blue|cyan|green|yellow|magenta|red
disallowedTools: list   # optional
permissionMode: enum    # optional: default|acceptEdits|plan|bypassPermissions
mcpServers: object      # optional, scoped MCP config
hooks: object           # optional, subagent-scoped hooks
skills: list            # optional, allowed skill slugs
---
```

Minimal example:

```markdown
---
name: code-reviewer
description: Reviews staged diffs for security and style issues.
tools: Read, Grep, Bash
model: sonnet
---
You are a meticulous code reviewer. Focus on...
```

Identity: filename stem (lowercased slug); `name` must match. Conflicts: project > user.

Sync risks: `model` may name a model ID that doesn't exist on the destination; `tools` may reference MCP tools (`mcp__server__tool`) whose server isn't installed on the other side.

### Skills

Path: `~/.claude/skills/<skill-name>/SKILL.md` (user) or `<project>/.claude/skills/<skill-name>/SKILL.md` (project). The skill is a directory; `SKILL.md` is required.

```yaml
---
name: string                       # optional; defaults to directory name
description: string                # required in practice
allowed-tools: string|list         # optional, e.g. "Read, Grep, Bash(git status:*)"
disable-model-invocation: boolean  # optional
license: string                    # optional
---
```

Auxiliary structure:

```
~/.claude/skills/my-skill/
  SKILL.md
  scripts/        # executable code Claude runs via Bash
  references/     # additional docs loaded on demand
  assets/         # templates, images, binary outputs
```

Identity: directory name (slug). Sync risks: `scripts/` may have OS-specific shebangs; skill bodies often reference relative paths inside the skill dir.

### Slash commands

Path: `~/.claude/commands/<name>.md` (user) and `<project>/.claude/commands/<name>.md` (project). Subdirectories namespace: `commands/review/security.md` → `/review:security`.

```yaml
---
description: string
argument-hint: string
allowed-tools: list
model: string
disable-model-invocation: boolean
---
```

Body supports `$ARGUMENTS`, `$1..$N`, `!`-prefixed lines (execute Bash, inline output), and `@path/to/file` (inline file contents).

```markdown
---
description: Open a PR for the current branch
argument-hint: [title]
allowed-tools: ["Bash(git:*)", "Bash(gh pr create:*)"]
---
!git status
Create a PR titled "$ARGUMENTS" using gh.
```

Identity: file path relative to `commands/`. Conflicts: project > user. Sync risks: `!`-shell snippets and `@`-file references are environment-dependent.

### Output styles

Path: `~/.claude/output-styles/<name>.md` or `<project>/.claude/output-styles/<name>.md`. Selected via `outputStyle` in settings or `/output-style`.

```yaml
---
name: string
description: string
keep-coding-instructions: boolean
---
```

### Status line

Convention: `~/.claude/statusline.sh` (or `.py`, `.js`). Registered via `statusLine` in `settings.json`. Claude Code pipes a JSON object (model, cwd, cost, output_style) to stdin; the script writes the status line to stdout.

```json
{ "statusLine": { "type": "command", "command": "~/.claude/statusline.sh" } }
```

Sync risks: script path is environment-specific.

### Hooks

Declared inside `settings.json` under `hooks`. Twelve events. Structure: `hooks → <Event> → [ { matcher, hooks: [ { type, command, timeout, ... } ] } ]`.

Events and matchers:
- `PreToolUse`, `PostToolUse` — matcher = tool name regex (`Bash`, `Edit|Write`, `mcp__github__*`, `*`)
- `UserPromptSubmit` — no matcher
- `Stop`, `SubagentStop` — no matcher
- `Notification` — matcher: `permission_prompt`, `idle_prompt`, `auth_success`
- `PreCompact` — matcher: `manual`, `auto`
- `SessionStart` — matcher: `startup`, `resume`, `clear`, `compact`
- `SessionEnd` — no matcher (reason passed in payload)

Hook object fields: `type` (`command`|`prompt`|`http`|`mcp_tool`|`agent`), `command`, `timeout`, `shell`, `async`, `asyncRewake`, `once`, `statusMessage`.

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {"type": "command", "command": "npx prettier --write \"$CLAUDE_FILE_PATHS\"", "timeout": 30}
        ]
      }
    ],
    "SessionStart": [
      {"matcher": "startup", "hooks": [{"type": "command", "command": "~/.claude/hooks/load-context.sh"}]}
    ]
  }
}
```

Identity: positional. Sync must dedupe by `(event, matcher, command)`. Sync risks: `command` strings reference local paths, local binaries, POSIX shell syntax that breaks on Windows.

### MCP server configs

Three locations:

1. `~/.claude.json` (NOT inside `.claude/`) — user-global servers and per-project under `projects.<path>.mcpServers`.
2. `<project>/.mcp.json` — project-shared, committed to git.
3. `~/.claude/settings.json` or project `.claude/settings.json` may include `mcpServers`.

Server schema:

```json
{
  "type": "stdio",                 // "stdio" | "http" | "sse" | "streamable-http"
  "command": "string",             // stdio only
  "args": ["string"],              // stdio only
  "env": {"KEY": "value"},         // stdio only
  "url": "https://…",              // http/sse only
  "headers": {"Authorization": "Bearer ${TOKEN}"},
  "debug": false
}
```

`${VAR}` interpolation honoured. `CLAUDE_PROJECT_DIR` injected into stdio server env.

```json
{
  "mcpServers": {
    "github": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
    }
  }
}
```

Identity: server name key. Conflicts: project > user. Sync risks: `command` paths differ (`npx` vs `npx.cmd`); `env` may inline secrets; `~/.claude.json` mixes user mcpServers with session state.

### Memory / instructions

- `~/.claude/CLAUDE.md` — user-global, every session.
- `<project>/CLAUDE.md` — project-shared, committed.
- `<project>/<subdir>/CLAUDE.md` — directory-scoped.
- `<project>/CLAUDE.local.md` — personal, gitignored.

Plain Markdown, no frontmatter. `@path` imports another Markdown file inline (depth ≤ 5).

```markdown
# Project rules
- Use uv for Python.

@.claude/rules/architecture.md
@~/.claude/CLAUDE.md
```

Sync risks: `@`-imports may reference paths absent on destination.

### Settings

Files (high → low precedence): `/etc/claude-code/managed-settings.json` (Linux) or `C:\ProgramData\ClaudeCode\managed-settings.json` (Windows) > CLI flags > `<project>/.claude/settings.local.json` > `<project>/.claude/settings.json` > `~/.claude/settings.json`. Array fields like `permissions.allow[]` concatenate.

Documented top-level keys (subset; v2.1.139 exposes 60+):

```json
{
  "$schema": "https://...",
  "model": "string",
  "outputStyle": "string",
  "includeCoAuthoredBy": true,
  "cleanupPeriodDays": 30,
  "apiKeyHelper": "string",
  "awsAuthRefresh": "string",
  "forceLoginMethod": "claudeai|console",
  "enableAllProjectMcpServers": false,
  "env": {"KEY": "value"},
  "permissions": {
    "allow": ["Bash(git:*)"],
    "deny": ["Bash(rm -rf:*)"],
    "ask": ["WebFetch"],
    "additionalDirectories": ["~/scratch"],
    "defaultMode": "default|acceptEdits|plan|bypassPermissions",
    "disableBypassPermissionsMode": "disable"
  },
  "statusLine": {"type": "command", "command": "string"},
  "hooks": { /* see Hooks */ },
  "mcpServers": { /* see MCP */ }
}
```

Sync risks: `apiKeyHelper`, `awsAuthRefresh`, `statusLine.command` hold local paths; `env` may carry secrets; `settings.local.json` is per-machine by design.

### Plugins / marketplaces

Path: `~/.claude/plugins/` — `known_marketplaces.json`, `marketplaces/<name>/`, `cache/<marketplace>/<plugin>/<version>/...`. A plugin contains `.claude-plugin/plugin.json`:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "string",
  "author": {"name": "...", "email": "...", "url": "..."},
  "homepage": "...",
  "repository": "...",
  "license": "MIT",
  "keywords": ["claude-code"]
}
```

Plugin contents auto-discovered: `commands/`, `agents/`, `skills/`, `hooks/`, `.mcp.json`. Identity: `name`. Sync risks: `cache/` is derived state — never sync.

### Keybindings

Path: `~/.claude/keybindings.json` (user only).

```json
{
  "$schema": "https://www.schemastore.org/claude-code-keybindings.json",
  "bindings": [
    {
      "context": "Chat",
      "bindings": {
        "ctrl+e": "chat:externalEditor",
        "ctrl+k ctrl+s": "chat:submit",
        "ctrl+u": null
      }
    }
  ]
}
```

Identity: `(context, keystroke)`. Auto-reloaded on save.

### Other items under `~/.claude/`

- `~/.claude/projects/<path-slug>/` — session transcripts (do not sync).
- `~/.claude/todos/`, `~/.claude/shell-snapshots/`, `~/.claude/statsig/` — runtime state.
- `~/.claude/ide/` — IDE integration lock files.
- `~/.claude/.credentials.json` — auth token (NEVER sync).
- `~/.claude/hooks/` — convention-only directory for hook scripts referenced from `settings.json`.

### Sources

- [Subagents](https://docs.claude.com/en/docs/claude-code/sub-agents)
- [Skills](https://docs.claude.com/en/docs/claude-code/skills)
- [Slash commands](https://docs.claude.com/en/docs/claude-code/slash-commands)
- [Hooks](https://code.claude.com/docs/en/hooks)
- [Settings](https://code.claude.com/docs/en/settings)
- [MCP](https://code.claude.com/docs/en/mcp)
- [Memory](https://code.claude.com/docs/en/memory)
- [Statusline](https://code.claude.com/docs/en/statusline)
- [Output styles](https://code.claude.com/docs/en/output-styles)
- [Keybindings](https://code.claude.com/docs/en/keybindings)
- [Plugins](https://code.claude.com/docs/en/plugins)
- [Claude directory](https://code.claude.com/docs/en/claude-directory)
- [anthropics/claude-code plugins README](https://github.com/anthropics/claude-code/blob/main/plugins/README.md)

---

## Cline

Cline is an open-source VS Code AI coding-agent extension (publisher `saoudrizwan`, extension ID `saoudrizwan.claude-dev`). Its user-authored data is split between (a) plain files in the workspace and a fixed `~/Documents/Cline/` tree, and (b) opaque key/value entries in VS Code's `ExtensionContext.globalState` / `secrets` (SQLite-backed `state.vscdb`). Only the file-based half is in scope for a portable sync tool; the SQLite-backed half is explicitly out of scope.

### Rules — `.clinerules` (workspace) and `~/Documents/Cline/Rules/` (global)

Two scopes, both file-based Markdown:

- **Workspace rules**: either a legacy single file `<project>/.clinerules` *or* a folder `<project>/.clinerules/` containing any number of `*.md` / `*.txt` files. Cline auto-concatenates every file. Numeric prefixes (`01-coding.md`) order the merge. Conditional rules use YAML frontmatter.
- **Global rules**: `~/Documents/Cline/Rules/` on macOS/Linux; `C:\Users\<USER>\Documents\Cline\Rules\` on Windows. A known Linux/WSL quirk (issue #5153) is that some installs land at `~/Cline/Rules/` when `~/Documents` does not exist — probe both.

Workspace wins on conflict. Example:

```markdown
---
description: "Style rules — always-on"
---
- Prefer pure functions
- 100-char line limit
```

Identity: filename and path. Sync risks: toggle state (rule on/off in v3.13+) is kept in `ClineRulesToggles` — a `Record<absolutePath, boolean>` in `globalState`. Docs explicitly warn that toggles do not persist across sessions and that rules can collide between workstations because keys are absolute paths. Sync the files only; let each station rebuild its toggle map.

### Workflows — `.clinerules/workflows/` and `~/Documents/Cline/Workflows/`

Markdown "scripts" Cline executes step-by-step.

- **Workspace**: `<project>/.clinerules/workflows/<name>.md`
- **Global**: `~/Documents/Cline/Workflows/<name>.md`

Invoke as `/<filename>.md` in chat. Cline wraps the body in `<explicit_instructions>` for that one turn. Workspace shadows global on same filename. Identity: filename.

### MCP servers — `cline_mcp_settings.json` (global only)

Single JSON file in the extension's globalStorage:

- **Linux**: `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`
- **macOS**: `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`
- **Windows**: `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`

For VS Code Insiders, replace `Code` with `Code - Insiders`. For VSCodium, `VSCodium`.

Top-level `mcpServers` object keyed by server name. Per-server fields: `command`, `args`, `env`, `disabled`, `autoApprove` (string[]), `timeout`, transport discriminator (`transportType: "stdio" | "sse"` or `type: "streamableHttp"` with `url`/`headers`).

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/me"],
      "env": {},
      "disabled": false,
      "autoApprove": ["read_file"],
      "timeout": 60,
      "transportType": "stdio"
    },
    "linear-remote": {
      "type": "streamableHttp",
      "url": "https://mcp.example.com/linear",
      "headers": {"Authorization": "Bearer ${LINEAR_TOKEN}"},
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

Identity: `mcpServers` key. No project-level MCP config. Marketplace installs write into the same file. Sync risks: `env` and `headers` typically contain secrets; mask or omit. Issue #9663 — Marketplace installer has been observed to overwrite the entire file; back up before merging.

### Memory — "Memory Bank" community pattern (`<project>/memory-bank/`)

Not built-in; a widely-adopted custom-instruction recipe:

```
<project>/memory-bank/
├── projectbrief.md       # foundation: requirements, goals, scope
├── productContext.md     # why it exists, UX goals
├── activeContext.md      # current focus, recent changes
├── systemPatterns.md     # architecture, key patterns
├── techContext.md        # stack, setup, constraints
└── progress.md           # status, milestones, known issues
```

Activation requires a corresponding `.clinerules/memory-bank.md` rule. Pure convention; sync if present, never auto-create.

### Slash commands

No separate slash-command file type. `/foo.md` runs the workflow `foo.md` (see §Workflows).

### VS Code settings — `cline.*` keys

User-/workspace-level VS Code settings under `cline.`. Relevant keys (non-exhaustive — Cline adds new keys frequently):

- `cline.customInstructions` — path to a Markdown file injected as custom instructions (file-syncable; see issue #8313).
- `cline.preferredLanguage`, `cline.enableCheckpoints`, `cline.disableBrowserTool`, `cline.openAiBaseUrl`, `cline.modelCacheTtl`, `cline.telemetrySetting`.

Cline does not publish a stable list; the marketplace `package.json` `contributes.configuration` is the source of truth. Sync by extracting any key matching `^cline\.` from VS Code `settings.json`.

### Custom Instructions (the textbox) — globalState, NOT a file

The "Custom Instructions" textarea writes to VS Code `ExtensionContext.globalState`, in the shared SQLite `state.vscdb`:

- Linux: `~/.config/Code/User/globalStorage/state.vscdb`
- macOS: `~/Library/Application Support/Code/User/globalStorage/state.vscdb`
- Windows: `%APPDATA%\Code\User\globalStorage\state.vscdb`

Workspace-wide singleton shared by every extension; do not touch. Recent Cline versions export ExtensionContext to `~/.cline/data/{globalState.json, workspaceState.json, secrets.json}`, but the canonical source remains `state.vscdb`. **Out of sync scope.** Skip `state.vscdb` and `~/.cline/data/secrets.json`.

### MCP Marketplace installed servers

Marketplace writes into the same `cline_mcp_settings.json`. Some installs clone server source trees to `~/.cline/mcp/<server>/` — treat as build artefact, do not sync.

### Other on-disk user-authored items

- `<project>/.clineignore` — `.gitignore`-syntax. Hot-reloaded.
- `<project>/.vscode/settings.json` — workspace overrides for `cline.*` settings.
- `~/Documents/Cline/` — parent of `Rules/` and `Workflows/`.

### Out-of-sync items (flag to user)

| Item | Location | Reason |
|---|---|---|
| Custom Instructions textbox | `state.vscdb` globalState | Shared SQLite |
| Selected model / provider / API endpoint | `state.vscdb` globalState | Same |
| API keys | `state.vscdb` `secrets` + `~/.cline/data/secrets.json` | Secrets |
| Rule toggle state | `ClineRulesToggles` (absolute-path keys) | Per-workstation |
| Chat history / task checkpoints | `~/.cline/data/` + globalStorage | Local artefacts |

### Sources

- [Cline rules (features)](https://docs.cline.bot/features/cline-rules)
- [Rules (customization)](https://docs.cline.bot/customization/cline-rules)
- [Workflows](https://docs.cline.bot/features/slash-commands/workflows)
- [.clineignore](https://docs.cline.bot/customization/clineignore)
- [Memory Bank](https://docs.cline.bot/features/memory-bank)
- [Cline 3.13 — toggleable .clinerules](https://cline.bot/blog/cline-3-13-toggleable-clinerules-slash-commands-previous-message-editing)
- [Cline 3.17 — global workflows](https://cline.bot/blog/3-17-global-workflows-ux-improvements-and-more)
- [Cline 3.16 — workflows GA](https://cline.bot/blog/cline-v3-16-one-shot-automation-with-workflows-plus-ui-stability-gains)
- [Stop adding rules when you need workflows](https://cline.bot/blog/stop-adding-rules-when-you-need-workflows)
- [Issue #5153 — global rules path on Linux/WSL](https://github.com/cline/cline/issues/5153)
- [Issue #8313 — `cline.customInstructions` setting](https://github.com/cline/cline/issues/8313)
- [Issue #9663 — MCP install overwrote `cline_mcp_settings.json`](https://github.com/cline/cline/issues/9663)
- [Discussion #3796 — declarative settings vs globalState](https://github.com/cline/cline/discussions/3796)
- [cline/prompts memory-bank rule](https://github.com/cline/prompts/blob/main/.clinerules/memory-bank.md)
- [Cline VS Code Marketplace page](https://marketplace.visualstudio.com/items?itemName=saoudrizwan.claude-dev)

---

## Continue.dev

Continue.dev is an open-source AI coding assistant for VS Code and JetBrains IDEs, plus a `cn` CLI. Its user-authored configuration follows a **block-based YAML system**: most artefacts can be defined either inline inside a single `config.yaml` (or assistant file) or as a standalone file in a dedicated subdirectory of `~/.continue/` (global) or `<project>/.continue/` (workspace). Both trees expose the same subdirectory grammar.

### Filesystem roots

| OS | Global user root | Workspace root |
|---|---|---|
| Linux | `~/.continue/` | `<project>/.continue/` |
| macOS | `~/.continue/` | `<project>/.continue/` |
| Windows | `%USERPROFILE%\.continue\` | `<project>\.continue\` |

Workspace overrides global on name collision.

### Primary config — `config.yaml`

Path: `~/.continue/config.yaml` or `<project>/.continue/config.yaml`. Legacy `config.json` is still recognised but `config.yaml` takes precedence.

```yaml
name: My Config            # required
version: 1.0.0             # required
schema: v1                 # required, currently only "v1"
models: []
context: []
rules: []
prompts: []
docs: []
mcpServers: []
data: []
```

### Assistants / Agents — `assistants/` (a.k.a. `agents/`)

"Assistant" and "agent" used interchangeably; the directory is conventionally `agents/` in recent releases, `assistants/` still recognised.

- Global: `~/.continue/agents/*.yaml`
- Project: `<project>/.continue/agents/*.yaml`

Each file is a **full config.yaml-shaped document** — same top-level keys, letting users keep several named assistants and switch via the IDE selector.

```yaml
name: offline-config
version: 0.1.0
schema: v1
models:
  - name: Llama 3 Local
    provider: ollama
    model: llama3
    roles: [chat, edit]
rules:
  - "Prefer standard library over third-party deps."
mcpServers:
  - name: sqlite
    command: uvx
    args: [mcp-server-sqlite, --db-path, ./test.db]
```

Identity: `name` slug (typically matches filename stem).

### Models — `models/`

`~/.continue/models/*.yaml` (or project equivalent). One model block per file.

```yaml
name: GPT-4o
provider: openai                   # openai|anthropic|ollama|mistral|bedrock|...
model: gpt-4o
apiKey: ${{ secrets.OPENAI_KEY }}
apiBase: https://api.openai.com
roles: [chat, edit, apply, autocomplete, embed, rerank, summarize]
defaultCompletionOptions:
  temperature: 0.2
  maxTokens: 2000
capabilities: [tool_use, image_input]
```

Sync risk: `apiKey` often inlined — must be redacted or referenced through Continue's `secrets` indirection.

### Rules — `rules/`

Two formats coexist: Markdown rule files at `~/.continue/rules/*.md` (or project equivalent), and inline strings or blocks under `rules:` in any config file.

```markdown
---
name: Documentation Standards
globs: docs/**/*.{md,mdx}              # string or list of glob patterns
regex: "^import .* from '.*';$"        # optional
alwaysApply: false                     # true | false | unset
description: When editing docs files…
---

Body of the rule in Markdown.
```

`alwaysApply` semantics: `true` (or no frontmatter) ⇒ always; `false` ⇒ only if `globs` match or the agent pulls it in by `description`; unset ⇒ no globs → included; globs + match → included.

Identity: filename stem (or `name`). Sync risk: globs are often workstation-specific.

### Prompts — `prompts/`

`~/.continue/prompts/*.prompt` (preferred) or `*.md`. Invoked via `/<name>`. Replaces the deprecated `customCommands` from `config.json`.

Optional YAML preamble + body. Handlebars: `{{{ input }}}`, `{{{ currentFile }}}`, `{{{ ./path/to/file.js }}}`, plus `@`-style context-provider refs.

```
---
name: write-tests
description: Generate pytest cases for the current file
invokable: true
---
<system>
You are a senior Python engineer. Output pytest test cases only.
</system>

Write unit tests for the following file:

{{{ currentFile }}}

User additional instructions: {{{ input }}}
```

Identity: `name` (or filename stem).

### MCP servers — `mcpServers/`

`~/.continue/mcpServers/*.yaml`. One server per file. Usable only in **agent mode**.

```yaml
name: My SQLite MCP Server
command: uvx
args: [mcp-server-sqlite, --db-path, ./test.db]
cwd: /Users/me/project
env:
  NODE_ENV: production
  MY_TOKEN: ${{ secrets.MY_TOKEN }}
type: stdio                     # stdio | sse | streamable-http
url: https://mcp.example.com    # for sse / streamable-http only
```

Sync risk: hardcoded `cwd`, absolute `command` paths, tokens in `env`.

### Context providers — `context/`

```yaml
- provider: codebase
  params: { nRetrieve: 30, nFinal: 3 }
- provider: docs
- provider: diff
- provider: http
  name: Internal Wiki
  params:
    url: https://wiki.example.com/search
    headers: { Authorization: "Bearer ${{ secrets.WIKI_TOKEN }}" }
```

### Docs — `docs/`

```yaml
- name: Continue
  startUrl: https://docs.continue.dev/intro
  rootUrl: https://docs.continue.dev
  faviconUrl: https://docs.continue.dev/favicon.ico
  maxDepth: 3
  useLocalCrawling: false
```

### Data — `data/`

```yaml
- name: My Private Company
  destination: https://mycompany.com/ingest   # HTTPS POST or file://
  schema: 0.2.0
  level: noCode                               # all | noCode
  events: [autocomplete, chatInteraction]
```

### Legacy and auxiliary files

- `~/.continue/config.json` — superseded by `config.yaml`.
- `~/.continue/config.ts` — programmatic override exporting `modifyConfig(config)`.
- `~/.continue/.continuerc.json` — runtime overlay; `mergeBehavior: merge | overwrite`. Also valid at workspace root.
- `.continueignore` at `~/.continue/.continueignore` (global) or `<project>/.continueignore` (workspace root, **not** inside `.continue/`).

### Not user-authored (do not sync)

`~/.continue/index/` (codebase embedding index, SQLite), `logs/`, `sessions/` (chat history), cached doc indexes.

### Identity / scope / risk summary

| Block | Path | Identity | Risk |
|---|---|---|---|
| `config.yaml` | `<root>/config.yaml` | singleton | secrets inline |
| Assistant | `<root>/agents/<slug>.yaml` | `name`/stem | embeds models+secrets |
| Model | `<root>/models/<slug>.yaml` | `name` | `apiKey`, `apiBase` |
| Rule (md) | `<root>/rules/<slug>.md` | `name`/stem | `globs` workstation-specific |
| Prompt | `<root>/prompts/<slug>.prompt` | `name`/stem | path templating |
| MCP server | `<root>/mcpServers/<slug>.yaml` | `name` | `cwd`, absolute `command`, env secrets |
| Context | `<root>/context/<slug>.yaml` | `provider`+`name` | http headers/tokens |
| Docs | `<root>/docs/<slug>.yaml` | `name` | low |
| Data | `<root>/data/<slug>.yaml` | `name` | destination secrets |
| `.continueignore` | `<root>/.continueignore` | path | low |
| `config.ts` | `~/.continue/config.ts` | singleton | arbitrary code |

### Sources

- [config.yaml Reference](https://docs.continue.dev/reference)
- [How to Configure Continue](https://docs.continue.dev/customize/deep-dives/configuration)
- [Migrating Config to YAML](https://docs.continue.dev/reference/yaml-migration)
- [Rules](https://docs.continue.dev/customize/deep-dives/rules)
- [Prompts](https://docs.continue.dev/customize/deep-dives/prompts)
- [Prompt files (experimental)](https://docs.continue.dev/features/prompt-files)
- [MCP](https://docs.continue.dev/customize/deep-dives/mcp)
- [MCP servers](https://docs.continue.dev/customize/mcp-tools)
- [Context Providers](https://docs.continue.dev/customize/deep-dives/custom-providers)
- [Development Data](https://docs.continue.dev/customize/deep-dives/development-data)
- [Intro to Roles](https://docs.continue.dev/customize/model-roles/intro)
- [Hub vs Local Configuration](https://docs.continue.dev/guides/understanding-configs)
- [YAML Blocks and Composition (DeepWiki)](https://deepwiki.com/continuedev/continue/5.2-yaml-blocks-and-composition)
- [Issue #8484 — Multiple local configs](https://github.com/continuedev/continue/issues/8484)

---

## Crush (Charmbracelet)

Crush is Charmbracelet's open-source terminal AI coding agent, written in Go, multi-provider. It is the rebrand of Charm's earlier `opencode` after SST forked it. Configuration is **single JSON file plus a few directories**, and follows XDG conventions on every OS (including macOS — does **not** use `~/Library/Application Support`).

### Global paths

```
Linux   : $XDG_CONFIG_HOME/crush/crush.json   (default ~/.config/crush/crush.json)
          $XDG_DATA_HOME/crush/               (default ~/.local/share/crush/)
macOS   : ~/.config/crush/crush.json          (XDG, not ~/Library/Application Support)
          ~/.local/share/crush/
Windows : %LOCALAPPDATA%\crush\crush.json     (config AND ephemeral data share this path —
                                               see issue #1347, currently a known conflict)
```

Overrides: `CRUSH_GLOBAL_CONFIG`, `CRUSH_GLOBAL_DATA`, `CRUSH_SKILLS_DIR`. CLI: `crush dirs config`, `crush dirs data`, `crush schema`.

**Project-local lookup order** (first found wins, then merges over global):

```
./.crush.json
./crush.json
```

### Custom agents

Crush has **no user-authored sub-agent definitions** today. It internally wires two fixed agent roles (`coder` = large model, `task` = small model) bound to `models` in `crush.json`. Sub-agent support is an open request (issues #431, #1807). The closest extension point is Agent Skills (below).

### MCP servers

Under the `mcp` key in `crush.json`. Three transports: `stdio`, `http`, `sse`. Variable expansion supports `$VAR`, `${VAR:-default}`, `$(cmd)`, `${VAR:?msg}` in string fields (but not in `extra_body`).

```json
{
  "$schema": "https://charm.land/crush.json",
  "mcp": {
    "filesystem": {
      "type": "stdio",
      "command": "node",
      "args": ["/path/to/mcp-server.js"],
      "timeout": 120,
      "disabled": false,
      "disabled_tools": ["some-tool"],
      "env": { "NODE_ENV": "production" }
    },
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": { "Authorization": "Bearer $GH_PAT" }
    },
    "stream": {
      "type": "sse",
      "url": "https://example.com/mcp/sse",
      "headers": { "API-Key": "$(echo $API_KEY)" }
    }
  }
}
```

Identity: map key. Sync risk: secrets typically `$VAR`-expanded, so JSON is safe; literal tokens must be redacted.

### Slash commands (user)

**Not implemented** as of issue #2219. The TUI Commands Dialog exposes a `UserCommands` tab, but no on-disk loader. The proposed layout is `~/.config/crush/commands/<name>.md`, mirroring Claude Code. Treat Crush as having **no slash-command surface** for now.

### Rules / instructions / context files

Crush reads project-root Markdown files automatically:

```
./AGENTS.md          ./AGENTS.local.md
./CRUSH.md           ./CRUSH.local.md
./CLAUDE.md          ./CLAUDE.local.md
./GEMINI.md          ./GEMINI.local.md
```

Default file written by `crush` on first init is controlled by `options.initialize_as` (default `AGENTS.md`). Additional paths via `options.context_paths`. **No global rules file**. Sync: treat `AGENTS.md`/`CRUSH.md` as canonical, others as compatibility aliases.

### Settings — full `crush.json` schema

```json
{
  "$schema": "https://charm.land/crush.json",
  "models":      { /* per-role model selection */ },
  "providers":   { /* LLM provider defs */ },
  "mcp":         { /* see MCP */ },
  "lsp":         { /* language servers */ },
  "hooks":       { /* PreToolUse only */ },
  "options":     { /* see below */ },
  "permissions": { "allowed_tools": [] },
  "tools":       { /* per-tool overrides */ }
}
```

- **`providers.<name>`**: `type` (`openai`|`openai-compat`|`anthropic`), `base_url`, `api_key`, `api_endpoint`, `extra_headers`, `extra_body` (NOT expanded), `disable`, `system_prompt_prefix`, `models[]` (`id`, `name`, `context_window`), `provider_options`.
- **`models.<role>`**: `model`, `provider`, `max_tokens`, `reasoning_effort`, `think`, `temperature`, `top_p`, `top_k`, `frequency_penalty`, `presence_penalty`, `provider_options`. Roles: `large`, `small`.
- **`lsp.<lang>`**: `command` (req), `args`, `env`, `disabled`, `filetypes`, `root_markers`, `init_options`, `options`, `timeout`.
- **`options`**: `skills_paths`, `disabled_tools`, `disabled_skills`, `auto_lsp`, `debug`, `debug_lsp`, `context_paths`, `progress`, `disable_notifications`, `disable_auto_summarize`, `disable_metrics`, `disable_provider_auto_update`, `disable_default_providers`, `data_directory`, `initialize_as`, `tui.{compact_mode,diff_mode,transparent}`, `attribution.{trailer_style,generated_with}`.
- **`hooks.PreToolUse[]`**: `matcher` (regex, optional), `command` (req), `timeout` (default 30s). Only `PreToolUse` today. Hook stdin = JSON `{event, session_id, cwd, tool_name, tool_input}`; stdout = `{"decision":"allow"|"deny", "context":"…"}`.

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "^(edit|write|multiedit)$",
        "command": ".crush/hooks/protect-files.sh" }
    ]
  },
  "permissions": { "allowed_tools": ["view", "ls", "grep", "edit"] },
  "options": {
    "initialize_as": "AGENTS.md",
    "context_paths": ["docs/architecture.md"],
    "skills_paths": ["~/.config/crush/skills", "./project-skills"],
    "disabled_skills": ["crush-config"],
    "attribution": { "trailer_style": "co-authored-by", "generated_with": true }
  }
}
```

### Themes

Built-in only. Issue #1334 is the open feature request. Nothing to sync.

### Hooks (user-authored scripts)

User-authored hook scripts live wherever `command` points — conventionally `./.crush/hooks/*.sh` (project) or `~/.config/crush/hooks/*.sh` (global). Auto-discovery is not done by directory scan — JSON reference and script file must move together.

### Agent Skills

Crush implements the AgentSkills.io spec. A skill is a folder with a `SKILL.md` plus optional resources. Search order:

```
Global (any of):
  $CRUSH_SKILLS_DIR
  $XDG_CONFIG_HOME/agents/skills/    (~/.config/agents/skills/)
  $XDG_CONFIG_HOME/crush/skills/     (~/.config/crush/skills/)
  ~/.agents/skills/
  ~/.claude/skills/                  (compat)
  Windows: %LOCALAPPDATA%\agents\skills\, %LOCALAPPDATA%\crush\skills\

Project (auto, no config needed):
  .agents/skills/
  .crush/skills/
  .claude/skills/                    (compat)
  .cursor/skills/                    (compat)
```

Additional via `options.skills_paths[]`. Skill identity = folder name. Sync risk: Crush intentionally reads `~/.claude/skills/` — treat as a **shared** surface; avoid double-syncing physical directories between Claude Code and Crush.

### Ignore files

`.gitignore` is honored; `.crushignore` (gitignore syntax) adds Crush-specific exclusions. Project-only.

### Ephemeral / non-sync data

Crush writes a SQLite session/history database, `crush.log`, and a separate ephemeral `crush.json` under the data directory (`~/.local/share/crush/`, Windows `%LOCALAPPDATA%\crush\`). Exclude from sync.

### Summary

| Surface | Path | Sync? | Risk |
|---|---|---|---|
| Global config | `~/.config/crush/crush.json` (all OS), `%LOCALAPPDATA%\crush\crush.json` (Win) | yes | secrets in `api_key`/`headers`/`env` — require `$VAR` indirection |
| Project config | `./.crush.json`, `./crush.json` | per-project | same |
| Rules | `AGENTS.md`, `CRUSH.md`, `CLAUDE.md`, `GEMINI.md` (+ `.local`) | project-only | shared with other agents |
| Skills | `~/.config/crush/skills/`, `~/.agents/skills/`, `~/.claude/skills/`; project `.crush/skills/`, `.agents/skills/` | yes | aliasing with Claude Code |
| Hooks | wherever `hooks.PreToolUse[].command` points (conv. `.crush/hooks/`) | yes | executable bits + JSON pointer must move atomically |
| Commands (slash) | planned `~/.config/crush/commands/*.md` | future | watch issue #2219 |
| Themes | built-in only | no | n/a |
| Ignore | `./.crushignore` | per-project | n/a |
| DB / logs | `~/.local/share/crush/`, `%LOCALAPPDATA%\crush\` | **no** | runtime state |

### Sources

- [charmbracelet/crush](https://github.com/charmbracelet/crush)
- [crush/AGENTS.md](https://github.com/charmbracelet/crush/blob/main/AGENTS.md)
- [crush-config SKILL.md (authoritative config-key reference)](https://github.com/charmbracelet/crush/blob/main/internal/skills/builtin/crush-config/SKILL.md)
- [DeepWiki: Configuration](https://deepwiki.com/charmbracelet/crush/2.2-configuration)
- [DeepWiki: Provider Setup](https://deepwiki.com/charmbracelet/crush/2.3-provider-setup-and-authentication)
- [Issue #2219 — slash commands](https://github.com/charmbracelet/crush/issues/2219)
- [Issue #1347 — Windows config/data conflict](https://github.com/charmbracelet/crush/issues/1347)
- [Issue #1019 — where is the config file](https://github.com/charmbracelet/crush/issues/1019)
- [Issue #1334 — theme customization](https://github.com/charmbracelet/crush/issues/1334)
- [Issue #1807 — subagents](https://github.com/charmbracelet/crush/issues/1807)
- [Crush quickstart](https://charmbracelet-crush.mintlify.app/quickstart)

---

## Cursor

Cursor is an AI-native fork of VS Code. User-authored AI customization spans (a) **project-local files** under `<project>/.cursor/`, (b) **user-global files** under `~/.cursor/`, (c) **VS Code-style settings** at the User-config path, and (d) **cloud-only state** (account "User Rules", "Team Rules", Background Agent secrets, Docs index) NOT reachable from local files and therefore NOT syncable. The local surface is the syncable surface.

| OS | Cursor User dir | Cursor home |
|---|---|---|
| Linux | `~/.config/Cursor/User/` | `~/.cursor/` |
| macOS | `~/Library/Application Support/Cursor/User/` | `~/.cursor/` |
| Windows | `%APPDATA%\Cursor\User\` | `%USERPROFILE%\.cursor\` |

### Rules (`.mdc`, modern Project Rules)

Project Rules at `<project>/.cursor/rules/*.mdc` (nested subdirectories scope rules). Plain `.md` files are silently ignored — `.mdc` is load-bearing. Each rule = YAML frontmatter + Markdown body.

```mdc
---
description: When and why this rule applies (used by Agent Requested rules)
globs: ["**/*.ts", "**/*.tsx"]
alwaysApply: false
---

# Body in Markdown
- Plain instructions for the agent
- @path/to/file.ts            # @-references are inlined as context
```

Rule "types" are derived, not declared:

| `alwaysApply` | `globs` | `description` | Behavior |
|---|---|---|---|
| `true` | — | — | **Always** — prepended every turn |
| `false` | non-empty | — | **Auto Attached** — when matching file is in context |
| `false` | empty | non-empty | **Agent Requested** — model decides |
| `false` | empty | empty | **Manual** — only via `@RuleName` |

User-level rules: `~/.cursor/rules/*.mdc`. The **"User Rules"** pane in Settings → Rules is stored in Cursor's account/cloud profile (SQLite-blob `state.vscdb`), **not reliably file-syncable**; the `~/.cursor/rules/` directory IS.

Legacy: `<project>/.cursorrules` at repo root. `AGENTS.md` (and nested) at root is an alternative.

Identity: filename stem.

### Custom Modes

A "mode" bundles (prompt, model, tool allowlist, auto-run toggles). Legacy storage: in-app Settings UI. Cursor has been migrating modes to a committable `<project>/.cursor/modes.json` so teams can share them. JSON: array of mode objects with `name`, `model`, `prompt`/`instructions`, `tools` (subset of Cursor's tool catalog), and auto-run flags. No documented user-global `~/.cursor/modes.json`; user-scope modes still live in SQLite settings.

### Background Agents

Cloud-hosted VMs. The only local user-authored artifact is `<project>/.cursor/environment.json` (commit it):

```json
{
  "snapshot": "snap_abc123",
  "install": "npm ci",
  "start": "npm run dev",
  "terminals": [
    { "name": "server", "command": "npm run start" }
  ],
  "dockerfile": ".cursor/Dockerfile"
}
```

Optional sibling: `<project>/.cursor/Dockerfile`. Secrets and GitHub linkage are encrypted in Cursor's cloud DB — NOT in any local file.

### MCP servers

Two locations, identical schema:
- User-global: `~/.cursor/mcp.json`
- Project: `<project>/.cursor/mcp.json`

Root key `mcpServers`. Three transports:

```json
{
  "mcpServers": {
    "local-stdio": {
      "type": "stdio",
      "command": "python",
      "args": ["${workspaceFolder}/tools/mcp_server.py"],
      "env": { "API_KEY": "${env:API_KEY}" }
    },
    "remote-http": {
      "url": "https://api.example.com/mcp",
      "headers": { "Authorization": "Bearer ${env:MY_SERVICE_TOKEN}" }
    },
    "remote-sse": {
      "type": "sse",
      "url": "https://sse.example.com/v1/sse",
      "headers": { "Authorization": "Bearer ${env:TOKEN}" }
    },
    "oauth-server": {
      "url": "https://api.example.com/mcp",
      "auth": {
        "CLIENT_ID": "${env:MCP_CLIENT_ID}",
        "CLIENT_SECRET": "${env:MCP_CLIENT_SECRET}"
      }
    }
  }
}
```

Fields: `type` (`stdio`|`sse`|omit for streamable HTTP), `command`, `args`, `env`, `url`, `headers`, `auth`. Variable interpolation: `${workspaceFolder}`, `${env:VAR}`, `${userHome}`. Identity: key under `mcpServers`.

### Memories

Cursor's built-in "Memories" feature was **deprecated and removed in 2.1.x (late 2025)**. No canonical local `memories/` directory in current Cursor. Persistent context now via Project Rules.

### Slash commands

`<project>/.cursor/commands/*.md` (project) and `~/.cursor/commands/*.md` (user). Filename stem → command name. **Plain Markdown with no frontmatter** (unlike Claude Code). Fully syncable.

```markdown
# Refactor selection
Refactor the selected code to:
- be type-safe
- pass `ruff check`
- preserve public API
```

### Hooks (Cursor 1.7+)

Configured via `hooks.json`. Locations searched in order: `<project>/.cursor/hooks.json`, `~/.cursor/hooks.json`, plus an enterprise/team location.

```json
{
  "version": 1,
  "hooks": {
    "beforeSubmitPrompt":   [{ "command": "./.cursor/hooks/audit.sh" }],
    "beforeShellExecution": [{ "command": "./hooks/guard.sh", "matcher": "^rm " }],
    "beforeMCPExecution":   [{ "command": "node hooks/mcp-audit.js" }],
    "afterMCPExecution":    [{ "command": "node hooks/mcp-log.js" }],
    "afterFileEdit":        [{ "command": "./hooks/format.sh" }],
    "stop":                 [{ "command": "./hooks/notify.sh" }]
  }
}
```

Six lifecycle events. Hooks are spawned processes exchanging JSON over stdio; can `allow`/`deny`/`modify`. Sync risk: hook commands reference scripts — those scripts must also be synced and made executable on the destination.

### Notepads & Docs

**Notepads** (`@notepad`) were beta and **deprecated end of October 2025**. **Docs** (`@Docs`) are cloud-indexed under the Cursor account; only the *list* is reachable, and only through the UI/API. Both cloud-only, OUT OF SCOPE.

### Settings (`settings.json`)

VS Code-style JSON. Common documented Cursor namespaces:

- `cursor.cpp.disabledLanguages`, `cursor.cpp.enablePartialAccepts`
- `cursor.cmdk.useThemedDiffBackground`
- `cursor.chat.smoothStreaming`
- `cursor.composer.shouldAllowCustomModes`, `cursor.composer.collapseFileDiffsInChat`
- `cursor.general.enableShadowWorkspace`, `cursor.general.disableHttp2`
- `cursor.terminal.usePreviewBox`
- `cursor.diffs.useCharacterLevelDiffs`

Most user-visible toggles in Settings → Cursor Settings are NOT in `settings.json` — they live in the SQLite blob `state.vscdb` under `<User dir>/globalStorage/`. **This is the single biggest sync hazard for Cursor**: anything edited through the in-app pane (account, model preferences, privacy mode, Tab settings beyond the keys above, User Rules text, UI-created custom-modes entries, Notepads) is in SQLite, not in a syncable JSON file.

### Other user-authored local files

- `<project>/.cursorignore` — gitignore-syntax; excludes from AI access and indexing.
- `<project>/.cursorindexingignore` — excludes from indexing only.
- `<project>/.cursor/Dockerfile`, `<project>/.cursor/environment.json` — Background Agent.
- `AGENTS.md` and nested at repo root — see Rules.
- Legacy `<project>/.cursorrules`.

### Syncable vs cloud-only

| Surface | Syncable via local files? |
|---|---|
| `.cursor/rules/*.mdc`, `~/.cursor/rules/*.mdc` | Yes |
| `AGENTS.md`, `.cursorrules` | Yes |
| `.cursor/mcp.json`, `~/.cursor/mcp.json` | Yes (redact secrets) |
| `.cursor/commands/*.md`, `~/.cursor/commands/*.md` | Yes |
| `.cursor/hooks.json`, `~/.cursor/hooks.json` | Yes (sync scripts too) |
| `.cursor/modes.json` | Yes |
| `.cursor/environment.json`, `Dockerfile` | Yes (secrets stay in cloud) |
| `.cursorignore`, `.cursorindexingignore` | Yes |
| `settings.json` Cursor keys | Yes (JSON-stored subset only) |
| In-app Cursor Settings pane (SQLite) | **No** |
| Background Agent secrets, GitHub linkage | **No — cloud only** |
| User Rules / Team Rules panes | **No — cloud only** |
| Memories (deprecated), Notepads (deprecated) | **No — gone/cloud** |
| Docs (`@Docs` index) | **No — cloud only** |

### Sources

- [Cursor Docs — Rules](https://cursor.com/docs/rules)
- [Cursor Docs — MCP](https://cursor.com/docs/mcp)
- [Cursor Docs — Hooks](https://cursor.com/docs/hooks)
- [Cursor Docs — Custom Modes](https://docs.cursor.com/chat/custom-modes)
- [Cursor Docs — Background Agents](https://docs.cursor.com/en/background-agent)
- [Cursor Docs — Slash Commands](https://cursor.com/docs/cli/reference/slash-commands)
- [Cursor Docs — Ignore Files](https://cursor.com/docs/reference/ignore-file)
- [Cursor Docs — Notepads (Beta, deprecated)](https://docs.cursor.com/beta/notepads)
- [Forum — Deprecating Notepads](https://forum.cursor.com/t/deprecating-notepads-in-cursor/138305)
- [Forum — Project-based JSON Settings](https://forum.cursor.com/t/project-based-json-settings-for-cursor/46179)
- [Forum — MDC rules best practices](https://forum.cursor.com/t/my-best-practices-for-mdc-rules-and-troubleshooting/50526)
- [Changelog 1.6 — slash commands](https://cursor.com/changelog/1-6)
- [GitButler — Deep dive into Cursor Hooks](https://blog.gitbutler.com/cursor-hooks-deep-dive)
- [TrueFoundry — MCP Authentication in Cursor](https://www.truefoundry.com/blog/mcp-authentication-in-cursor-oauth-api-keys-and-secure-configuration)
- [Scientific Witchery — Cursor settings location (SQLite state.vscdb)](https://www.jackyoustra.com/blog/cursor-settings-location)
- [cursor-hooks npm — JSON Schema](https://libraries.io/npm/cursor-hooks)

---

## GitHub Copilot

GitHub Copilot's customization surface spans **GitHub.com / Copilot coding agent**, **VS Code**, **Visual Studio 2022**, and **GitHub Copilot CLI** (`copilot` binary, formerly invoked via `gh copilot`). Files are a mix of repo-scoped, user-scoped (VS Code profile or `~/.copilot`), and cloud-only.

### Repository custom instructions (single-file)

Path: `<repo>/.github/copilot-instructions.md`. Markdown, no frontmatter. Loaded by Copilot Chat in VS Code, Visual Studio, JetBrains, Eclipse, Xcode, GitHub.com chat, code review, and the coding agent.

```markdown
# Project: agents_sync
Use Python 3.12, `uv` for env management, ruff format, mypy --strict.
Tests live in tests/ and are split via the `slow` pytest marker.
```

VS Code requires `github.copilot.chat.codeGeneration.useInstructionFiles: true` (default `true`).

### Path-scoped instructions (`*.instructions.md`)

**Workspace**: `<repo>/.github/instructions/*.instructions.md` (recursive). Additional folders via `chat.instructionsFilesLocations`.

**User profile** (VS Code, syncs via Settings Sync):
- Linux: `~/.config/Code/User/prompts/*.instructions.md`
- macOS: `~/Library/Application Support/Code/User/prompts/*.instructions.md`
- Windows: `%APPDATA%\Code\User\prompts\*.instructions.md`

Frontmatter:
- `applyTo` — glob (`"**/*.py"`, `"src/**,tests/**"`, `"**"` for always-on).
- `description` — tooltip.

```markdown
---
applyTo: "**/*.py"
description: "Python coding conventions"
---
- Always type-annotate public interfaces.
- Validate at boundaries; trust inside.
```

Identity: filename stem.

### Prompt files (`*.prompt.md`)

Invoked from chat as `/<name>` or via `Chat: Run Prompt`.

**Workspace**: `<repo>/.github/prompts/*.prompt.md` (configurable via `chat.promptFilesLocations`).
**User profile**: same `prompts/` folder.

Frontmatter:
- `description`, `name` (defaults to filename stem), `hint` (placeholder).
- `mode` (legacy) / `agent` (current) — `ask` | `edit` | `agent` | `plan` | `<custom-agent-name>`.
- `model` — e.g. `GPT-4.1`, `Claude Sonnet 4.5`.
- `tools` — array of tool / tool-set / MCP tool names; MCP wildcard `"<server>/*"`.

```markdown
---
description: "Security review of the current diff"
mode: agent
model: Claude Sonnet 4.5
tools: ["codebase", "githubRepo", "github/*"]
---
Run a security review on the staged diff. Focus on injection,
secret leakage, and authz. Output findings as a checklist.
```

### Custom chat modes / custom agents (`*.chatmode.md`, `*.agent.md`)

VS Code renamed "custom chat modes" to "custom agents" Oct 2025. **Both extensions still parsed**.

**Workspace**: `<repo>/.github/chatmodes/*.chatmode.md` and `<repo>/.github/agents/*.agent.md`. Configurable via `chat.modeFilesLocations`.
**User profile**: same `prompts/` folder, distinguished by extension.

Frontmatter: `description`, `tools`, `model`, `handoffs` (newer; each `{ agent, label, prompt? }`).

```markdown
---
description: "Plan-only mode: no edits, no tool calls that mutate"
tools: ["codebase", "search", "usages"]
model: GPT-4.1
---
You are in PLAN mode. Produce a step-by-step plan with verifiable
checkpoints. Do not modify files. Do not run terminal commands.
```

### AGENTS.md (cross-tool convention)

`<repo>/AGENTS.md` plus nested `AGENTS.md` files. Read by Copilot coding agent (Aug 2025) and Copilot CLI. Coexists with `.github/copilot-instructions.md`, `.github/instructions/**`, `CLAUDE.md`, `GEMINI.md` (all merged). Sync risk: file shared with Codex, Cursor, Aider, Claude Code, Gemini CLI — treat as **shared canonical**.

### MCP servers — VS Code

**Workspace**: `<repo>/.vscode/mcp.json` (use `inputs` block for secrets).
**User profile**:
- Linux: `~/.config/Code/User/mcp.json`
- macOS: `~/Library/Application Support/Code/User/mcp.json`
- Windows: `%APPDATA%\Code\User\mcp.json`

Open via command palette: `MCP: Open User Configuration` / `MCP: Open Workspace Folder Configuration`.

Schema (JSONC):
- `servers` — object, key = server name. Values:
  - stdio: `{ "type": "stdio", "command": "<cmd>", "args": [...], "env": {...}, "envFile": ".env" }`
  - http: `{ "type": "http", "url": "<url>", "headers": {...} }`
  - sse: `{ "type": "sse", "url": "<url>", "headers": {...} }`
  - Unix socket: `unix:///path/to/server.sock`; Windows named pipe: `pipe:///pipe/name`.
- `inputs` — array of VS Code prompts (`{ id, type: "promptString", description, password }`) referenced as `${input:<id>}`.
- Variables: `${workspaceFolder}`, `${env:VAR}`, `${input:id}`.

```jsonc
{
  "inputs": [
    { "id": "gh-token", "type": "promptString", "password": true,
      "description": "GitHub PAT" }
  ],
  "servers": {
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": { "Authorization": "Bearer ${input:gh-token}" }
    },
    "playwright": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"]
    }
  }
}
```

Sync risks: user-level `mcp.json` may carry resolved secrets; treat as **sensitive**, redact `headers`/`env`, never sync `inputs` resolutions.

### GitHub Copilot coding agent (cloud)

Repository-level, in-tree:
- `.github/copilot-instructions.md`
- `.github/instructions/**/*.instructions.md`
- `.github/agents/*.agent.md` — custom agents (frontmatter: `name`, `description`, `tools`, optional `mcp_servers`, optional handoffs).
- `AGENTS.md` (root + nested).
- Per-agent specific instructions (Nov 2025): `.github/instructions/<agent-name>.instructions.md`.
- `.github/workflows/copilot-*.yml` — workflow hooks.

The cloud agent has additional cloud-only settings at `https://github.com/<org>/<repo>/settings/copilot/coding_agent` (MCP servers, allowed actions, environment) NOT on disk.

### GitHub Copilot CLI

Uses `~/.copilot/` (override via `$COPILOT_HOME`):

| File / dir | Purpose |
|---|---|
| `~/.copilot/config.json` | Top-level config (JSONC) |
| `~/.copilot/settings.json` | Settings (model, theme, telemetry) |
| `~/.copilot/mcp-config.json` | User-level MCP servers |
| `~/.copilot/lsp-config.json` | LSP servers exposed to agent |
| `~/.copilot/agents/*.agent.md` | User-level custom agents |
| `~/.copilot/skills/<skill>/SKILL.md` | User-level agent skills |
| `~/.copilot/hooks/*` | User-level hook scripts |
| `~/.copilot/<state>/` | Auth, plugin metadata — **do not sync** |

Repo-level equivalents at `<repo>/.github/copilot/` (skills) and `<repo>/.github/agents/` (agents); MCP also reads `<repo>/.vscode/mcp.json`.

The older `gh copilot` extension uses `gh`'s own config under `~/.config/gh/` — only auth/host settings, **no user-authored prompts/instructions**.

### Visual Studio 2022

Reads the same `<repo>/.github/copilot-instructions.md` and `<repo>/.github/instructions/*.instructions.md`. Toggle: *Tools → Options → GitHub → Copilot → Copilot Chat → "Enable custom instructions..."*. `.vs/` carries no user-authored AI customization. VS-specific settings sync via the signed-in account, not on disk.

### VS Code Copilot settings keys (subset)

In `settings.json`:

```jsonc
{
  "github.copilot.enable": { "*": true, "markdown": false },
  "github.copilot.chat.codeGeneration.useInstructionFiles": true,
  "github.copilot.chat.codeGeneration.instructions": [
    { "text": "Use early returns." },
    { "file": "docs/style.md" }
  ],
  "github.copilot.chat.testGeneration.instructions": [],
  "github.copilot.chat.reviewSelection.instructions": [],
  "github.copilot.chat.reviewSelection.enabled": true,
  "github.copilot.chat.commitMessageGeneration.instructions": [],
  "github.copilot.chat.pullRequestDescriptionGeneration.instructions": [],
  "chat.promptFiles": true,
  "chat.promptFilesLocations": { ".github/prompts": true },
  "chat.instructionsFilesLocations": { ".github/instructions": true },
  "chat.modeFilesLocations": { ".github/chatmodes": true, ".github/agents": true },
  "chat.agent.enabled": true,
  "chat.mcp.enabled": true,
  "chat.tools.autoApprove": false
}
```

`*.instructions` arrays accept `{ "text": "..." }` or `{ "file": "<workspace-relative-path>" }`.

### Awesome-copilot (community convention)

`github/awesome-copilot` is the canonical community catalog. Layout: `instructions/`, `prompts/`, `chatmodes/`, `agents/`, `skills/<name>/SKILL.md`, `collections/`. Not a path Copilot itself reads — users vendor into their own `.github/` or `~/.copilot/`.

### Sync-risk summary

| Surface | Location | In-tree? | Secret risk | Cloud-overlap |
|---|---|---|---|---|
| `copilot-instructions.md` | repo | yes | none | — |
| `*.instructions.md` (workspace) | repo | yes | none | — |
| `*.instructions.md` (user) | VS Code profile | no | low | Settings Sync |
| `*.prompt.md` | both | repo: yes / user: no | low | Settings Sync |
| `*.chatmode.md` / `*.agent.md` | both | repo: yes / user: no | low | Settings Sync |
| `AGENTS.md` | repo | yes | none | shared with other tools |
| `.vscode/mcp.json` | repo | yes (use `inputs`) | medium | — |
| User `mcp.json` | VS Code profile | no | **high** | — |
| `~/.copilot/*` | home | no | medium-high | — |
| `settings.json` Copilot keys | both | repo: yes / user: no | low | Settings Sync |
| Coding-agent cloud config | github.com | n/a | n/a | **cloud-only** |

### Sources

- [Add repository custom instructions](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions-in-your-ide/add-repository-instructions-in-your-ide)
- [Support for different types of custom instructions](https://docs.github.com/en/copilot/reference/custom-instructions-support)
- [Custom instructions in VS Code](https://code.visualstudio.com/docs/copilot/customization/custom-instructions)
- [Prompt files in VS Code](https://code.visualstudio.com/docs/copilot/customization/prompt-files)
- [Custom chat modes](https://code.visualstudio.com/docs/copilot/customization/custom-chat-modes)
- [Custom agents in VS Code](https://code.visualstudio.com/docs/copilot/customization/custom-agents)
- [MCP configuration reference - VS Code](https://code.visualstudio.com/docs/copilot/reference/mcp-configuration)
- [Add and manage MCP servers in VS Code](https://code.visualstudio.com/docs/copilot/customization/mcp-servers)
- [Copilot settings reference](https://code.visualstudio.com/docs/copilot/reference/copilot-settings)
- [Copilot CLI configuration directory](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference)
- [Configuring GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/configure-copilot-cli)
- [Custom instructions for CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions)
- [Adding agent skills for CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills)
- [Custom agents configuration](https://docs.github.com/en/copilot/reference/custom-agents-configuration)
- [Coding agent supports AGENTS.md (changelog)](https://github.blog/changelog/2025-08-28-copilot-coding-agent-now-supports-agents-md-custom-instructions/)
- [Custom agents for GitHub Copilot (changelog)](https://github.blog/changelog/2025-10-28-custom-agents-for-github-copilot/)
- [Customize chat responses - Visual Studio](https://learn.microsoft.com/en-us/visualstudio/ide/copilot-chat-context?view=vs-2022)
- [github/awesome-copilot](https://github.com/github/awesome-copilot)

---

## Goose (Block)

Goose is Block's open-source on-machine AI agent, distributed as a terminal CLI (`goose`) and an Electron desktop app. User-authored customizations on disk fall into six categories: a single YAML config, a separate plaintext secrets file (only when the OS keyring is unavailable), a permission policy file, a recipe library, free-form `.goosehints` files, and the Memory Extension store. XDG on Unix; `%APPDATA%\Block\goose\` on Windows.

### Filesystem layout per OS

| Asset | Linux | macOS | Windows |
|---|---|---|---|
| Main config | `~/.config/goose/config.yaml` | `~/.config/goose/config.yaml` | `%APPDATA%\Block\goose\config\config.yaml` |
| Secrets (fallback) | `~/.config/goose/secrets.yaml` (0600) | same | `%APPDATA%\Block\goose\config\secrets.yaml` |
| Permissions | `~/.config/goose/permission.yaml` | same | `%APPDATA%\Block\goose\config\permission.yaml` |
| Tool permission cache | `~/.config/goose/permissions/tool_permissions.json` | same | `%APPDATA%\Block\goose\config\permissions\tool_permissions.json` |
| Recipe library (global) | `~/.config/goose/recipes/*.{yaml,json}` | same | `%APPDATA%\Block\goose\config\recipes\` |
| Project-local recipes | `./.goose/recipes/` | same | same |
| Global hints | `~/.config/goose/.goosehints` and `~/.goosehints` | same | `%APPDATA%\Block\goose\config\.goosehints` |
| Project hints | `<project>/.goosehints`, `<project>/.goosehints.local` | same | same |
| Memory store (global) | `~/.config/goose/memory/<category>.txt` | same | `%APPDATA%\Block\goose\config\memory\` |
| Memory store (project) | `<project>/.goose/memory/<category>.txt` | same | same |
| Sessions (state, out of scope) | `~/.local/share/goose/sessions/sessions.db` | same | `%LOCALAPPDATA%\Block\goose\data\sessions\` |
| Logs (state) | `~/.local/state/goose/logs/` | same | `%LOCALAPPDATA%\Block\goose\state\logs\` |

Recipes also resolve via env: `GOOSE_RECIPE_PATH` (colon-separated extra dirs) and `GOOSE_RECIPE_GITHUB_REPO`.

### Settings — `config.yaml`

```yaml
GOOSE_PROVIDER: anthropic
GOOSE_MODEL: claude-4.5-sonnet
GOOSE_TEMPERATURE: 0.7
GOOSE_MODE: smart_approve              # auto | approve | smart_approve | chat
GOOSE_PLANNER_PROVIDER: openai
GOOSE_PLANNER_MODEL: gpt-4o
GOOSE_LEAD_PROVIDER: anthropic
GOOSE_LEAD_MODEL: claude-4.5-sonnet
GOOSE_WORKER_PROVIDER: openai
GOOSE_WORKER_MODEL: gpt-4o-mini
GOOSE_TOOLSHIM: false
GOOSE_CONTEXT_STRATEGY: summarize      # truncate|summarize|clear
GOOSE_MAX_TURNS: 100
GOOSE_RECIPE_GITHUB_REPO: myorg/recipes
GOOSE_DISABLE_KEYRING: false
extensions: { ... }
```

### Extensions — MCP servers, builtins, and remotes

Goose's unified abstraction over MCP servers and bundled tools. Six `type` values: `stdio`, `streamable_http`, `sse`, `builtin`, `platform`, `frontend`, `inline_python`.

```yaml
extensions:
  developer:
    name: developer
    type: builtin
    display_name: Developer
    enabled: true
    bundled: true
    timeout: 300
  memory:
    name: memory
    type: builtin
    enabled: true
    bundled: true
  github:
    name: github
    type: stdio
    enabled: true
    cmd: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    description: GitHub MCP server
    env_keys: ["GITHUB_PERSONAL_ACCESS_TOKEN"]
    envs:
      LOG_LEVEL: info
    timeout: 300
  figma_remote:
    name: figma_remote
    type: streamable_http
    enabled: true
    uri: http://127.0.0.1:3845/mcp
    headers:
      Authorization: "Bearer ${FIGMA_TOKEN}"
    timeout: 120
```

Identity: map key (must equal `name`). Sync risk: `env_keys` references secrets that live in the OS keyring or in `secrets.yaml`; `cmd` for stdio often contains absolute paths.

### Recipes — reusable agent configurations

First-class portable artifacts. `*.yaml` or `*.json`. Discovery order for `goose run --recipe <name>`:

1. CWD
2. Each dir in `GOOSE_RECIPE_PATH`
3. Global `~/.config/goose/recipes/`
4. Project-local `./.goose/recipes/`
5. GitHub fallback at `https://github.com/$GOOSE_RECIPE_GITHUB_REPO/blob/main/<name>/recipe.yaml`

```yaml
version: "1.0.0"
title: "Code Review Agent"
description: "Reviews a PR diff..."
instructions: |
  You are a senior reviewer. Apply {{ style_guide }} ...
prompt: "Review PR #{{ pr_number }}"
author:
  contact: "alice@example.com"
parameters:
  - key: pr_number
    input_type: string
    requirement: required
  - key: style_guide
    input_type: select
    requirement: optional
    default: "google"
    options: ["google", "pep8", "airbnb"]
extensions:
  - type: builtin
    name: developer
  - type: stdio
    name: github
    cmd: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env_keys: ["GITHUB_PERSONAL_ACCESS_TOKEN"]
activities:
  - "Summarise the diff"
sub_recipes:
  - name: lint_check
    path: ./lint.yaml
    values:
      language: "{{ language }}"
response:
  json_schema:
    type: object
    required: [verdict, comments]
    properties:
      verdict: { type: string, enum: [approve, request_changes, comment] }
      comments: { type: array, items: { type: string } }
retry:
  max_retries: 3
  timeout_seconds: 600
  checks:
    - type: shell
      command: "pytest -x"
  on_failure:
    - type: shell
      command: "git stash"
settings:
  goose_provider: anthropic
  goose_model: claude-4.5-sonnet
  temperature: 0.2
  max_turns: 40
```

Identity: filename stem. Jinja2 `{{ param }}` applied to `instructions`, `prompt`, `activities`, sub-recipe `values`.

### Custom modes / personas

Not a first-class concept. The equivalent is a **recipe**: focused `instructions` + `extensions` allowlist + pinned `settings` = persona. `GOOSE_MODE` selects approval policy, not persona.

### MCP servers — relationship to extensions

No separate `mcp_servers:` block. Every MCP server is an `extensions:` entry of `type: stdio` / `streamable_http` / `sse`.

### Memory: `.goosehints` and the Memory Extension

**`.goosehints`** — static text/Markdown appended to system prompt every turn. Lookup order (highest first): `<project>/.goosehints.local`, `~/.goosehints` (or `~/.config/goose/.goosehints`), `<project>/.goosehints`, `<project>/.goosehints.default`. Free-form.

**Memory Extension** — `memory` builtin stores categorised text snippets. `~/.config/goose/memory/<category>.txt` (global) or `<project>/.goose/memory/<category>.txt` (project). Plain text, one entry per block, optional `#tag` lines. Identity: filename stem.

### Secrets and permissions

`secrets.yaml` — created only when `GOOSE_DISABLE_KEYRING=true` or no keyring available. Plain YAML at mode 0600. Otherwise secrets sit in macOS Keychain / Windows Credential Manager / Linux Secret Service under service `goose`. **Never sync `secrets.yaml`.**

`permission.yaml` — tool-level approval policy. Human-editable. `permissions/tool_permissions.json` is auto-managed runtime cache — do not sync.

### Other on-disk user-authored data

- `~/.config/goose/scheduler/` — scheduled-recipe definitions (cron-style YAML).
- `./.goose/` — project tree (`recipes/`, `memory/`, `.goosehints.local`).

### Cross-cutting sync risks

1. **Absolute paths** in extension `cmd` (Homebrew vs system Python vs Windows `.cmd`).
2. **Secrets coupling** — `env_keys` names sync; actual secret store does not.
3. **Builtin vs bundled** drifts between Goose versions; `bundled: true` is informational.
4. **Windows path mapping** — `%APPDATA%\Block\goose\config\` vs `~/.config/goose/`.
5. **Sessions/logs are state** — `~/.local/share/goose/`, `~/.local/state/goose/`.
6. **`.goosehints` precedence** — `.goosehints.local` is per-machine by design.

### Sources

- [Configuration File](https://block.github.io/goose/docs/guides/config-file/)
- [Recipe Reference Guide](https://block.github.io/goose/docs/guides/recipes/recipe-reference/)
- [Saving Recipes](https://block.github.io/goose/docs/guides/recipes/storing-recipes/)
- [Sub-Recipes](https://block.github.io/goose/docs/guides/recipes/sub-recipes/)
- [Extensions](https://block.github.io/goose/v1/extensions/)
- [Memory Extension](https://block.github.io/goose/docs/tutorials/memory-mcp/)
- [What's in my .goosehints file](https://block.github.io/goose/blog/2025/06/05/whats-in-my-goosehints-file/)
- [Logging System](https://block.github.io/goose/docs/guides/logs/)
- [Managing Sessions](https://block.github.io/goose/docs/guides/managing-goose-sessions/)
- [block/goose recipe.yaml](https://github.com/block/goose/blob/main/recipe.yaml)
- [Issue #2560 — GOOSE_RECIPE_PATH](https://github.com/block/goose/issues/2560)
- [Extension Types and Configuration (DeepWiki)](https://deepwiki.com/block/goose/5.3-extension-types-and-configuration)
- [Provider Configuration (DeepWiki)](https://deepwiki.com/block/goose/2.2-provider-configuration)
- [File Access Controls (DeepWiki)](https://deepwiki.com/block/goose/6.3-file-access-controls)

---

## Google Gemini CLI & Antigravity

Google's `gemini-cli` (npm; `google-gemini/gemini-cli` on GitHub) and **Google Antigravity** (Google's agent-native IDE) share much of the same configuration root: `~/.gemini/`. Antigravity additionally reads from `~/.gemini/antigravity/` for IDE-specific assets (notably skills) and reads its workspace overrides from `<workspace>/.agent/`. The format of `settings.json` was reorganized into nested category objects on 2025-09-17, with auto-migration from the legacy flat shape.

OS-specific roots:
- Linux: `~/.gemini/`
- macOS: `~/.gemini/`
- Windows: `%USERPROFILE%\.gemini\`. System-wide settings: `%ProgramData%\gemini-cli\settings.json`.

Per-project overrides under `<project>/.gemini/`. Antigravity workspace skills under `<project>/.agent/skills/`.

### Agents (subagents / personas)

Gemini CLI added first-class subagents in 2025. Markdown with YAML frontmatter.

- User: `~/.gemini/agents/<agent-name>.md`
- Project: `<project>/.gemini/agents/<agent-name>.md`

Frontmatter: `name` (identity, must match filename stem in practice), `description` (used by router LLM), `tools` (optional allowed-tool list), `model` (optional; `inherit` or specific Gemini model id), plus optional `kind`, `temperature`, `max_turns`. Body is the system prompt.

```markdown
---
name: readme-architect
description: Analyzes a repo and writes a professional README.md.
tools:
  - read_file
  - glob
model: inherit
---
You are a documentation specialist. When invoked...
```

Sync risks: filename/`name` drift; `tools` referring to extension-provided tools absent on target host.

### Skills

First-class in Antigravity; same SKILL.md format used by Gemini CLI through `creating-skills`.

- Antigravity, global: `~/.gemini/antigravity/skills/<skill-name>/SKILL.md`
- Antigravity, workspace: `<project>/.agent/skills/<skill-name>/SKILL.md` (workspace precedence over global)
- Gemini CLI: same `~/.gemini/antigravity/skills/` location is read; some installs also use `~/.gemini/skills/`. Extensions may bundle skills under `~/.gemini/extensions/<ext>/skills/`.
- Windows: `%USERPROFILE%\.gemini\antigravity\skills\<skill-name>\SKILL.md`.

Required frontmatter: `name` (must match parent folder), `description` (should start "Use when..."). Optional: `allowed-tools`. Skill folder may include `scripts/`, `references/`, `assets/`.

```
~/.gemini/antigravity/skills/pdf-extract/
├── SKILL.md
├── scripts/extract.py
└── references/layout.md
```

```markdown
---
name: pdf-extract
description: Use when the user wants to extract text or tables from PDF files.
allowed-tools:
  - read_file
  - run_shell_command
---
# PDF extraction
...
```

### Custom commands (slash commands)

TOML files under `commands/`. Subdirectories namespace using `:` (path separator `/` or `\` → `:`).

- User: `~/.gemini/commands/<name>.toml` → `/<name>`
- User namespaced: `~/.gemini/commands/git/commit.toml` → `/git:commit`
- Project: `<project>/.gemini/commands/...` (overrides user)

Fields: `prompt` (required), `description` (optional).

Placeholders inside `prompt`:
- `{{args}}` — interpolated raw user input; auto shell-escaped inside `!{...}`.
- `!{shell command}` — runs shell, inlines stdout.
- `@{path/to/file-or-dir}` — inlines file content or directory listing; respects `.gitignore`/`.geminiignore`.

```toml
description = "Summarize the current git diff."
prompt = """
Summarize the following diff for a PR description.

```diff
!{git diff --staged}
```

Focus area: {{args}}
"""
```

### Extensions

`~/.gemini/extensions/<extension-name>/` (user) or `<project>/.gemini/extensions/<extension-name>/` (project). Required manifest: `gemini-extension.json`. Optional: `GEMINI.md`, `hooks/`, `skills/`, `commands/`, `.env`, `.install-metadata.json`.

Manifest key fields: `name`, `version`, `description`, `mcpServers` (same shape as top-level; supports `${extensionPath}`), `contextFileName`, `excludeTools`, `migratedTo`, `plan.directory`, `settings` (array of `{ name, description, env, sensitive }`).

```json
{
  "name": "my-ext",
  "version": "1.0.0",
  "description": "Adds an internal docs MCP server.",
  "mcpServers": {
    "docs": {
      "command": "node",
      "args": ["${extensionPath}/server.js"],
      "cwd": "${extensionPath}"
    }
  },
  "contextFileName": "GEMINI.md",
  "excludeTools": ["run_shell_command"],
  "settings": [
    { "name": "API token", "env": "DOCS_API_TOKEN", "sensitive": true }
  ]
}
```

Sync risks: `mcpServers` inside extensions may duplicate top-level entries; `.env` and OS keychain are auth-bearing — **out of scope**; `.install-metadata.json` is per-host bookkeeping.

### MCP server configs

Top-level entry inside `~/.gemini/settings.json` under `mcpServers`. Same shape may be embedded in extension manifest. Three transports:

- **stdio**: `command`, `args`, `cwd`, `env` (with `${VAR}` expansion), `includeTools`/`excludeTools`, `timeout` (ms), `trust`.
- **SSE**: `url`.
- **Streamable HTTP**: `httpUrl`, `headers`, `timeout`.

```json
{
  "mcpServers": {
    "github": {
      "httpUrl": "https://api.githubcopilot.com/mcp/",
      "headers": { "Authorization": "Bearer ${GITHUB_PAT}" },
      "timeout": 30000,
      "trust": false
    },
    "fs": {
      "command": "uvx",
      "args": ["mcp-server-filesystem", "/home/me"],
      "env": { "LOG_LEVEL": "info" }
    }
  }
}
```

Discovered tools prefixed `mcp_<alias>_<tool>`.

### Memory / instructions (GEMINI.md)

- Global: `~/.gemini/GEMINI.md`
- Project: `<project>/GEMINI.md` (walk up to git root)
- Subdirectory: `<project>/<subdir>/GEMINI.md`

CLI concatenates all discovered files every prompt. Imports use `@file.md`. Built-in: `/memory show`, `/memory refresh`, `/memory add <text>` (appends to `~/.gemini/GEMINI.md`).

Per-extension memory: each extension may ship its own `GEMINI.md` (or whatever `contextFileName` is). The user-scope `~/.gemini/GEMINI.md` is the right unit to sync.

### Settings (`~/.gemini/settings.json`)

Post-Sept-2025 layout groups keys under category objects. Schema at `https://raw.githubusercontent.com/google-gemini/gemini-cli/main/schemas/settings.schema.json`. Known keys:

- `model` — default Gemini model id.
- `ui` — `theme`, `customThemes`, `preferredEditor`, `hideTips`, `accessibility`.
- `context` — `contextFileName`, `fileFiltering` `{ respectGitIgnore, enableRecursiveFileSearch, respectGeminiIgnore }`.
- `tools` — `autoAccept`, `sandbox` (`false`|`true`|`"docker"`|`"podman"`), `toolDiscoveryCommand`, `toolCallCommand`, `coreTools`, `excludeTools`.
- `mcp` — `serverDiscoveryTimeout`, plus top-level `mcpServers`.
- `telemetry` — `{ enabled: false, target: "local"|"gcp", otlpEndpoint, logPrompts }`.
- `checkpointing` — `{ enabled: true }`. Enables `/restore`.
- `usageStatisticsEnabled` (bool).
- `security`.
- `hooks`.

Precedence: system < user < project < extensions (lowest for hooks).

### Hooks

Under `settings.json -> hooks` (or extension manifest). Events: `PreToolUse`, `PostToolUse`, `SessionStart`, plus other lifecycle events. Each maps to an array; hooks communicate via stdin/stdout JSON.

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "run_shell_command", "command": "~/.gemini/hooks/audit.sh" }
    ]
  }
}
```

### Auth / credentials (out of scope)

`~/.gemini/.env` (user) or `<project>/.env` (project) hold `GEMINI_API_KEY`. Extension-managed `sensitive` settings in OS keychain.

### Sandbox / tools

`settings.json -> tools.sandbox`. Default image `gcr.io/gemini-code-dev/sandbox` under Docker or Podman. `coreTools`/`excludeTools` gate built-ins. Project may add `<project>/.geminiignore`.

### Everything else under `~/.gemini/`

- `oauth_creds.json`, `google_account_id`, `installation_id` — auth + telemetry (do NOT sync).
- `tmp/`, `checkpoints/`, `logs/` — runtime (skip).
- `antigravity/` — Antigravity-only assets.

### Summary

In-scope: `agents/*.md`, `antigravity/skills/<name>/`, `commands/**/*.toml`, `extensions/<name>/` (minus `.env`, `.install-metadata.json`, keychain settings), `settings.json` (with `mcpServers` and `hooks`; redact `Authorization` and secret env), `GEMINI.md`.

Out of scope: `.env`, `oauth_creds.json`, `google_account_id`, `installation_id`, `tmp/`, `checkpoints/`, `logs/`.

### Sources

- [google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli)
- [Gemini CLI configuration reference](https://geminicli.com/docs/reference/configuration/)
- [Basic configuration (official)](https://google-gemini.github.io/gemini-cli/docs/get-started/configuration.html)
- [Custom commands (official)](https://google-gemini.github.io/gemini-cli/docs/cli/custom-commands.html)
- [Custom commands (geminicli.com)](https://geminicli.com/docs/cli/custom-commands/)
- [Custom slash commands (Google Cloud Blog)](https://cloud.google.com/blog/topics/developers-practitioners/gemini-cli-custom-slash-commands)
- [Extensions reference](https://geminicli.com/docs/extensions/reference/)
- [Build Gemini CLI extensions](https://geminicli.com/docs/extensions/writing-extensions/)
- [MCP servers with Gemini CLI](https://geminicli.com/docs/tools/mcp-server/)
- [GEMINI.md (official)](https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html)
- [Memory tool](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/memory.md)
- [Hooks](https://geminicli.com/docs/hooks/)
- [Hooks reference](https://geminicli.com/docs/hooks/reference/)
- [Subagents (official)](https://github.com/google-gemini/gemini-cli/blob/main/docs/core/subagents.md)
- [Subagents (geminicli.com)](https://geminicli.com/docs/core/subagents/)
- [Google Antigravity Agent Skills](https://antigravity.google/docs/skills)
- [Authoring Antigravity Skills (codelab)](https://codelabs.developers.google.com/getting-started-with-antigravity-skills)
- [Where Gemini CLI stores configuration](https://inventivehq.com/knowledge-base/gemini/where-configuration-files-are-stored)
- [settings.schema.json](https://fossies.org/linux/gemini-cli/schemas/settings.schema.json)

---

## JetBrains Junie & AI Assistant

JetBrains ships two distinct AI products: **Junie** (agentic coding agent — IDE plugin + standalone CLI) and **AI Assistant** (in-IDE chat / inline-completion / Prompt Library / rules). They share a common IDE config substrate (`*.xml` in the IDE config dir) but have diverged file conventions for portable, repo-checkable artifacts. Junie has aggressively adopted the open `.junie/` + `AGENTS.md` + Markdown convention; AI Assistant has adopted a parallel `.aiassistant/` directory plus the older Settings-stored Prompt Library.

For a sync tool, the **portable** units (Markdown/JSON) sync cleanly; the **IDE-state** units (XML under `<JetBrainsConfig>/<Product><Version>/options/`) do not — directory name is per-product **and** per-IDE-version (`IntelliJIdea2024.3`, `PyCharm2025.1`), and the schema is undocumented private XML.

### Project guidelines (Junie + shared with AI Assistant)

Junie reads, in priority order:

1. Custom path set in `Settings | Tools | Junie | Project Settings`
2. `.junie/AGENTS.md` (preferred, current standard)
3. `AGENTS.md` at project root (fallback)
4. Legacy: `.junie/guidelines.md`, or a `.junie/guidelines/` directory of fragments

No documented user-level/global guidelines file — JetBrains tracks "Unified AI guidelines file" as `LLM-26006` (open). AI Assistant honors the same `AGENTS.md` when used together with Junie; its primary instruction surface is `.aiassistant/rules/`.

```
<projectRoot>/
  .junie/
    AGENTS.md            # preferred
    guidelines.md        # legacy
    guidelines/*.md      # legacy multi-file
  AGENTS.md              # fallback
```

Sync risk: low. `AGENTS.md` is shared with Codex / Cursor / Aider / Claude Code, so multi-tool projects need disambiguation.

### Custom prompts / slash commands

**Junie** (CLI and IDE plugin share format) — Markdown with YAML frontmatter:

```
<projectRoot>/.junie/commands/<name>.md     # project-scope
~/.junie/commands/<name>.md                 # user-scope (macOS/Linux)
%USERPROFILE%\.junie\commands\<name>.md     # user-scope (Windows)
```

```markdown
---
description: Run the project test suite and summarize failures
argument-hint: <test-path>
---
Run `uv run pytest {{test-path}}` and report …
```

**AI Assistant** — the **Prompt Library** is stored as IDE-state XML (not portable Markdown). Lives in IDE config dir under `options/` (e.g. `aiAssistantPromptLibrary.xml` / `ai.assistant.xml`-family):

```xml
<application>
  <component name="AIAssistantPromptLibrary">
    <prompt name="Explain this code" template="Explain $SELECTION ..."/>
  </component>
</application>
```

`$SELECTION` is documented placeholder. Sync risk: **high** — XML schema is private, files are per-version, third-party plugin "Export AI Assistant Prompt" exists precisely because format is not portable.

### MCP servers

**Junie** uses a JSON file with Claude-Desktop-compatible `mcpServers` schema:

```
<projectRoot>/.junie/mcp/mcp.json   # project
~/.junie/mcp/mcp.json               # user (Linux/macOS)
%USERPROFILE%\.junie\mcp\mcp.json   # user (Windows)
```

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
    }
  }
}
```

Transports: STDIO, Streamable HTTP, SSE (legacy).

**AI Assistant** MCP (`Settings | Tools | AI Assistant | Model Context Protocol (MCP)`) uses the same JSON shape (UI accepts paste-from-Claude-Desktop) but **persisted as IDE-state XML** in IDE config dir. Per-server "Server level" toggle selects global vs project. Sync risk: **high** for global (XML, per-IDE-version); project-scope rows often serialize into `.idea/` workspace XML (conventionally git-ignored).

### Custom instructions / project rules (AI Assistant)

Markdown files mirroring Cursor's `.cursor/rules/`:

```
<projectRoot>/.aiassistant/rules/<rule-name>.md
```

Authored via `Settings | Tools | AI Assistant` → *New Project Rules File*. Plain Markdown — heading + bullets.

AI Assistant also honors agent-specific instruction files when the corresponding backend is selected: `AGENTS.md`, `CLAUDE.md` + `.claude/` (when Claude Agent ACP backend selected).

### IDE settings (XML, the brittle layer)

```
Linux:   ~/.config/JetBrains/<Product><Version>/
macOS:   ~/Library/Application Support/JetBrains/<Product><Version>/
Windows: %APPDATA%\JetBrains\<Product><Version>\
```

Examples: `IntelliJIdea2025.1`, `PyCharm2025.1`, `WebStorm2025.1`, `GoLand2025.1`, `RustRover2025.1`, `CLion2025.1`, `Rider2025.1`, `RubyMine2025.1`, `PhpStorm2025.1`, `DataGrip2025.1`, `AndroidStudio2025.1.1` (Google fork — slightly different layout).

AI-relevant files in `options/`:

| File | Owner | Contents |
|---|---|---|
| `options/llm.xml` | AI Assistant | JWT token, model selection, provider config |
| `options/aiAssistantPromptLibrary.xml` (`ai.assistant.xml`) | AI Assistant | Prompt Library |
| `options/mcp.xml` (or merged into AI Assistant XML) | AI Assistant | MCP server entries (global) |
| `options/junie.xml` | Junie IDE plugin | Plugin preferences |
| `options/models.xml` (system dir `full-line/models/`) | Full-line completion | Local model registry |

Sync risk: **high**. Version segment means user on IDEA 2024.3 + PyCharm 2025.1 has two distinct copies of every XML; private schemas; some embed JWT tokens or absolute paths. Treat IDE-state XML as **read-only / opt-in**; prefer portable surfaces.

Project-local IDE state in `<projectRoot>/.idea/` and `<projectRoot>/.idea/workspace.xml`.

### AGENTS.md support — confirmed

Junie reads `AGENTS.md` (project root) and `.junie/AGENTS.md` natively. YouTrack `JUNIE-618` resolved. `JUNIE-2381` (`.agents/` directory convention) open. AI Assistant honors `AGENTS.md` indirectly when running the Junie agent.

### Other user-authored on-disk surfaces

**Junie agent skills** — Anthropic-style folder bundles:

```
<projectRoot>/.junie/skills/<skill-name>/   # project scope
~/.junie/skills/<skill-name>/               # user scope (macOS/Linux)
%USERPROFILE%\.junie\skills\<skill-name>\   # user scope (Windows)
```

Each skill: `SKILL.md` (frontmatter + body) plus optional supporting files. The **Skill Manager** (April 2026) adds IDE-wide layer; **Skill Repository** is JetBrains-curated, security-screened.

**Junie subagents** — `<projectRoot>/.junie/agents/<agent>.md`, analogous to Claude Code's `.claude/agents/`.

**Junie Action Allowlist** — `~/.junie/allowlist.json` (user-scope). Categories: `fileEditing`, `executables`, `mcpTools`, `readOutsideProject`. **Security boundary** — sync requires careful merge, not blind overwrite.

**Junie CLI general settings** — `~/.junie/config.json` (user-scope).

**Junie memory** — persisted under `.junie/` (project) and `~/.junie/` (user). User-scope is private/per-machine.

**JetBrains MCP Server plugin** — the inverse direction. Out of scope.

### Summary

| Artifact | Tool | Path (Linux/macOS) | Format | Scope | Sync? |
|---|---|---|---|---|---|
| `AGENTS.md` / `.junie/AGENTS.md` | Junie (+AI Asst) | project | MD | project | yes |
| `.junie/commands/*.md` | Junie | project + `~/.junie/commands/` | MD+YAML | both | yes |
| `.junie/skills/<name>/` | Junie | project + `~/.junie/skills/` | folder | both | yes |
| `.junie/agents/*.md` | Junie | project | MD+YAML | project | yes |
| `.junie/mcp/mcp.json` | Junie | project + `~/.junie/mcp/mcp.json` | JSON | both | yes (strip secrets) |
| `~/.junie/allowlist.json` | Junie | `~/.junie/` | JSON | user | careful merge |
| `~/.junie/config.json` | Junie | `~/.junie/` | JSON | user | yes |
| `.aiassistant/rules/*.md` | AI Assistant | project | MD | project | yes |
| Prompt Library | AI Assistant | `<IDEConfig>/options/*.xml` | XML | per-IDE-version | no (brittle) |
| MCP global | AI Assistant | `<IDEConfig>/options/*.xml` | XML | per-IDE-version | no (brittle) |
| `llm.xml` | AI Assistant | `<IDEConfig>/options/llm.xml` | XML | per-IDE-version | no |
| `junie.xml` | Junie plugin | `<IDEConfig>/options/junie.xml` | XML | per-IDE-version | no |

Windows: substitute `%APPDATA%\JetBrains\<Product><Version>\` and `%USERPROFILE%\.junie\`.

### Sources

- [Guidelines | Junie](https://www.jetbrains.com/help/junie/customize-guidelines.html)
- [Guidelines and memory | Junie](https://junie.jetbrains.com/docs/guidelines-and-memory.html)
- [Junie by JetBrains | AI Assistant](https://www.jetbrains.com/help/ai-assistant/junie-agent.html)
- [Custom slash commands | Junie](https://junie.jetbrains.com/docs/custom-slash-commands.html)
- [Custom subagents | Junie](https://junie.jetbrains.com/docs/junie-cli-subagents.html)
- [Agent skills | Junie](https://junie.jetbrains.com/docs/agent-skills.html)
- [Junie CLI configuration files](https://junie.jetbrains.com/docs/junie-cli-configuration.html)
- [Add and configure MCP servers | Junie](https://junie.jetbrains.com/docs/junie-cli-mcp-configuration.html)
- [MCP | Junie](https://www.jetbrains.com/help/junie/model-context-protocol-mcp.html)
- [Action Allowlist | Junie](https://www.jetbrains.com/help/junie/action-allowlist.html)
- [Project Settings | Junie](https://www.jetbrains.com/help/junie/project-settings.html)
- [MCP | AI Assistant](https://www.jetbrains.com/help/ai-assistant/mcp.html)
- [Configure an MCP server | AI Assistant](https://www.jetbrains.com/help/ai-assistant/configure-an-mcp-server.html)
- [Configure project rules | AI Assistant](https://www.jetbrains.com/help/ai-assistant/configure-project-rules.html)
- [Agent instructions | AI Assistant](https://www.jetbrains.com/help/ai-assistant/configure-agent-behavior.html)
- [Add and customize prompts | AI Assistant](https://www.jetbrains.com/help/ai-assistant/prompt-library.html)
- [Prompt Library | AI Assistant](https://www.jetbrains.com/help/ai-assistant/settings-reference-prompt-library.html)
- [AI Assistant settings reference](https://www.jetbrains.com/help/ai-assistant/settings-reference-ai-assistant.html)
- [Directories used by the IDE](https://www.jetbrains.com/help/idea/directories-used-by-the-ide-to-store-settings-caches-plugins-and-logs.html)
- [Skill Manager and Skill Repository (blog)](https://blog.jetbrains.com/ai/2026/04/skill-manager-and-skill-repository/)
- [YouTrack JUNIE-618 Support AGENTS.md](https://youtrack.jetbrains.com/projects/JUNIE/issues/JUNIE-618)
- [YouTrack JUNIE-2381 Support .agents directory](https://youtrack.jetbrains.com/projects/JUNIE/issues/JUNIE-2381)
- [YouTrack LLM-26006 Unified AI guidelines file](https://youtrack.jetbrains.com/projects/LLM/issues/LLM-26006)

---

## Kilo Code

Kilo Code is an open-source VS Code extension AI coding agent that emerged from a merge of Cline and Roo Code. Almost all of its user-authored on-disk customization conventions are inherited directly from Roo Code — only the directory and file *names* change (`.roo` → `.kilocode`, `.roomodes` → `.kilocodemodes`, `rooignore` → `kilocodeignore`). Where applicable, "same as Roo Code" is called out. Project is in flux — a newer "Kilo CLI" / Opencode-based runtime (v7+) is migrating configuration to `kilo.jsonc` under `~/.config/kilo/`, but the VS Code extension still reads the legacy `.kilocode/...` layout.

### Custom Modes

Same shape as Roo Code, renamed files.

**Project-level**: `<project>/.kilocodemodes` (YAML at workspace root, not `.kilomodes`, not in `.kilocode/`).

**Global (extension)**:
- Linux: `~/.config/Code/User/globalStorage/kilocode.kilo-code/settings/custom_modes.yaml`
- macOS: `~/Library/Application Support/Code/User/globalStorage/kilocode.kilo-code/settings/custom_modes.yaml`
- Windows: `%APPDATA%\Code\User\globalStorage\kilocode.kilo-code\settings\custom_modes.yaml`
- Override via `kilo-code.customStoragePath`.

**Global (CLI runtime, newer)**: `~/.kilocode/cli/global/settings/custom_modes.yaml`.

**Precedence**: project `.kilocodemodes` overrides global by `slug`.

```yaml
customModes:
  - slug: docs-writer
    name: "📝 Documentation Writer"
    description: "A mode for technical docs."
    roleDefinition: |
      You are a technical writer specializing in clear documentation.
    whenToUse: "When writing or editing docs."
    customInstructions: "Focus on clarity."
    groups:
      - read
      - - edit
        - fileRegex: \.(md|mdx)$
          description: Markdown files only
      - browser
      - command
      - mcp
    source: global
```

`groups`: `read`, `edit` (optionally `[edit, { fileRegex, description }]`), `browser`, `command`, `mcp`. Sync risk: YAML anchors/comments preserved by Roo/Kilo readers; JSON-roundtrip would lose them.

### Rules

Same as Roo Code; only the directory name differs.

**Project-level:**
- `<project>/.kilocode/rules/*.md` — applies to every mode.
- `<project>/.kilocode/rules-<mode-slug>/*.md` — mode-specific.
- Legacy `<project>/.kilocoderules` accepted (deprecated).
- `AGENTS.md` at any level also honoured.

**Global:**
- `~/.kilocode/rules/*.md` — all projects.
- `~/.kilocode/rules-<mode-slug>/*.md`.

Plain Markdown, one rule per file; concatenated in filesystem order.

```markdown
# .kilocode/rules/01-style.md
- Always use type hints on public Python functions.
- Use `uv` for dependency management.
- Prefer `ruff format` over `black`.
```

The old "Memory Bank" feature (`.kilocode/rules/memory-bank/*.md` + `memory-bank-instructions.md`) is deprecated in favour of `AGENTS.md`, but existing files keep working.

### Workflows

Same as Roo Code:
- Project: `<project>/.kilocode/workflows/*.md`
- Global: `~/.kilocode/workflows/*.md`

```markdown
---
description: Submit a pull request with checks
agent: code
---
You are helping submit a pull request.
1. Run `uv run pytest`.
2. Run `ruff check`.
3. Open the PR with `gh pr create`.
```

Invocation: `/<filename-without-.md>`. Newer CLI migrates these to `.kilo/commands/` (project) and `~/.config/kilo/commands/` (global) on startup, but the extension still reads the legacy path.

### MCP Servers

Same shape as Roo Code; the global file is in a different `globalStorage` directory (`kilocode.kilo-code` vs `rooveterinaryinc.roo-cline`).

**Project**: `<project>/.kilocode/mcp.json` — committed.
**Global (extension)**:
- Linux: `~/.config/Code/User/globalStorage/kilocode.kilo-code/settings/mcp_settings.json`
- macOS: `~/Library/Application Support/Code/User/globalStorage/kilocode.kilo-code/settings/mcp_settings.json`
- Windows: `%APPDATA%\Code\User\globalStorage\kilocode.kilo-code\settings\mcp_settings.json`

Project overrides global on same server name. Schema identical to Roo/Cline:

```json
{
  "mcpServers": {
    "local-server": {
      "command": "node",
      "args": ["/path/to/server.js"],
      "env": { "API_KEY": "${env:API_KEY}" },
      "alwaysAllow": ["tool1", "tool2"],
      "disabled": false,
      "timeout": 180
    },
    "remote-sse": {
      "type": "sse",
      "url": "https://example.com/mcp",
      "headers": { "Authorization": "Bearer …" },
      "alwaysAllow": [],
      "disabled": false
    }
  }
}
```

### Custom Slash Commands

VS Code extension does **not** yet have a first-class user-defined slash command system — issue #6949 tracks it. "Slash commands" today are workflows (§Workflows) invoked via `/<workflow-name>`, plus built-in commands. In the newer Kilo CLI, user commands live at `<project>/.kilo/commands/*.md` and `~/.config/kilo/commands/*.md`.

### Memory Bank / Context

- **Memory Bank**: deprecated; `.kilocode/rules/memory-bank/*.md` + `memory-bank-instructions.md`. Treat as ordinary project rules.
- **AGENTS.md**: open-standard plain-Markdown. Shared with Cursor, Windsurf, others.
- **`.kilocodeignore`** (project root): `.gitignore`-syntax denylist.

### Settings (VS Code keys)

Under `kilo-code.*` namespace. Notable user-authored keys:

- `kilo-code.apiProvider` — selected model provider id.
- `kilo-code.customStoragePath` — overrides globalStorage base.
- `kilo-code.allowedCommands` — terminal commands the agent may run without confirmation.
- Provider-specific keys (`kilo-code.<provider>.apiKey`, base URLs, etc.) — secrets, do not sync.

Per-OS `settings.json` is the standard VS Code path. Agents_sync must do **key-level** extraction (only `kilo-code.*` keys), not whole-file sync.

### Marketplace Items

The Kilo Marketplace (`Kilo-Org/kilo-marketplace`) ships curated Skills, MCP servers, Modes. Installing them writes into the locations above: `mcp_settings.json`, `custom_modes.yaml`, or `.kilocode/skills/`. Skills follow the emerging `SKILL.md` standard.

### Other User-Authored Artefacts

- `<project>/.kilocodeignore`.
- `~/.kilocode/cli/workspaces/workspace-map.json`, `~/.kilocode/cli/global/tasks/`, `~/.kilocode/cli/logs/` — CLI **state/history**; exclude.
- Profiles directory under globalStorage (`profiles/`) — provider profiles with API keys; exclude or redact.
- `kilo.jsonc` (`<project>/kilo.jsonc`, `<project>/.kilo/kilo.jsonc`, `~/.config/kilo/kilo.jsonc`) — new unified config for the CLI runtime. Not produced by the extension today; worth detecting.

### Summary deltas vs Roo Code

Take the Roo Code adapter, rename `roo` → `kilocode`, `.roo` → `.kilocode`, `.roomodes` → `.kilocodemodes`, `.rooignore` → `.kilocodeignore`, and point globalStorage at `kilocode.kilo-code`. All schemas (custom modes YAML, mcp.json, rules markdown, workflows markdown) are byte-for-byte the same. The one genuinely new surface is `kilo.jsonc` once the CLI runtime stabilises.

### Sources

- [Custom Modes — kilo.ai](https://kilo.ai/docs/agent-behavior/custom-modes)
- [Custom Modes — kilocode.ai](https://kilocode.ai/docs/features/custom-modes)
- [Custom Rules — kilo.ai](https://kilo.ai/docs/agent-behavior/custom-rules)
- [Workflows — kilo.ai](https://kilo.ai/docs/agent-behavior/workflows)
- [Using MCP in Kilo Code — kilocode.ai](https://kilocode.ai/docs/features/mcp/using-mcp-in-kilo-code)
- [Using MCP in Kilo Code — kilo.ai](https://kilo.ai/docs/automate/mcp/using-in-kilo-code)
- [MCP Overview](https://kilo.ai/docs/automate/mcp/overview)
- [Settings](https://kilo.ai/docs/getting-started/settings)
- [.kilocodeignore](https://kilo.ai/docs/customize/context/kilocodeignore)
- [Memory Bank](https://kilo.ai/docs/advanced-usage/memory-bank)
- [file-locations.md — kilocode-legacy](https://github.com/Kilo-Org/kilocode-legacy/blob/main/docs/file-locations.md)
- [Agent Rules and Workflows (DeepWiki)](https://deepwiki.com/Kilo-Org/kilocode/8.3-agent-rules-and-workflows)
- [Migration doc — Kilo-Org/kilo](https://github.com/Kilo-Org/kilo/blob/dev/packages/opencode/src/kilocode/docs/migration.md)
- [Kilo Marketplace](https://github.com/Kilo-Org/kilo-marketplace)
- [Issue #6949 — slash commands](https://github.com/Kilo-Org/kilocode/issues/6949)
- [Issue #6481 — MCP migration v7.0.33](https://github.com/Kilo-Org/kilocode/issues/6481)
- [Issue #1404 — mode-specific rules](https://github.com/Kilo-Org/kilocode/issues/1404)
- [Kilo-Org/kilocode](https://github.com/Kilo-Org/kilocode)

---

## OpenAI Codex CLI

OpenAI Codex CLI is the open-source Rust-based terminal coding agent at `github.com/openai/codex`. It stores all user-authored customization under a single home directory, `CODEX_HOME`, which defaults to `~/.codex` on macOS/Linux and `%USERPROFILE%\.codex` on Windows. There is no XDG-style split — config, agents, skills, prompts, hooks, credentials, history, and session rollouts all live under that one tree. The same files (`AGENTS.md`, `config.toml`, `agents/`, `skills/`, `prompts/`, `hooks.json`) can also appear under a per-repo `.codex/` directory at any ancestor of the working tree; project layers are honored only if the project is "trusted", with the closest layer winning per-key.

### Settings / config — `config.toml`

User-level: `~/.codex/config.toml`. Format TOML. Schema hint: `#:schema https://developers.openai.com/codex/config-schema.json`. Project overrides at `<repo>/.codex/config.toml`; `-c key=value` flags override both.

```toml
# Model + provider
model = "gpt-5-codex"
model_provider = "openai"
model_reasoning_effort = "medium"      # low | medium | high
model_reasoning_summary = "auto"
hide_agent_reasoning = false
disable_response_storage = false

# Safety / execution
approval_policy = "on-request"         # untrusted | on-request | never | granular
sandbox_mode    = "workspace-write"    # read-only | workspace-write | danger-full-access
project_root_markers = [".git", ".hg", ".sl"]

# Project doc (AGENTS.md) discovery
project_doc_max_bytes = 32768
project_doc_fallback_filenames = ["TEAM_GUIDE.md", ".agents.md"]

# History + logs
log_dir = "~/.codex/log"
[history]
persistence = "save-all"               # save-all | none
max_bytes   = 10_000_000

# Misc UX
file_opener = "vscode"
notify = ["/usr/local/bin/codex-notify"]
default_profile = "work"

# Shell env passed to subprocesses
[shell_environment_policy]
inherit  = "core"                      # all | core | none
exclude  = ["AWS_*"]
include_only = []
set      = { CI = "1" }

# Credentials store
cli_auth_credentials_store = "file"

# Custom model providers
[model_providers.azure]
name      = "Azure OpenAI"
base_url  = "https://YOUR.openai.azure.com/openai"
wire_api  = "responses"                # responses | chat
env_key   = "AZURE_OPENAI_API_KEY"
query_params = { api-version = "2025-04-01-preview" }
http_headers = { "X-Org" = "acme" }

# Profiles
[profiles.work]
model            = "gpt-5-codex"
approval_policy  = "on-request"
sandbox_mode     = "workspace-write"
model_reasoning_effort = "high"
```

Reserved built-in provider IDs (cannot be redefined): `openai`, `ollama`, `lmstudio`.

### MCP server configs — inside `config.toml`

```toml
[mcp_servers.github]
enabled = true
required = false
startup_timeout_sec = 10
tool_timeout_sec = 60
transport = { type = "stdio", command = "npx", args = ["-y", "@modelcontextprotocol/server-github"] }
env = { GITHUB_TOKEN = "ghp_xxx" }

[mcp_servers.remote_api]
transport = { type = "streamable_http", url = "https://api.example.com/mcp" }
bearer_token_env_var = "REMOTE_API_TOKEN"
```

Older syntax (still supported) puts `command`, `args`, `env` directly on the table. Transports: `stdio`, `streamable_http`.

### Memory / instructions — `AGENTS.md`

Plain Markdown, no frontmatter. Codex concatenates files in order:

- `~/.codex/AGENTS.md` — user-global.
- `<repo-root>/AGENTS.md` and nested `AGENTS.md` up to CWD — project/team.

Concatenation stops once total bytes exceeds `project_doc_max_bytes` (default 32 KiB). Fallback filenames in `project_doc_fallback_filenames`. Project-level file usually lives in the repo and is version-controlled — only `~/.codex/AGENTS.md` is workstation-scoped.

### Custom agents (subagents) — `~/.codex/agents/*.toml`

One TOML file per agent under `~/.codex/agents/` (user) or `<repo>/.codex/agents/` (project).

```toml
# REQUIRED
name = "pr_explorer"
description = "Read-only codebase explorer for gathering evidence before changes."
developer_instructions = """
Stay in exploration mode. Trace the real execution path, cite files and
symbols, and avoid proposing fixes unless the parent agent asks for them.
"""

# OPTIONAL — inherit from parent session when omitted
nickname_candidates    = ["scout", "ranger"]
model                  = "gpt-5-codex"
model_reasoning_effort = "medium"
sandbox_mode           = "read-only"
[mcp_servers.github]
transport = { type = "stdio", command = "npx", args = ["..."] }
[skills.config]
```

Required: `name`, `description`, `developer_instructions`. Identity: `name`.

### Skills — `~/.codex/skills/<name>/SKILL.md`

Directory-per-skill, mirroring Anthropic's spec.

- User: `~/.codex/skills/<skill-name>/SKILL.md` (plus a `.system/` subtree for OpenAI-shipped skills).
- Project: `<repo>/.codex/skills/<skill-name>/SKILL.md`.

```markdown
---
name: pr-drafter
description: Use when the user asks to draft a pull request body from staged diff.
---

# When to use
…body of natural-language instructions…
```

YAML frontmatter requires `name` and `description`. `name` must match folder name. The `.system/` subtree under `~/.codex/skills/` ships with the CLI and should be excluded from sync.

### Slash commands / custom prompts — `~/.codex/prompts/*.md`

Markdown files become slash commands (`/<basename>` or `/prompts:<basename>`). Project-scope NOT supported. Non-Markdown files ignored.

```markdown
---
description: Prep a branch, commit, and open a draft PR
argument-hint: [FILES=<paths>] [PR_TITLE="<title>"]
---
Stage the files in $FILES, commit with message inferred from the diff,
push the branch, and open a draft PR titled $PR_TITLE.
```

Placeholders: positional `$1..$9` (space-split args), named `$FOO` (passed as `KEY=value`). User-only. Marked **deprecated** in favor of skills.

### Hooks — `~/.codex/hooks.json` or `[hooks]` in `config.toml`

Loads from either a sibling `hooks.json` or inline `[hooks]` in `config.toml`. Same schema. Locations: `~/.codex/hooks.json`, `<repo>/.codex/hooks.json`, plugin-bundled.

Events: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `Stop` (all turn-scoped).

```toml
[[hooks.PreToolUse]]
matcher = "^Bash$"
[[hooks.PreToolUse.hooks]]
type = "command"
command = '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/pre_tool_use.py"'
timeout = 30
statusMessage = "Checking Bash command"
```

JSON form:

```json
{
  "PreToolUse": [
    {
      "matcher": "^Bash$",
      "hooks": [
        { "type": "command",
          "command": "/usr/bin/python3 .codex/hooks/pre_tool_use.py",
          "timeout": 30,
          "statusMessage": "Checking Bash command" }
      ]
    }
  ]
}
```

Hook scripts speak JSON over stdin/stdout. Deny via `permissionDecision: "deny"` or exit-code 2 with reason on stderr.

### Authentication — `~/.codex/auth.json`

Plaintext JSON cache. `cli_auth_credentials_store` config key currently only accepts `file`. **Out of sync scope** — credential, never replicate.

### History / sessions / logs (out of scope)

- `~/.codex/history.jsonl` — input-line history.
- `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` — session transcripts used for `codex resume`.
- `~/.codex/log/codex-tui.log` — runtime logs.

### Other items under `~/.codex/`

- `~/.codex/skills/.system/` — OpenAI-shipped built-in skills; exclude.
- Plugin-managed directories — leave to plugin tool.
- `requirements.toml` (enterprise-managed) — read-only policy; exclude.

### Sources

- [openai/codex (repo)](https://github.com/openai/codex)
- [Configuration Reference](https://developers.openai.com/codex/config-reference)
- [Config basics](https://developers.openai.com/codex/config-basic)
- [Advanced Configuration](https://developers.openai.com/codex/config-advanced)
- [Sample Configuration](https://developers.openai.com/codex/config-sample)
- [AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md)
- [Subagents](https://developers.openai.com/codex/subagents)
- [Agent Skills](https://developers.openai.com/codex/skills)
- [Custom Prompts](https://developers.openai.com/codex/custom-prompts)
- [Slash commands (CLI)](https://developers.openai.com/codex/cli/slash-commands)
- [MCP](https://developers.openai.com/codex/mcp)
- [Hooks](https://developers.openai.com/codex/hooks)
- [Authentication](https://developers.openai.com/codex/auth)
- [Windows app/CLI notes](https://developers.openai.com/codex/app/windows)
- [Managed configuration (enterprise)](https://developers.openai.com/codex/enterprise/managed-configuration)
- [Config schema JSON](https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json)

---

## opencode (SST)

[opencode](https://opencode.ai) is the open-source terminal AI coding agent from SST (github.com/sst/opencode). It follows the XDG Base Directory spec on Linux/macOS and uses `%APPDATA%` on Windows. Most user-authored data lives under a single root directory, with parallel project-level overrides under `.opencode/` at the repo root. Config files merge with precedence (lowest → highest): remote (`.well-known/opencode`) → global (`~/.config/opencode/opencode.json`) → custom (`OPENCODE_CONFIG` env) → project (`./opencode.json`) → `.opencode` dirs → inline (`OPENCODE_CONFIG_CONTENT`) → managed settings → macOS managed preferences.

**Global root per OS:**
- Linux: `~/.config/opencode/`
- macOS: `~/.config/opencode/` (XDG, not `~/Library/Application Support`)
- Windows: `%APPDATA%\opencode\`

Managed-policy roots (admin): `/etc/opencode/` (Linux), `/Library/Application Support/opencode/` (macOS), `%ProgramData%\opencode\` (Windows).

Throughout, opencode's docs use **plural** subdirectory names (`agents/`, `commands/`, `skills/`, `themes/`, `plugins/`). The singular form is reportedly accepted for backward compat; treat plural as on-disk truth.

### Settings — `opencode.json` / `opencode.jsonc`

Path: `~/.config/opencode/opencode.json` (global) and `./opencode.json` or `./.opencode/opencode.json` (project). JSONC accepted.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "theme": "tokyonight",
  "model": "anthropic/claude-sonnet-4-5",
  "small_model": "anthropic/claude-haiku-4-5",
  "username": "alice",
  "share": "manual",
  "autoupdate": true,
  "autoshare": false,
  "provider": {},
  "agent": {},
  "default_agent": "build",
  "command": {},
  "mcp": {},
  "permission": {},
  "instructions": ["CONTRIBUTING.md", "docs/guidelines.md"],
  "plugin": ["opencode-helicone-session", "@my-org/custom-plugin"],
  "keybinds": {},
  "formatter": true,
  "lsp": true,
  "tools": { "write": false, "bash": false },
  "server": { "port": 4096, "hostname": "0.0.0.0", "mdns": true },
  "shell": "pwsh",
  "attachment": { "image": { "auto_resize": true, "max_width": 2000 } },
  "compaction": { "auto": true },
  "watcher": { "ignore": [] },
  "snapshot": true,
  "disabled_providers": [],
  "enabled_providers": [],
  "experimental": {}
}
```

Variable substitution: `{env:VAR_NAME}` and `{file:path/to/file}` expanded throughout. Sync risk: API keys/tokens via `{env:...}` safe; literal secrets in `provider` or `mcp.*.headers` must be filtered. `username`, `share`, `autoupdate`, `server` are workstation-local.

### Custom Agents

- Global: `~/.config/opencode/agents/<name>.md`
- Project: `.opencode/agents/<name>.md`
- Windows: `%APPDATA%\opencode\agents\<name>.md`

Filename stem is the agent identity — `review.md` → `@review`. Frontmatter:

| Field | Type | Notes |
|---|---|---|
| `description` | string | Required. Used by primary agents to route to subagents. |
| `mode` | `"primary"` \| `"subagent"` \| `"all"` | |
| `model` | string | e.g. `anthropic/claude-sonnet-4-5`. |
| `temperature` | number | 0.0–1.0 |
| `top_p` | number | Alternative to temperature |
| `permission` | object | `{ edit, bash, webfetch, ... }` with `allow`/`ask`/`deny` |
| `tools` | object | Glob keys → boolean; `"skill": false`, `"my-mcp*": false` |
| `color` | string | Hex or theme color name |

Built-in primaries: **Build**, **Plan**. Built-in subagents: **General**, **Explore**, **Scout**. Reserved names — user files named `build.md`/`plan.md`/`general.md`/`explore.md`/`scout.md` are overrides.

```markdown
---
description: Reviews code for quality and best practices
mode: subagent
model: anthropic/claude-sonnet-4-20250514
temperature: 0.1
permission:
  edit: deny
  bash: deny
---
You are in code review mode. Focus on:
- Code quality and best practices
- Potential bugs and edge cases
- Performance implications
- Security considerations
```

### Skills

First-party [Agent Skills](https://opencode.ai/docs/skills/) support, conforming to Anthropic's standard.

Search order:
- Project: `.opencode/skills/<name>/SKILL.md`
- Global: `~/.config/opencode/skills/<name>/SKILL.md`
- Claude-compatible: `.claude/skills/<name>/SKILL.md` and `~/.claude/skills/<name>/SKILL.md`
- Generic agent paths

Required frontmatter:

```yaml
---
name: pdf-extractor          # required, ^[a-z0-9]+(-[a-z0-9]+)*$, MUST match directory
description: Extract structured data from PDFs.
license: MIT                 # optional
compatibility: {}            # optional
metadata: {}                 # optional
---
```

Permissions controlled via `permission.skill` in `opencode.json`. Skill directory may include supporting files. opencode reads `~/.claude/skills/` — syncing a skill there makes it visible to both; treat as shared canonical surface.

### Custom Commands / Slash Prompts

- Global: `~/.config/opencode/commands/<name>.md`
- Project: `.opencode/commands/<name>.md`

Filename stem — `test.md` → `/test`. Frontmatter:

```markdown
---
description: Run tests with coverage
agent: build
model: anthropic/claude-3-5-sonnet-20241022
subtask: false
---
Run the full test suite for $ARGUMENTS and report failures.
Recent git log: !`git log --oneline -5`
Relevant file: @src/test_runner.py
```

Body supports:
- `$ARGUMENTS`, `$1`, `$2`, … — positional args.
- `` !`cmd` `` — inject shell stdout.
- `@path/to/file` — inline file contents.

`subtask: true` forces a fresh subagent. Sync risk: the `!`...`` directive executes arbitrary shell — review on import.

### MCP Server Configs

Inside `opencode.json` under `mcp` — not separate files. Two transports:

```json
{
  "mcp": {
    "my-local": {
      "type": "local",
      "command": ["npx", "-y", "my-mcp-command"],
      "environment": { "API_KEY": "{env:MY_KEY}" },
      "enabled": true
    },
    "my-remote": {
      "type": "remote",
      "url": "https://my-mcp-server.com",
      "headers": { "Authorization": "Bearer {env:TOKEN}" },
      "enabled": true,
      "oauth": false,
      "clientId": "...",
      "clientSecret": "...",
      "scope": "read write"
    }
  }
}
```

Identity: object key. OAuth automatic via RFC 7591 DCR unless `oauth: false`. Tokens land in opencode's auth store. Sync risk: `headers` and `environment` commonly contain literal secrets; sanitize via `{env:...}`.

### Memory / Instructions — `AGENTS.md`

Per [Rules](https://opencode.ai/docs/rules/), opencode loads `AGENTS.md` in order:

1. Local `AGENTS.md` files (walk up from CWD).
2. Global: `~/.config/opencode/AGENTS.md`.
3. Fallback: `~/.claude/CLAUDE.md` (unless disabled).

Additional instruction files in `opencode.json`:

```json
{ "instructions": ["CONTRIBUTING.md", "docs/guidelines.md", "https://example.com/rules.md"] }
```

Remote URLs allowed (5-second timeout). `/init` generates `AGENTS.md` for a repo. Sync risk: treat `~/.config/opencode/AGENTS.md` and `~/.claude/CLAUDE.md` as a shared logical surface.

### Themes

- Global: `~/.config/opencode/themes/<name>.json`
- Project: `.opencode/themes/<name>.json`

JSON only. Supports `defs` block, hex (`"#abcdef"`), ANSI ints (0–255), references to `defs`, `"none"`, `{ dark, light }` variants. Requires truecolor terminal.

### Plugins

- Global: `~/.config/opencode/plugins/*.{js,ts}`
- Project: `.opencode/plugins/*.{js,ts}`

Local plugins auto-load. npm-distributed plugins listed in `opencode.json` `plugin` array. TS plugins import from `@opencode-ai/plugin`. Sync risk: arbitrary executable code — flag for explicit user review on import, never auto-trust.

### Modes

Not a current opencode concept — `/docs/modes/` 404s. Mode is an agent attribute (`mode: primary|subagent|all`) plus `default_agent` and `agent` keys in `opencode.json`.

### Keybinds

In `opencode.json` under `keybinds` (and `tui.json` for the desktop app). Default leader `ctrl+x`, `leader_timeout: 2000`. Disabled via `"none"` or `false`. Platform-specific defaults differ for Windows.

### Permissions

`permission` block in `opencode.json`. Keys: `read`, `edit`, `bash`, `webfetch`, `external_directory`, `task`, `skill`, `lsp`, `question`, `websearch`, `doom_loop`. Values: `"allow"`, `"ask"`, `"deny"`, or pattern objects. Last matching rule wins; supports `*`, `?`, `~`/`$HOME` expansion. Agent frontmatter `permission:` overrides global.

### Other user-authored surfaces

- **Auth store** — OAuth tokens (typically `~/.local/share/opencode/auth.json`). **Do not sync**.
- **Session state / share data** — workstation-local; exclude.
- **`opencode.jsonc`** — alternate filename for the main config (with comments).
- **Project-level mirror** — every directory has a `.opencode/<subdir>/` analogue at the repo root.

### Sync-risk summary

- `opencode.json` keys `server`, `username`, `autoupdate`, `share`, `theme` are workstation-local — filterable.
- `provider`, `mcp.*.headers`, `mcp.*.environment` may carry secrets; rewrite to `{env:...}` or skip.
- Plugins are executable; treat as elevated-trust artifacts.
- Skills overlap with `~/.claude/skills/` — dedupe across tools.
- `AGENTS.md` overlaps with `~/.claude/CLAUDE.md` via fallback — dedupe.
- Built-in agent names (`build`, `plan`, `general`, `explore`, `scout`) are reserved overrides.

### Sources

- [opencode docs](https://opencode.ai/docs/)
- [Config](https://opencode.ai/docs/config/)
- [Agents](https://opencode.ai/docs/agents/)
- [Commands](https://opencode.ai/docs/commands/)
- [MCP Servers](https://opencode.ai/docs/mcp-servers/)
- [Rules / AGENTS.md](https://opencode.ai/docs/rules/)
- [Skills](https://opencode.ai/docs/skills/)
- [Permissions](https://opencode.ai/docs/permissions/)
- [Themes](https://opencode.ai/docs/themes/)
- [Plugins](https://opencode.ai/docs/plugins/)
- [Keybinds](https://opencode.ai/docs/keybinds/)
- [sst/opencode on GitHub](https://github.com/sst/opencode)
- [Agent System (DeepWiki)](https://deepwiki.com/sst/opencode/3.2-agent-system)
- [Configuration System (DeepWiki)](https://deepwiki.com/sst/opencode/3-configuration-system)
- [Anthropic Agent Skills spec](https://github.com/anthropics/skills)

---

## OpenHands (All Hands AI)

OpenHands (github.com/All-Hands-AI/OpenHands, formerly OpenDevin) is an open-source software-development agent shipped as a Docker server, a desktop app, and a CLI (`openhands` / `python -m openhands.cli.main`). User-authored disk surface is split between a **project layer** (`.openhands/` inside each repo + a root-level `AGENTS.md`) and a **host-user layer** (`~/.openhands/`, formerly `~/.openhands-state/`). The agent normally executes inside a sandbox container; every user-authored file the agent reads is bind-mounted from the host. Sync only host paths.

OpenHands is mid-V0→V1 rename: V0 uses **microagents** under `.openhands/microagents/`; V1 uses **skills** under `.openhands/skills/` (or repo root `.agents/skills/`). V1 still loads V0 microagents for backward compatibility.

### Microagents / Skills (repository-scoped)

Path: `<repo_root>/.openhands/microagents/*.md` (V0) and `<repo_root>/.openhands/skills/*.md` or `<repo_root>/.agents/skills/*.md` (V1). Plain Markdown; subdirectories allowed (V1 SKILL.md form: one folder per skill).

Three kinds:
1. **Repository microagent** — named `repo.md` or `type: repo`. Loaded every interaction in this repo.
2. **Knowledge microagent** — `type: knowledge` / `trigger_type: keyword`. Injected when `triggers` keywords appear.
3. **Always-on microagent** — `trigger_type: always`.

Frontmatter (V0 and V1 keys both accepted):

```yaml
---
name: kubernetes_helper
type: knowledge                    # repo | knowledge | always (V0)
trigger_type: keyword              # always | keyword | manual (V1)
triggers:
  - kubernetes
  - k8s
  - kubectl
agent: CodeActAgent                # optional
mcp_location: ./mcp-server.json    # optional, attaches MCP server
inputs:                            # optional (V1)
  - name: namespace
    default: default
---
# Body becomes system-prompt extension
Use `kubectl --context=$KUBE_CONTEXT` and prefer namespaced operations.
```

Identity: `name`; falls back to filename stem. Precedence: `.agents/skills/` > `.openhands/skills/` > `.openhands/microagents/`; project skills override user skills. Sync risks: filename collisions; V0/V1 frontmatter dialect drift; `mcp_location` host-relative paths the sandbox cannot resolve.

### Personal / global microagents (host-scoped)

No first-class personal-microagents directory yet. Issue #6404 proposes `~/.openhands-state/global-microagents/`. Today's workaround: keep a personal skills repo and symlink into each project — treat as repo-scoped until the feature lands.

### AGENTS.md (repo root)

OpenHands honours the cross-tool **AGENTS.md** convention. Loaded every session in addition to any `.openhands/microagents/repo.md`. No frontmatter. Sync risk: shared with Codex, Claude, Aider; downstream agents may interpret directives differently.

### MCP servers

Two surfaces:

- **CLI / headless**: `[mcp]` section of `~/.openhands/config.toml` (legacy `~/.openhands-state/config.toml`) or repo-local `./config.toml`. Repo-local overrides user-level.
- **Web/Docker server**: `~/.openhands/settings.json` under `mcp` object, written by Settings → MCP UI.

Unification in progress (Issue #9531); both paths read the same schema.

```toml
[mcp]
shttp_servers = [
    "https://api.example.com/mcp/shttp",
    { url = "https://files.example.com/mcp/shttp",
      api_key = "your-api-key",
      timeout = 180 }
]
sse_servers = [
    "http://localhost:8080/mcp/sse",
    { url = "https://api.example.com/mcp/sse", api_key = "your-api-key" }
]
stdio_servers = [
    { name = "filesystem",
      command = "npx",
      args = ["@modelcontextprotocol/server-filesystem", "/"] },
    { name = "fetch",
      command = "uvx",
      args = ["mcp-server-fetch"],
      env = { DEBUG = "true" } }
]
```

Identity: `name` for stdio; `url` for SSE/SHTTP. Sync risks: (a) stdio `command`/`args` reference host binaries; (b) in Docker-server mode stdio runs *inside* the sandbox image — host-absolute paths fail; (c) `api_key` values are secrets.

### Settings / config

Two files, host-side:

```
~/.openhands/settings.json        # Web/Docker, user-level prefs
~/.openhands/config.toml          # CLI / headless, system-level
```

Plus legacy `~/.openhands-state/...` (auto-migrated). A `./config.toml` in repo root is also loaded.

TOML sections (from `config.template.toml`):

- `[core]` — `workspace_base`, `cache_dir`, `debug`, `file_store`, `file_store_path`, `save_trajectory_path`, `runtime`, `default_agent` (default `CodeActAgent`), `max_iterations`, `max_budget_per_task`, `enable_browser`, `jwt_secret`, `max_concurrent_conversations`, `conversation_max_age_seconds`.
- `[llm]` / `[llm.<name>]` — `model`, `api_key`, `base_url`, `temperature`, `top_p`, `max_input_tokens`, `max_output_tokens`, `presence_penalty`, `frequency_penalty`. Named subsections for multiple profiles.
- `[agent]` / `[agent.<AgentName>]` — `enable_browsing`, `enable_llm_editor`, `enable_editor`, `enable_jupyter`, `enable_cmd`, `enable_think`, `enable_finish`, `enable_prompt_extensions`, `enable_history_truncation`, `enable_condensation_request`, `disabled_microagents = []`, `classpath`.
- `[sandbox]` — `timeout`, `user_id`, `base_container_image`, `runtime_container_image`, `use_host_network`, `runtime_extra_build_args`, `runtime_extra_deps`, `runtime_startup_env_vars`, `enable_auto_lint`, `initialize_plugins`, `platform`, `force_rebuild_runtime`, `keep_runtime_alive`, `pause_closed_runtimes`, `close_delay`, `enable_gpu`, `cuda_visible_devices`, `docker_runtime_kwargs`, `vscode_port`, `volumes`.
- `[security]` — `confirmation_mode`, `security_analyzer` (`llm` | `invariant`), `enable_security_analyzer`.
- `[condenser]` — `type` (`noop`|`observation_masking`|`recent`|`llm`|`amortized`|`llm_attention`), `keep_first`, `max_size`, `attention_window`, `llm_config`.
- `[kubernetes]` — `namespace`, `ingress_domain`, `pvc_storage_size`, `pvc_storage_class`, `resource_cpu_request`, `resource_memory_request`, `resource_memory_limit`, `image_pull_secret`, `ingress_tls_secret`, `node_selector_key`, `node_selector_val`, `tolerations_yaml`, `privileged`.
- `[mcp]` — see above.
- `[model_routing]` — `router_name` (`noop_router` | `multimodal_router`).

`settings.json` keys: `llm_model`, `llm_api_key`, `llm_base_url`, `agent`, `language`, `confirmation_mode`, `security_analyzer`, `remote_runtime_resource_factor`, `enable_default_condenser`, `github_token` / `provider_tokens`, `user_consents_to_analytics`, `mcp_config`, `llm_profiles`.

Sync risks: `llm_api_key`, `github_token`, `provider_tokens`, `jwt_secret`, MCP `api_key` are secrets; sandbox `volumes`, `workspace_base`, `workspace_mount_path` are host-path-shaped; container image pins may reference private registries.

### Slash commands / custom prompts / hooks

**No documented custom-slash-command file format** and **no hook system**. The CLI exposes a built-in slash menu (`/help`, `/exit`, `/init`) but these are hard-coded. Issue #343 in `OpenHands-CLI` proposes a `/`-launched Agent Skill menu. Treat any future hook/command directory as TBD.

### Memory / persistence

`~/.openhands/` is the FileStore:

```
~/.openhands/
  settings.json
  config.toml
  secrets.json                                 # encrypted SecretsStore
  sessions/
  conversations/<conversation_id>/
      base_state.json
      metadata.json
      events/event-00000-<eventid>.json
```

Location overridable via `OH_PERSISTENCE_DIR` (default `~/.openhands`) and `[core] file_store_path`. These are **session state, not user customisation** — explicitly exclude `conversations/`, `sessions/`, `events/`, `secrets.json` from sync.

### OS-specific paths

| OS | User root | Repo-level |
|---|---|---|
| Linux | `~/.openhands/` (legacy `~/.openhands-state/`) | `<repo>/.openhands/`, `<repo>/.agents/skills/`, `<repo>/AGENTS.md` |
| macOS | same | same |
| Windows | `%USERPROFILE%\.openhands\` — OpenHands runs inside a Linux container; on-host files live wherever the user bind-mounted into `/root/.openhands`. Issue #11247 documents Windows-native breakage; treat Windows as Docker-only. | `<repo>\.openhands\…` |

### In-container vs host nuances

`docker run ghcr.io/all-hands-ai/openhands` bind-mounts `~/.openhands` (host) → `/.openhands` (container) and the project repo → `/workspace`. Stdio MCP servers and sandbox `volumes` resolve **inside the container's filesystem**; absolute host paths in those keys will be broken on the agent side.

### Sources

- [Microagents Overview](https://docs.openhands.dev/openhands/usage/microagents/microagents-overview)
- [General Microagents](https://docs.all-hands.dev/modules/usage/prompting/microagents-repo)
- [Skills (V1)](https://docs.openhands.dev/overview/skills)
- [General Skills (repo)](https://docs.openhands.dev/overview/skills/repo)
- [OpenHands/skills/README.md](https://github.com/OpenHands/OpenHands/blob/main/skills/README.md)
- [OpenHands/AGENTS.md](https://github.com/OpenHands/OpenHands/blob/main/AGENTS.md)
- [MCP Settings](https://docs.all-hands.dev/openhands/usage/settings/mcp-settings)
- [MCP Servers — CLI](https://docs.openhands.dev/openhands/usage/cli/mcp-servers)
- [Custom LLM Configurations](https://docs.openhands.dev/openhands/usage/llms/custom-llm-configs)
- [Configuration Options](https://docs.openhands.dev/openhands/usage/advanced/configuration-options)
- [config.template.toml](https://github.com/All-Hands-AI/OpenHands/blob/main/config.template.toml)
- [Issue #9531 — Unify dual configuration](https://github.com/All-Hands-AI/OpenHands/issues/9531)
- [Issue #6404 — User-level microagents](https://github.com/All-Hands-AI/OpenHands/issues/6404)
- [Issue #7547 — Simplify microagents + native MCP](https://github.com/All-Hands-AI/OpenHands/issues/7547)
- [Issue #9520 — MCP support in CLI](https://github.com/All-Hands-AI/OpenHands/issues/9520)
- [Issue #12377 — Re-thinking Skills Management](https://github.com/All-Hands-AI/OpenHands/issues/12377)
- [Issue #11247 — Windows initialization failures](https://github.com/All-Hands-AI/OpenHands/issues/11247)
- [Persistence — SDK Docs](https://docs.openhands.dev/sdk/guides/convo-persistence)
- [Secrets Management (DeepWiki)](https://deepwiki.com/OpenHands/OpenHands/6.3-agent-configuration)

---

## Plandex

Plandex is a terminal AI coding agent with a strong client/server split: the CLI is a Go binary, and most plan/context/conversation state lives in a PostgreSQL-backed server (Plandex Cloud or self-hosted). Only a thin slice of user-authored data sits on the workstation filesystem — but that slice contains the **custom models / providers / model packs JSON**, the per-project link to the server-side project, and the CLI auth/host config.

### Top-level user-data directory (`~/.plandex-home-v2`)

Plandex v2 stores client-side state under `~/.plandex-home-v2/`, suffixed `-v2` since v2 redesign. Earlier docs refer to `.plandex-home`. A `-dev` variant is used when `PLANDEX_ENV=development`.

| OS | Default path |
|----|--------------|
| Linux | `$HOME/.plandex-home-v2/` |
| macOS | `$HOME/.plandex-home-v2/` |
| Windows | `%USERPROFILE%\.plandex-home-v2\` |

No documented `PLANDEX_HOME` override; `PLANDEX_BASE_DIR` is server-side. Inside:

```
~/.plandex-home-v2/
├── auth.json                              # active account, host, token
└── accounts/
    └── <account-id>/
        └── custom-models.json             # user-authored
```

### Custom models, providers, and model packs

**The** user-authored artifact. Edited via `plandex models custom` (or `\models custom` in REPL):

```
~/.plandex-home-v2/accounts/<account-id>/custom-models.json
```

Schema: `https://plandex.ai/schemas/models-input.schema.json`. Three top-level arrays — `providers`, `models`, `modelPacks`.

```json
{
  "$schema": "https://plandex.ai/schemas/models-input.schema.json",
  "providers": [
    { "name": "together",     "baseUrl": "https://api.together.xyz/v1", "apiKeyEnvVar": "TOGETHER_API_KEY" },
    { "name": "local-llm",    "baseUrl": "http://localhost:8080/v1",   "skipAuth": true }
  ],
  "models": [
    {
      "modelId": "qwen/qwen3-coder",
      "publisher": "qwen",
      "description": "Qwen3 Coder via Together",
      "defaultMaxConvoTokens": 75000,
      "maxTokens": 256000,
      "maxOutputTokens": 32000,
      "reservedOutputTokens": 8000,
      "preferredOutputFormat": "xml",
      "providers": [ { "provider": "together", "modelName": "Qwen/Qwen3-Coder" } ]
    }
  ],
  "modelPacks": [
    {
      "name": "qwen-coder-pack",
      "description": "Qwen3 Coder for everything",
      "planner":        { "modelId": "qwen/qwen3-coder", "temperature": 0.7, "topP": 0.9,
                          "largeContextFallback": "google/gemini-2.5-pro" },
      "architect":      "qwen/qwen3-coder",
      "coder":          "qwen/qwen3-coder",
      "summarizer":     "anthropic/claude-3.5-haiku",
      "builder":        "qwen/qwen3-coder",
      "wholeFileBuilder": "qwen/qwen3-coder",
      "names":          "anthropic/claude-3.5-haiku",
      "commitMessages": "anthropic/claude-3.5-haiku",
      "autoContinue":   "anthropic/claude-3.5-haiku"
    }
  ]
}
```

Identity fields: `providers[].name`, `models[].modelId`, `modelPacks[].name`. A `--file /path/to/models.json` flag lets the user point elsewhere, but the canonical store is the path above. Sync risk: `<account-id>` differs across machines — rewrite the parent path on import.

### Roles

No separate "roles" config. **Roles are baked into model packs** (`planner`, `architect`, `coder`, `summarizer`, `builder`, `wholeFileBuilder`, `names`, `commitMessages`, `autoContinue`). Each role is a string `modelId` or `{ modelId, temperature, topP, largeContextFallback, … }`.

### Auth / host configuration (`auth.json`)

```
~/.plandex-home-v2/auth.json
```

Active account, host, auth token. **Not safe to sync** — tokens are machine-scoped, host may differ per workstation. Exclude from snapshots by default.

### Project-level directory (`<project>/.plandex-v2/`)

Created on `plandex` or `plandex new`:

```
<project>/.plandex-v2/            # v2 builds (older docs: ".plandex/")
```

Light — pointer linking working tree to server-side project (project ID, org ID, current plan ID, branch). Plans, conversation history, context: **server-side DB**, not here. Docs recommend either committing or gitignoring `.plandex-v2/`.

Also project-level, user-authored:

```
<project>/.plandexignore          # .gitignore syntax
```

Plain-text. Lives next to source tree, not under agent home — usually committed to project repo.

### Plan-level configuration

Plan settings — `auto-mode` (`none|basic|plus|semi|full`), `auto-apply`, `auto-commit`, `auto-context`, `auto-debug`, `auto-exec`, `auto-continue` — are set via `plandex set-config` and stored **server-side**, attached to the plan or account defaults. No client-side JSON.

### MCP support

As of CLI v2.2.x, Plandex has **no MCP client or server integration**. No `mcp.json`, no `mcpServers` block, no `plandex mcp` subcommand. Treat as **not supported**.

### Memory / context / notes

Plandex's "context" (loaded files, URLs, images, notes, piped input) is per-plan, version-controlled, server-side. No local user-scope memory file. Notes via `--note/-n` become server-side context items.

### Summary

| Artifact | Path | Sync? | Identity |
|---|---|---|---|
| Custom models / providers / model packs | `~/.plandex-home-v2/accounts/<account-id>/custom-models.json` | Yes (rewrite account-id) | `providers[].name`, `models[].modelId`, `modelPacks[].name` |
| Auth / host | `~/.plandex-home-v2/auth.json` | **No** (token + per-machine host) | — |
| Project link | `<project>/.plandex-v2/` | No (per-clone server pointer) | — |
| `.plandexignore` | `<project>/.plandexignore` | No (lives with project repo) | path |
| Roles | inside `custom-models.json` modelPacks | covered | — |
| MCP | not supported | — | — |
| Plan/autonomy config | server-side only | — | — |

### Sources

- [Custom Models, Providers, and Model Packs](https://docs.plandex.ai/models/custom-models/)
- [Model Settings](https://docs.plandex.ai/models/model-settings/)
- [Model Roles](https://docs.plandex.ai/models/roles/)
- [Model Providers](https://docs.plandex.ai/models/model-providers/)
- [Configuration](https://docs.plandex.ai/core-concepts/configuration/)
- [Autonomy](https://docs.plandex.ai/core-concepts/autonomy/)
- [Context Management](https://docs.plandex.ai/core-concepts/context-management/)
- [CLI Reference](https://docs.plandex.ai/cli-reference/)
- [Environment Variables](https://docs.plandex.ai/environment-variables/)
- [Advanced Self-Hosting](https://docs.plandex.ai/hosting/self-hosting/advanced-self-hosting/)
- [plandex-ai/plandex](https://github.com/plandex-ai/plandex)
- [Issue #291 — custom models path](https://github.com/plandex-ai/plandex/issues/291)
- [Issue #297 — CLI flags `--local` and `--host`](https://github.com/plandex-ai/plandex/issues/297)
- [Issue #299 — .gitignore/.plandexignore](https://github.com/plandex-ai/plandex/issues/299)

---

## Roo Code

Roo Code (publisher id `RooVeterinaryInc.roo-cline`, formerly Roo Cline; forked from Cline) is an open-source VS Code coding-agent extension. User-authored data lives in two zones: (1) a VS Code per-extension `globalStorage` folder (user-scope), and (2) a `.roo/` tree in each project workspace (project-scope). A few items also use VS Code `settings.json` keys under `roo-cline.*`.

The "extension settings directory" resolves to:

| OS | Path |
|---|---|
| Linux | `~/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/` |
| macOS | `~/Library/Application Support/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/` |
| Windows | `%APPDATA%\Code\User\globalStorage\rooveterinaryinc.roo-cline\settings\` |

For VS Code Insiders, replace `Code` with `Code - Insiders`; VS Codium uses `VSCodium`; Cursor / Windsurf use their own `globalStorage` roots.

### Custom Modes

A named agent persona with role definition, tool-group whitelist, optional custom instructions.

**Project**: `<project>/.roomodes` (YAML preferred; JSON also accepted). Single file at project root.

**Global**: `<settings-dir>/custom_modes.yaml` (older installs may have `custom_modes.json`).

Schema (`customModes` list):

| Field | Type | Required | Notes |
|---|---|---|---|
| `slug` | string | yes | Identity field. `/^[a-zA-Z0-9-]+$/`. |
| `name` | string | yes | Display name. |
| `description` | string | no | |
| `roleDefinition` | string | yes | Multi-line persona prompt. |
| `whenToUse` | string | no | Orchestrator hint. |
| `customInstructions` | string | no | Appended guidance. |
| `groups` | array | yes | Tool groups: `read`, `edit` (optionally `["edit", { fileRegex, description }]`), `browser`, `command`, `mcp`. |
| `source` | string | no | `"global"` / `"project"` (Roo sets on merge). |
| `iconName` | string | no | Codicon. |

```yaml
customModes:
  - slug: docs-writer
    name: 📝 Documentation Writer
    description: Writes and edits Markdown docs only.
    roleDefinition: You are a technical writer specializing in clear documentation.
    whenToUse: Use for writing or editing .md/.mdx files.
    groups:
      - read
      - - edit
        - fileRegex: \.(md|mdx)$
          description: Markdown files only
```

Project entries override global by `slug`. Sync risk: global file lives under a VS Code-fork-specific `globalStorage` — same file is not seen by Cursor/Windsurf/Insiders unless replicated (issue #10750 proposes `~/.roo/modes/`).

### Rules (Custom Instructions)

Markdown/text concatenated alphabetically into the system prompt.

| Form | Path | Scope |
|---|---|---|
| Generic project rules | `<project>/.roo/rules/*.md` (recursive) | project, all modes |
| Mode-specific project rules | `<project>/.roo/rules-<modeSlug>/*.md` | project, one mode |
| Generic global rules | `~/.roo/rules/*.md` | user |
| Mode-specific global rules | `~/.roo/rules-<modeSlug>/*.md` | user, one mode |
| Legacy generic project | `<project>/.roorules` | project |
| Legacy mode-specific project | `<project>/.roorules-<modeSlug>` | project, one mode |
| Legacy global | `~/.roorules`, `~/.roorules-<modeSlug>` | user |
| Cross-agent standard | `<project>/AGENTS.md` | project |

Load order (`addCustomInstructions`): language preference → global custom instructions → mode-specific → mode-specific rules dir/file → `.rooignore` notice → `AGENTS.md` → generic rules dir/file. Directory form takes precedence over legacy single-file; project layers over global.

No frontmatter required. Identity = filesystem path. Sync risk: ordering depends on filename collation.

### Workflows

Roo Code does **not** expose `.roo/workflows/`. "Workflow" refers to Boomerang Tasks/Orchestrator (runtime) or reusable prompts (slash commands / Skills). No persistent on-disk schema named "workflow" — agents_sync should not look for `.roo/workflows/`.

### MCP Servers

Two scopes; identical `mcpServers` schema.

**Global**: `<settings-dir>/mcp_settings.json` (historic `cline_mcp_settings.json` also read in older installs).
**Project**: `<project>/.roo/mcp.json`.

Project wins on name collision.

Per-server fields:

| Field | Type | Notes |
|---|---|---|
| `type` | `"stdio"`\|`"sse"`\|`"streamable-http"` | Optional for `command` (default stdio); required for URL. |
| `command` | string | stdio. |
| `args` | string[] | stdio. |
| `env` | object<string,string> | stdio. `${env:VAR}` supported. |
| `cwd` | string | stdio. Defaults to first workspace folder. |
| `url` | string | sse / streamable-http. |
| `headers` | object | sse / streamable-http. |
| `disabled` | boolean | |
| `alwaysAllow` | string[] | Auto-approved tool names. |
| `timeout` | number | Seconds. |

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "${workspaceFolder}"],
      "alwaysAllow": ["read_file", "list_directory"],
      "disabled": false
    },
    "github-remote": {
      "type": "streamable-http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": { "Authorization": "Bearer ${env:GITHUB_TOKEN}" }
    }
  }
}
```

Identity: `mcpServers` key. Sync risk: `env` may carry secrets; UI rewrites JSON formatting on save (issue #9862).

### Slash Commands

User-authored prompts triggered by `/<name>` in chat. Three-tier precedence: project > global > built-in.

| Scope | Path |
|---|---|
| Project | `<project>/.roo/commands/*.md` |
| Global | `~/.roo/commands/*.md` |

```markdown
---
description: Generate a new REST API endpoint with best practices
argument-hint: <endpoint-name> <http-method>
---
Create a new REST API endpoint with the following specifications:
- Proper error handling
- Input validation
- Authentication middleware
- OpenAPI documentation
- Unit and integration tests
```

Frontmatter: `description`, `argument-hint`. Identity = filename stem. Global tree at `~/.roo/commands/` is outside `globalStorage` — straightforward cross-machine sync but not cross-editor.

### Skills

Added in Roo Code 3.38 (Dec 2025). Two scopes:

- Project: `<project>/.roo/skills/<skill-name>/` or `<project>/.roo/skills-<modeSlug>/<skill-name>/`.
- Global: `~/.roo/skills/<skill-name>/` (and `~/.roo/skills-<modeSlug>/<skill-name>/`).

Each skill directory:

```
<skill-name>/
  SKILL.md          # required, YAML frontmatter + body
  LICENSE.txt       # optional
  references/
  scripts/, ...
```

Frontmatter: `name` (required), `description` (required, used for discovery), arbitrary metadata. Symlinks supported for shared libraries. Sync risk: skills can carry executable scripts — preserve permissions and respect symlinks.

### Memory / Context

No first-party "memory bank" convention. The community pattern (GreatScottyMac/roo-code-memory-bank) stores `activeContext.md`, `progress.md`, `decisions.md`, `productContext.md` under `memory-bank/`. Treat as ordinary Markdown referenced by rules.

### `.rooignore`

`<project>/.rooignore` — single file, `.gitignore` syntax. Hot-reloaded.

### VS Code Settings (`settings.json`)

`roo-cline.*` keys:

- `roo-cline.allowedCommands` — string[] of glob-prefix patterns auto-approved.
- `roo-cline.deniedCommands` — string[] always blocked.
- `roo-cline.commandExecutionTimeout` — seconds (0 = no timeout).
- `roo-cline.commandTimeoutAllowlist` — patterns exempt from timeout.
- `roo-cline.customStoragePath` — override extension storage dir.
- `roo-cline.autoImportSettingsPath` — JSON imported on VS Code start.
- `roo-cline.codeIndex.*` — indexing tuning.

Key-level extraction only.

### Marketplace

In-extension installer writes into the global/project files above. Mode (global) → `custom_modes.yaml`; Mode (project) → `.roomodes`; MCP (global) → `mcp_settings.json`; MCP (project) → `.roo/mcp.json`.

### Secrets / API Keys

Provider credentials in VS Code SecretStorage (OS keychain). Not on disk; must not be synced (discussion #2690). Settings export can optionally include secrets but emits a separate encrypted JSON.

### Path summary

Project: `.roomodes`, `.roo/rules/`, `.roo/rules-<mode>/`, `.roorules`, `.roorules-<mode>`, `.roo/commands/`, `.roo/skills/`, `.roo/skills-<mode>/`, `.roo/mcp.json`, `.rooignore`, `AGENTS.md`, `.vscode/settings.json` (only `roo-cline.*`).

User: `<settings-dir>/custom_modes.yaml`, `<settings-dir>/mcp_settings.json`. Plus `~/.roo/`: `rules/`, `rules-<mode>/`, `commands/`, `skills/`, `skills-<mode>/`; legacy `~/.roorules*`. Plus user `settings.json` (`roo-cline.*` keys only).

### Sources

- [Customizing Modes](https://docs.roocode.com/features/custom-modes)
- [Custom Instructions](https://docs.roocode.com/features/custom-instructions)
- [Slash Commands](https://docs.roocode.com/features/slash-commands)
- [run_slash_command tool](https://docs.roocode.com/advanced-usage/available-tools/run-slash-command)
- [Skills](https://docs.roocode.com/features/skills)
- [Using MCP in Roo Code](https://docs.roocode.com/features/mcp/using-mcp-in-roo)
- [Roo Code Marketplace](https://docs.roocode.com/features/marketplace)
- [Using .rooignore](https://docs.roocode.com/features/rooignore)
- [Import, Export, and Reset Settings](https://docs.roocode.com/features/settings-management)
- [Auto-Approving Actions](https://docs.roocode.com/features/auto-approving-actions)
- [Boomerang Tasks](https://docs.roocode.com/features/boomerang-tasks)
- [Roo Code GitHub repo](https://github.com/RooCodeInc/Roo-Code)
- [Roo-Code/.roomodes (canonical example)](https://github.com/RooCodeInc/Roo-Code/blob/main/.roomodes)
- [Roo-Code-Docs/AGENTS.md](https://github.com/RooCodeInc/Roo-Code-Docs/blob/main/AGENTS.md)
- [Issue #10750 — move global custom_modes.yaml](https://github.com/RooCodeInc/Roo-Code/issues/10750)
- [Issue #9862 — MCP Settings UI removes JSON formatting](https://github.com/RooCodeInc/Roo-Code/issues/9862)
- [Discussion #2690 — credentials/API key storage and sync](https://github.com/RooVetGit/Roo-Code/discussions/2690)
- [Custom Instructions and Rules (DeepWiki)](https://deepwiki.com/RooCodeInc/Roo-Code/9.4-custom-instructions-and-rules)
- [Slash Commands System (DeepWiki)](https://deepwiki.com/RooCodeInc/Roo-Code/10-slash-commands-system)
- [Roo Code on VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=RooVeterinaryInc.roo-cline)

---

## Sourcegraph Cody (and Amp)

Sourcegraph ships two agentic products that a sync tool may encounter on the same workstation: **Cody** (the long-running AI coding assistant, primarily a VS Code/JetBrains/Visual Studio extension talking to a Sourcegraph backend) and **Amp** (a newer standalone agent released 2025 with a CLI and a thin VS Code extension). On-disk surfaces overlap conceptually but use completely different files. Handle separately.

### Cody Custom Commands (`cody.json`)

The canonical user-authored Cody artifact. Plain JSON at two scopes:

| Scope | Path (all OSes) |
|---|---|
| User-level | `~/.vscode/cody.json` |
| Workspace-level | `<project-root>/.vscode/cody.json` |

User-level is literally `~/.vscode/cody.json` on Linux/macOS/Windows. Not under `~/.config/Code/User/` and not under VS Code extension storage. Sourcegraph docs describe this as the "User Settings" location.

Single top-level `commands` object, keyed by slash-command name (identity). Each:
- `description` (string, optional)
- `prompt` (string, required)
- `mode` (enum, optional, default `"ask"`) — `"ask"` (chat), `"edit"` (replace selection), `"insert"` (above selection)
- `context` (object, optional):
  - `selection` (bool) — selected code
  - `currentFile` (bool) — full file
  - `currentDir` (bool) — sibling files
  - `openTabs` (bool) — all open tabs
  - `codebase` (bool) — embeddings / remote search
  - `command` (string) — shell command stdout included as context
  - `none` (bool) — disable all auto context

```json
{
  "commands": {
    "commit-message": {
      "description": "Generate a Conventional Commits message from staged diff",
      "prompt": "Write a Conventional Commits message for the staged diff.",
      "mode": "ask",
      "context": {
        "selection": false,
        "currentFile": false,
        "command": "git diff --staged"
      }
    },
    "add-types": {
      "description": "Add TypeScript types to selection",
      "prompt": "Add precise TypeScript type annotations. Do not change runtime behaviour.",
      "mode": "edit",
      "context": { "selection": true, "currentFile": true }
    }
  }
}
```

Sync risks: workspace `.vscode/cody.json` is normally committed (out of scope); only user-level is in scope. `context.command` can execute arbitrary shell on import — treat as executable payload.

### Cody Prompts (cloud / Prompt Library)

The newer Prompts feature is **server-side**: lives in the Sourcegraph instance's Prompt Library, fetched via API, not local files. Custom Commands (`cody.json`) remain the only locally-stored prompt artifact.

### Cody "Rules" / Pre-instructions

Cody does not expose Cursor-style `.cursor/rules/*.mdc` or `AGENTS.md` rules folders. Closest equivalents:

- `cody.chat.preInstruction` — single string VS Code setting prepended to every chat turn.
- Enterprise admin pre-instructions — set in Sourcegraph instance site config (cloud-only).

Sync risk: `cody.chat.preInstruction` lives inside `settings.json` — can only be synced as part of a broader VS Code settings sync.

### MCP servers (via OpenCtx)

No dedicated `mcp.json`. MCP servers wired through OpenCtx MCP provider, configured in VS Code `settings.json` under `openctx.providers`. Only **stdio** transport:

```jsonc
{
  "cody.experimental.noodle": true,
  "openctx.enable": true,
  "openctx.providers": {
    "https://openctx.org/npm/@openctx/provider-modelcontextprotocol": {
      "nodeCommand": "node",
      "mcp.provider.uri": "file:///path/to/servers/build/linear/index.js",
      "mcp.provider.args": ["LINEAR_API_KEY_VALUE"]
    }
  }
}
```

VS Code `settings.json` path:
- Linux: `~/.config/Code/User/settings.json`
- macOS: `~/Library/Application Support/Code/User/settings.json`
- Windows: `%APPDATA%\Code\User\settings.json`

Identity: provider URL key. Sync risks: `mcp.provider.args` frequently embeds API keys; absolute `file://` URIs encode machine-specific paths.

### Cody-specific VS Code settings keys

User-customizable `cody.*` keys (subset):

- `cody.serverEndpoint`
- `cody.chat.preInstruction` — de-facto user "rules"
- `cody.autocomplete.enabled`
- `cody.autocomplete.advanced.provider`
- `cody.autocomplete.advanced.serverEndpoint`
- `cody.autocomplete.advanced.model`
- `cody.commandCodeLenses`
- `cody.experimental.*`
- `cody.codebase`

Auth tokens stored separately in the OS keychain — never export.

### Cody Context Filters (enterprise, site-config-only)

`cody.contextFilters` with `include`/`exclude` arrays of `repoNamePattern` RE2 regexes — set in Sourcegraph instance site config by an admin. **Enterprise/cloud-only — do not attempt to sync**.

### Sourcegraph Amp — `settings.json`

Workspace settings override user settings; both prefixed `amp.`.

| Scope | Path |
|---|---|
| User (global), Linux/macOS | `$XDG_CONFIG_HOME/amp/settings.json` or `~/.config/amp/settings.json` |
| User (global), Windows | `%APPDATA%\amp\settings.json` |
| User override | env var `AMP_SETTINGS_FILE` |
| Workspace | nearest `.amp/settings.json` (or `.amp/settings.jsonc`) walking up |

```jsonc
{
  "amp.notifications.enabled": true,
  "amp.mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"]
    },
    "linear-remote": {
      "url": "https://mcp.linear.app/sse",
      "headers": { "Authorization": "Bearer ${LINEAR_TOKEN}" }
    }
  },
  "amp.tools.disable": ["edit_file"],
  "amp.commands.allowlist": ["git status", "npm run build"],
  "amp.commands.strict": false,
  "amp.dangerouslyAllowAll": false
}
```

Notes:
- `amp.mcpServers` supports local stdio and remote (`url`+`headers`); `${VAR}` interpolation.
- MCP servers in global settings (or via `--mcp-config`) are auto-approved; workspace-declared require interactive approval.
- `amp.commands.allowlist` is a flat array of literal prefixes.

### Amp memory files — `AGENTS.md` family

Amp follows the cross-vendor `AGENTS.md` convention. Load order:

1. **System-wide global**: `$HOME/.config/amp/AGENTS.md` and `$HOME/.config/AGENTS.md` (both if present).
2. **Repo / parent chain**: every `AGENTS.md` from CWD up to `$HOME`.
3. **Subtree**: additional `AGENTS.md` lazily attached when Amp reads a file inside its subtree.
4. **Legacy fallback**: if no `AGENTS.md` exists in a directory, `AGENT.md` (singular) or `CLAUDE.md` is used.

Windows: `%USERPROFILE%\.config\amp\AGENTS.md`, `%USERPROFILE%\.config\AGENTS.md`. Sync risk: workspace-scope is usually committed; only the two `$HOME/.config/...` are user-level. `CLAUDE.md` aliasing needs dedup.

### Amp Toolbox (custom tools)

`AMP_TOOLBOX` env var points to a directory of executable scripts; each invoked with `TOOLBOX_ACTION=describe` at startup, emits key/value lines to stdout to register as a tool. No fixed canonical directory — commonly `~/.amp/toolbox/` or `~/.config/amp/toolbox/`. Treat as opt-in payload sync only.

### Amp threads / session storage

Threads, login tokens, telemetry under `~/.local/share/amp/` (Linux), `~/Library/Application Support/amp/` (macOS), `%LOCALAPPDATA%\amp\` (Windows). Runtime state — exclude.

### Summary

| Artifact | Path | Identity |
|---|---|---|
| Cody custom commands (user) | `~/.vscode/cody.json` | command name |
| Cody chat pre-instruction + `cody.*` | VS Code `settings.json` | setting key |
| OpenCtx / MCP provider | VS Code `settings.json` → `openctx.providers` | provider URL key |
| Amp user settings | `~/.config/amp/settings.json` | `amp.*` key |
| Amp user memory | `~/.config/amp/AGENTS.md`, `~/.config/AGENTS.md` | absolute path |
| Amp toolbox scripts | `$AMP_TOOLBOX` dir | filename |

Enterprise/cloud-only (do NOT sync): `cody.contextFilters` site config, Cody Prompt Library entries, admin pre-instructions, Sourcegraph auth tokens.

### Sources

- [Cody Commands](https://sourcegraph.com/docs/cody/capabilities/commands)
- [Cody Custom Commands](https://docs.sourcegraph.com/cody/custom-commands)
- [Cody Prompts](https://sourcegraph.com/docs/cody/capabilities/prompts)
- [Cody Installing in VS Code](https://sourcegraph.com/docs/cody/clients/install-vscode)
- [Cody OpenCtx](https://sourcegraph.com/docs/cody/capabilities/openctx)
- [Cody Agentic Context Fetching](https://sourcegraph.com/docs/cody/capabilities/agentic-context-fetching)
- [Cody Manage Context / Context Filters](https://sourcegraph.com/docs/cody/capabilities/ignore-context)
- [Cody supports MCP (blog)](https://sourcegraph.com/blog/cody-supports-anthropic-model-context-protocol)
- [Cody VS Code v1.16 release notes](https://sourcegraph.com/blog/cody-vscode-1-16-0-release)
- [Admin pre-instructions](https://sourcegraph.com/changelog/admin-pre-instructions)
- [OpenCtx MCP provider](https://openctx.org/docs/providers/modelcontextprotocol)
- [Amp Owner's Manual](https://ampcode.com/manual)
- [Amp Workspace Settings](https://ampcode.com/news/cli-workspace-settings)
- [Amp AGENT.md announcement](https://ampcode.com/news/AGENT.md)
- [Amp examples & guides](https://github.com/sourcegraph/amp-examples-and-guides)

---

## Windsurf (Codeium)

Windsurf (formerly Codeium IDE, acquired by Cognition 2025) is an AI-native VS Code fork whose agent is named **Cascade**. User-authored customization is split between a user-scope directory (`~/.codeium/windsurf/`) and a project-scope directory (`.windsurf/` at repo root). Both hold a mix of Markdown (rules, workflows, skills) and JSON (MCP, hooks). VS Code-style `settings.json` carries IDE settings under `windsurf.*` / `cascade.*`, but most AI state lives in the two `.windsurf` / `.codeium/windsurf` trees.

### Rules

**Global rules** (always-on, all workspaces):
- Linux/macOS: `~/.codeium/windsurf/memories/global_rules.md`
- Windows: `%USERPROFILE%\.codeium\windsurf\memories\global_rules.md`
- Plain Markdown, no frontmatter.

**Workspace rules**:
- New form: `<project>/.windsurf/rules/<name>.md` — each rule its own Markdown file with YAML frontmatter.
- Legacy form: `<project>/.windsurfrules` — single file at repo root.

Combined budget for global + workspace = **12,000 characters**; on overflow, global wins and workspace is truncated.

Workspace rule frontmatter:

```markdown
---
trigger: glob          # always_on | manual | model_decision | glob
description: One-line summary used when trigger=model_decision
globs: **/*.test.ts    # required when trigger=glob; can be a list
---
All test files must use describe/it blocks and mock external APIs.
```

Identity: `description` (for `model_decision`) and file basename. Sync risk: filename collisions on `.windsurf/rules/*.md`; 12k char budget means naive merging can overflow.

### Workflows

Per-project Markdown exposed as `/slash-commands` in Cascade.

- Path: `<project>/.windsurf/workflows/<workflow-name>.md`
- No user-scope workflows directory.
- Invoked as `/<workflow-name>`; workflows can call other workflows.
- Manual-only — Cascade never auto-invokes.

```markdown
---
name: pre-pr-check
description: Run before opening a PR — lint, tests, type check, and stage diff
auto_execute_steps:
  - read_file
  - run_command
---

# Pre-PR Check Workflow
1. Run `pnpm lint`
2. Run `pnpm test`
3. ...
```

Identity: `name` (and basename which produces the slash command).

### Memories (auto-generated)

Cascade autogenerates memories from conversations and stores them locally — **not** in the repo.

- Linux/macOS: `~/.codeium/windsurf/memories/`
- Windows: `%USERPROFILE%\.codeium\windsurf\memories\`

`global_rules.md` is user-edited global rules; auto-generated workspace memories live alongside, keyed by a **workspace hash derived from the absolute workspace directory path**. Two machines with the same repo at different paths produce different memory buckets — Windsurf treats workspace memories as machine-local and path-bound, never version-controlled. Format is opaque to Windsurf, not stable Markdown.

Sync risk: **high**. Workspace memories are intentionally machine-local and path-keyed; copying breaks the hash mapping. Treat `memories/` as **non-syncable** except for `global_rules.md`.

### MCP servers

Single user-scope JSON shared by all workspaces.

- Linux/macOS: `~/.codeium/windsurf/mcp_config.json`
- Windows: `%USERPROFILE%\.codeium\windsurf\mcp_config.json`

Schema mirrors Claude Desktop's `claude_desktop_config.json`. Three transports: stdio, Streamable HTTP, SSE.

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${env:GITHUB_PAT}"
      }
    },
    "remote-http-mcp": {
      "serverUrl": "https://mcp.example.com/mcp",
      "headers": { "API_KEY": "${env:MCP_API_KEY}" }
    },
    "my-sse-server": {
      "serverUrl": "https://mcp.example.com/sse"
    }
  }
}
```

Interpolation: `${env:VAR_NAME}` in `command`, `args`, `env`, `serverUrl`, `url`, `headers`. Both `serverUrl` and `url` accepted for remote. Sync risk: medium — `env` often contains secrets/PATs.

### Custom / slash commands

Windsurf has **no separate slash-command concept**. `/name` slash commands in Cascade are the workflows from §Workflows. No parallel directory like `~/.claude/commands/`.

### Cascade Hooks

Introduced late 2025. JSON files at three scopes, merged system → user → workspace:

- System: platform-dependent system path (MDM / enterprise policy)
- User: `~/.codeium/windsurf/hooks.json` (Linux/macOS), `%USERPROFILE%\.codeium\windsurf\hooks.json` (Windows)
- Workspace: `<project>/.windsurf/hooks.json`

Events (as of 2026): `pre_read_code`, `post_read_code`, `pre_write_code`, `post_write_code`, `pre_run_command`, `post_run_command`, `pre_mcp_tool_use`, `post_mcp_tool_use`, `pre_user_prompt`, `post_cascade_response`, `post_cascade_response_with_transcript`, `post_setup_worktree`.

Each event maps to an array. Commands passed event JSON on stdin. Platform-specific commands use separate `command` (POSIX) and `powershell` (Windows) fields:

```json
{
  "hooks": {
    "pre_run_command": [
      {
        "command": "/usr/local/bin/policy-check.sh",
        "powershell": "C:\\tools\\policy-check.ps1",
        "timeout_ms": 5000
      }
    ],
    "post_write_code": [
      { "command": "pnpm exec prettier --write \"${file_path}\"" }
    ]
  }
}
```

Identity: event name + ordinal. Sync risk: high if commands reference absolute paths; `command`/`powershell` split helps cross-OS sync. Enterprise cloud-managed hooks (MDM to system scope) are **not local files** — non-syncable.

### Cascade Skills

A 2026 addition mirroring Claude Code's Skills.

- Workspace: `<project>/.windsurf/skills/<skill-name>/SKILL.md` (plus supporting files)
- User-scope counterpart at `~/.codeium/windsurf/skills/<skill-name>/SKILL.md` (skills exposed via same Customizations panel)

YAML frontmatter (minimum `name` and `description`). Progressive disclosure: only `name` + `description` exposed until invoked or `@mention`ed.

```markdown
---
name: deploy-staging
description: Deploy current branch to staging, run smoke tests, post Slack update
---
1. Read `deployment-checklist.md` from this folder.
2. Run `./scripts/deploy.sh staging`.
3. ...
```

No separate "persona" concept; persona-like behavior in rules or skills.

### Settings (`settings.json`)

Standard VS Code `settings.json`:
- Linux: `~/.config/Windsurf/User/settings.json`
- macOS: `~/Library/Application Support/Windsurf/User/settings.json`
- Windows: `%APPDATA%\Windsurf\User\settings.json`

AI-relevant keys under `windsurf.*` and `cascade.*` (autocomplete, default Cascade model, telemetry, indexing exclusions). Windsurf does not publish a stable public list — treat conservatively, sync whole file only if both machines on same Windsurf version.

### Other user-authored local artifacts

- `AGENTS.md` at repo root — recognized by Cascade as always-on rules; no frontmatter; sync via repo, not user state.
- `.windsurfignore` (legacy) and `.codeiumignore` at repo root — control what Cascade indexes.
- Per-workspace conversation history, indexed embeddings, Cascade transcripts under `~/.codeium/windsurf/` in opaque subdirectories — **non-syncable**.
- Enterprise cloud config (team rules, allow/deny lists, hook policy) is **server-side only** — flag as non-syncable.

### Summary (sync-relevant paths)

| Category | User scope | Workspace scope | Format |
|---|---|---|---|
| Global rules | `~/.codeium/windsurf/memories/global_rules.md` | — | Markdown |
| Workspace rules | — | `.windsurf/rules/*.md`, `.windsurfrules` | Markdown + frontmatter |
| Workflows | — | `.windsurf/workflows/*.md` | Markdown + frontmatter |
| Skills | `~/.codeium/windsurf/skills/<name>/SKILL.md` | `.windsurf/skills/<name>/SKILL.md` | Markdown + frontmatter + assets |
| MCP servers | `~/.codeium/windsurf/mcp_config.json` | — | JSON |
| Hooks | `~/.codeium/windsurf/hooks.json` | `.windsurf/hooks.json` | JSON |
| Memories (auto) | `~/.codeium/windsurf/memories/` (hashed) | — | Opaque — **non-syncable** |
| IDE settings | `settings.json` (per-OS VS Code path) | `.vscode/settings.json` | JSON |
| Ignore lists | — | `.windsurfignore`, `.codeiumignore` | Text |

Identity is filename-based for Markdown; key-based for JSON. Safe to sync: `global_rules.md`, `.windsurf/rules/*`, `.windsurf/workflows/*`, `.windsurf/skills/*` (and user-scope mirror), `mcp_config.json` (with secret redaction), `hooks.json` (both scopes, watching for absolute-path drift). Unsafe: workspace-hash-keyed `memories/`, opaque conversation/index caches, cloud-managed enterprise policy.

### Sources

- [Cascade Memories](https://docs.windsurf.com/windsurf/cascade/memories)
- [Cascade Workflows](https://docs.windsurf.com/windsurf/cascade/workflows)
- [Cascade MCP Integration](https://docs.windsurf.com/windsurf/cascade/mcp)
- [Cascade Hooks](https://docs.windsurf.com/windsurf/cascade/hooks)
- [Cascade Skills](https://docs.windsurf.com/windsurf/cascade/skills)
- [Cascade overview](https://docs.windsurf.com/windsurf/cascade/cascade)
- [Wave 8: Cascade Customization Features](https://windsurf.com/blog/windsurf-wave-8-cascade-customization-features)
- [Windsurf Editor Changelog](https://windsurf.com/changelog)
- [Creating & Modifying Rules](https://windsurf.com/university/general-education/creating-modifying-rules)
- [Using Workflows](https://windsurf.com/university/general-education/workflows)
- [Windsurf SWE-1.5 & Cascade Hooks (Nov 2025)](https://www.digitalapplied.com/blog/windsurf-swe-1-5-cascade-hooks-november-2025)
- [Windsurf MCP Setup Guide (2026)](https://natoma.ai/blog/how-to-enabling-mcp-in-windsurf)
- [Team-Shared Memory](https://www.iamraghuveer.com/posts/windsurf-team-shared-memory/)
- [Windsurf Rules Guide](https://design.dev/guides/windsurf-rules/)
- [Using Windsurf Rules, Workflows, and Memories](https://www.paulmduvall.com/using-windsurf-rules-workflows-and-memories/)

---

## Zed

Zed (zed.dev) is a Rust-built collaborative editor whose AI features live in the **Agent Panel** (previously "Assistant Panel"). User-authored AI customisations span `settings.json`, `keymap.json`, plain-text `.rules` files in projects, a binary LMDB database for the Rules Library, and (for slash commands and agent servers) installed Zed extensions. Conversation state (threads) is a SQLite/LMDB database — out of scope for sync.

**Config root per OS** (Zed reads its dotfiles from here):
- Linux: `~/.config/zed/` (respects `$XDG_CONFIG_HOME`)
- macOS: `~/.config/zed/` (Zed does NOT use `~/Library/Application Support/` for user-edited config; that path is for installed extensions + thread DBs)
- Windows: `%APPDATA%\Zed\`

Within: `settings.json`, `keymap.json`, `prompts/prompts-library-db.0.mdb`, `themes/*.json`. Project overrides at `<project>/.zed/settings.json` and `<project>/.rules`.

### Custom Agents / Profiles

Configured under `agent.profiles` in `settings.json`. Key inside `profiles` = profile ID (identity); human-readable name is `name`. Built-in profile IDs: `write`, `ask`, `minimal`.

```json
{
  "agent": {
    "default_profile": "write",
    "profiles": {
      "custom-profile": {
        "name": "Custom Profile",
        "tools": {
          "fetch": true,
          "thinking": true,
          "copy_path": false,
          "find_path": false,
          "delete_path": false,
          "create_directory": false,
          "list_directory": false,
          "diagnostics": false,
          "read_file": false,
          "open": false,
          "move_path": false,
          "grep": false,
          "edit_file": false,
          "terminal": false
        },
        "enable_all_context_servers": false,
        "context_servers": {
          "your-server": {
            "tools": { "tool_name": true, "another_tool": false }
          }
        }
      }
    }
  }
}
```

Fields: `name`, `tools` (built-in tool → bool), `enable_all_context_servers` (default off), `context_servers` (map of MCP-server-ID → `{ "tools": { ... } }`). Sync risk: profile IDs are namespace-free; `tools` keys are Zed-specific built-ins, not portable.

Related (under `agent`): `default_profile`, `default_model`, `tool_permissions.default` (`confirm`|`allow`, Zed ≥ 0.224.0), `always_allow_tool_actions`, `enabled`.

### Custom Slash Commands

Zed has **no user-authored slash commands as plain files**. Slash commands come from **extensions** (Rust + WebAssembly). Each extension's `extension.toml` declares its commands:

```toml
[slash_commands.encode]
description = "Base64-encode the argument"
requires_argument = true
```

Installed extensions live under platform data dirs (not config root):
- Linux: `$XDG_DATA_HOME/zed/extensions/` or `~/.local/share/zed/extensions/`
- macOS: `~/Library/Application Support/Zed/extensions/`
- Windows: `%LOCALAPPDATA%\Zed\extensions\`

User-authored handle: the installed-extensions list in `settings.json` (Zed tracks installed IDs in `extensions.json` under same data dir). Sync risk: never sync WASM `.wasm` binaries; only the manifest + source is portable. Treat installed slash-command extensions as "install list" rather than file sync.

### Prompt Library (a.k.a. Rules Library)

Stored as a single LMDB database — **not plain text**.

- Linux: `~/.config/zed/prompts/prompts-library-db.0.mdb` (some builds also report `~/.local/share/zed/prompts/prompts-library-db.0.mdb`)
- macOS: `~/.config/zed/prompts/prompts-library-db.0.mdb`
- Windows: `%APPDATA%\Zed\prompts\prompts-library-db.0.mdb`
- Flatpak: `~/.var/app/dev.zed.Zed/data/zed/prompts/prompts-library-db.0.mdb`

Each prompt: internal UUID (identity), title, body (markdown), "default" flag (default prompts auto-injected into every Agent Panel thread). No public YAML frontmatter. Third-party `rubiojr/zed-prompts` exports/imports LMDB to/from markdown.

Sync risk: LMDB is a binary memory-mapped file — concurrent writes from two Zed processes corrupt it, and byte-for-byte sync is unsafe across machines (page layout depends on architecture/page size). Portable archives should round-trip through exported markdown (title + body + `default: true|false`) keyed by UUID.

### Rules (project-level)

Plain-text at project root, auto-included every Agent Panel turn. Zed walks a fixed precedence list, first match wins:

`.rules` → `.cursorrules` → `.windsurfrules` → `.clinerules` → `.github/copilot-instructions.md` → `AGENT.md` → `AGENTS.md` → `CLAUDE.md` → `GEMINI.md`

For external agents launched via Zed (Claude Agent ACP), `CLAUDE.md` in root, subdirectories, and `.claude/` is additionally consumed. Treat `.rules` as Zed-canonical and the others as cross-tool aliases the user may share with Cursor / Claude Code / Gemini CLI.

### MCP / Context Servers

Under `context_servers` in `settings.json`. Two source types: `custom` (user-defined process) and `extension` (provided by installed extension).

```json
{
  "context_servers": {
    "my-mcp-server": {
      "source": "custom",
      "enabled": true,
      "command": "/usr/local/bin/my-mcp",
      "args": ["--stdio"],
      "env": { "API_KEY": "${MY_API_KEY}" }
    },
    "postgres-context-server": {
      "source": "extension",
      "enabled": true,
      "settings": { "database_url": "postgres://localhost/dev" }
    }
  }
}
```

Fields: `source` (`custom`|`extension`), `enabled`, `command` (custom only), `args` (custom only), `env` (custom only), `settings` (extension-defined). Sync risk: `command` paths and `env` API-keys are workstation-specific; server IDs collide cross-tool.

### Memory / Threads — out of scope

Agent-panel conversation history:
- macOS: `~/Library/Application Support/Zed/threads/threads.db` (SQLite) + `~/Library/Application Support/Zed/db/0-stable/db.sqlite`
- Linux: `~/.local/share/zed/threads/threads-db.1.mdb` (LMDB) + SQLite alongside
- Flatpak: `~/.var/app/dev.zed.Zed/data/zed/threads/threads-db.1.mdb`
- Windows: `%LOCALAPPDATA%\Zed\threads\`, `%LOCALAPPDATA%\Zed\db\`

JSON+Zstd blobs in DB. State, do not sync.

### Settings — AI-related top-level keys

`settings.json` at `~/.config/zed/settings.json` (Linux/macOS) or `%APPDATA%\Zed\settings.json` (Windows). Project override at `<project>/.zed/settings.json`. AI-related keys:

- `agent` — sub-keys: `enabled`, `default_profile`, `default_model` (`{provider, model}`), `profiles`, `tool_permissions` (`default`: `"confirm"|"allow"`), `always_allow_tool_actions`, `inline_alternatives`, `dock`, `single_file_review`, `notify_when_agent_waiting`.
- `assistant` — legacy alias.
- `context_servers` — see above.
- `agent_servers` — external ACP agents (Claude Agent, Codex, Gemini CLI):
  ```json
  {
    "agent_servers": {
      "claude-acp": {
        "type": "registry",
        "env": { "CLAUDE_CODE_EXECUTABLE": "/opt/claude/bin/claude" }
      },
      "my-custom": {
        "type": "custom",
        "command": "node",
        "args": ["~/projects/agent/index.js", "--acp"],
        "env": {}
      }
    }
  }
  ```
- `language_models` — per-provider `{api_url, version, available_models}`. API keys **not** stored here — Zed puts them in OS keyring.
  ```json
  {
    "language_models": {
      "anthropic": { "api_url": "https://api.anthropic.com/v1" },
      "openai": { "version": "1", "api_url": "https://api.openai.com/v1",
                  "available_models": [ { "name": "gpt-4o", "max_tokens": 128000 } ] }
    }
  }
  ```
- `features.edit_prediction_provider` — Zeta vs Copilot vs Supermaven.

### Keybindings

`keymap.json`:
- Linux/macOS: `~/.config/zed/keymap.json`
- Windows: `%APPDATA%\Zed\keymap.json`

JSON array of `{ "context": "...", "bindings": { "<keychord>": "<action>" } }`. AI-relevant actions: `agent::ToggleFocus`, `agent::NewThread`, `agent::ManageProfiles` (default `cmd-alt-p`/`ctrl-alt-p`), `assistant::InlineAssist`, `agent::OpenRulesLibrary`. Only `agent::*` / `assistant::*` actions are AI-relevant for sync.

### Anything else user-authored

- `themes/*.json` — not AI-related.
- `extensions.json` (Zed-managed install list) — co-located with installed extensions in data dir.
- `<project>/.zed/settings.json` and `<project>/.zed/tasks.json` — project-scoped overrides; leave to the project repo.

### Sources

- [Agent Panel](https://zed.dev/docs/ai/agent-panel)
- [Agent Settings](https://zed.dev/docs/ai/agent-settings)
- [AI Rules](https://zed.dev/docs/ai/rules)
- [Model Context Protocol (MCP) in Zed](https://zed.dev/docs/ai/mcp)
- [External Agents](https://zed.dev/docs/ai/external-agents)
- [LLM Providers](https://zed.dev/docs/ai/llm-providers)
- [Configuration overview](https://zed.dev/docs/ai/configuration)
- [Configuring Zed](https://zed.dev/docs/configuring-zed)
- [Key Bindings](https://zed.dev/docs/key-bindings)
- [Slash Command Extensions](https://zed.dev/docs/extensions/slash-commands)
- [Installing Extensions](https://zed.dev/docs/extensions/installing-extensions)
- [Developing Extensions](https://zed.dev/docs/extensions/developing-extensions)
- [Agent Server Extensions](https://zed.dev/docs/extensions/agent-servers)
- [Tool Permissions](https://zed.dev/docs/ai/tool-permissions)
- [Where are the rules in the rules library locally stored? (#33266)](https://github.com/zed-industries/zed/discussions/33266)
- [Where does Zed store Agent Conversation History? (#32335)](https://github.com/zed-industries/zed/discussions/32335)
- [Make Rules Library plaintext instead of LMDB (#34154)](https://github.com/zed-industries/zed/issues/34154)
- [Prompt Library Export/Backup (#14559)](https://github.com/zed-industries/zed/discussions/14559)
- [rubiojr/zed-prompts](https://github.com/rubiojr/zed-prompts)
- [zed-industries/zed docs source — rules.md](https://github.com/zed-industries/zed/blob/main/docs/src/ai/rules.md)
