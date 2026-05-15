# opencode Integration Research

Research note prepared for `agents_sync` — evaluates the integration of
[opencode](https://opencode.ai) as a fourth `agentic_tool` alongside Claude
Code, Codex, and Google Antigravity.

- **Status**: research only. No code changes proposed here; this document
  precedes an eventual v0.5 implementation plan.
- **Date**: 2026-05-15.
- **Method**: 8 parallel deep-search agents covering overview, agent format,
  skill/command format, paths, ecosystem, cross-tool comparison, canonical
  mapping, and an implementation checklist. Findings reconciled below.
- **Reading order**: §1 (what opencode is) → §3 (paths) → §4–§5 (the two
  customization formats) → §7 (canonical mapping) → §8 (implementation
  checklist). §2 and §6 are reference matter; §9 lists open questions.

---

## Table of Contents

1. [What opencode is](#1-what-opencode-is)
2. [Customization surfaces and sync classification](#2-customization-surfaces-and-sync-classification)
3. [On-disk paths, per OS](#3-on-disk-paths-per-os)
4. [Agent file format](#4-agent-file-format)
5. [Skill and Command formats](#5-skill-and-command-formats)
6. [Cross-tool comparison](#6-cross-tool-comparison)
7. [Mapping into the `agents_sync` canonical](#7-mapping-into-the-agents_sync-canonical)
8. [Implementation checklist](#8-implementation-checklist)
9. [Open questions and known unknowns](#9-open-questions-and-known-unknowns)
10. [Recommendation](#10-recommendation)
11. [Sources](#11-sources)

---

## 1. What opencode is

**opencode** is an open-source, terminal-first AI coding agent. It is built
and maintained by the same team behind SST (Serverless Stack): Jay V, Frank
Wang, Dax Raad, and Adam Elmore. The canonical repository was historically
`github.com/sst/opencode` and is now `github.com/anomalyco/opencode` after
the GitHub organisation was renamed in early 2026 (the legacy URL
redirects).

| Property | Value |
|---|---|
| Licence | MIT |
| Implementation | TypeScript, distributed as a Bun-compiled single-file binary (no Node.js / Bun required at runtime) |
| Repository | <https://github.com/anomalyco/opencode> (was `sst/opencode`) |
| Docs | <https://opencode.ai/docs/> |
| Release as of 2026-05-15 | v1.15.0; multiple releases per week is normal cadence |
| Activation modes | Interactive TUI (`opencode`), non-interactive (`opencode run …`), server (`opencode serve`) |
| Clients | TUI, beta desktop app (Electron/Tauri), IDE extensions for VS Code / Cursor / Windsurf / Zed / VSCodium |
| Providers | 75+ via the Vercel AI SDK and Models.dev — Anthropic, OpenAI, Google, xAI, Bedrock, Azure, OpenRouter, plus local Ollama / LM Studio / llama.cpp |
| Install | `curl -fsSL https://opencode.ai/install \| bash`, `brew install opencode`, `choco install opencode`, `scoop install opencode`, `npm i -g opencode-ai` |
| Binary install path | `$OPENCODE_INSTALL_DIR` → `$XDG_BIN_DIR` → `$HOME/bin` → `$HOME/.opencode/bin` |

**Disambiguation.** A separate, unrelated project once lived at
`github.com/opencode-ai/opencode` (Go + Bubble Tea); it was archived and
continues under the name "Crush". Everything below concerns only the
SST / anomalyco TypeScript project at <https://opencode.ai>.

---

## 2. Customization surfaces and sync classification

opencode exposes nine distinct customization surfaces. Two are obvious sync
targets, four are plausible future targets, three are firmly out of scope
(per-machine, secrets, or runtime state).

| Surface | Location | Class | Notes |
|---|---|:---:|---|
| **Agents** | `~/.config/opencode/agents/*.md` | **A** | In scope for this integration |
| **Skills** | `~/.config/opencode/skills/<name>/SKILL.md` | **A** | Open Agent Skills Spec — in scope |
| **Commands** | `~/.config/opencode/commands/<name>.md` | **A**? | User-invoked slash commands; same wire format as agents but no cross-tool equivalent in v0.4 — see §5 |
| **Global rules** | `~/.config/opencode/AGENTS.md` | **A**? | Maps to `~/.claude/CLAUDE.md` etc. — possible future `customization_type = "rule"` |
| **MCP servers** | `opencode.json` → `"mcp"` block | **B** | Possible future `customization_type = "mcp_server"`; embeds machine-local commands and env vars |
| **Plugins** (TS/JS) | `~/.config/opencode/plugins/*.ts` | **B** | Executable code; needs trust/sandbox decision before sync |
| **Custom tools** (TS/JS) | `~/.config/opencode/tools/*.ts` | **B** | Same trust caveat as plugins |
| **Permission profiles** | `opencode.json` → `"permission"` | **B** | `external_directory` rules embed machine-local paths |
| **Provider options** (non-secret) | `opencode.json` → `"provider"` | **B** | Strip API keys |
| Themes | `~/.config/opencode/themes/*.json` | C | Aesthetic, per-machine |
| TUI prefs / keybinds | `~/.config/opencode/tui.json` | C | Per-machine habit |
| API credentials | `~/.local/share/opencode/auth.json` | C | Secrets — never sync |
| MCP auth tokens | `~/.local/share/opencode/mcp-auth.json` | C | Secrets — never sync |
| Session history | `~/.local/share/opencode/storage/` | C | Runtime state — never sync |

Legend: **A** = strong sync candidate, in current `customization_type`
taxonomy; **B** = needs a new `customization_type` and/or field-stripping
strategy before sync is safe; **C** = explicitly excluded by design.

---

## 3. On-disk paths, per OS

opencode uses [`xdg-basedir`](https://www.npmjs.com/package/xdg-basedir) for
path resolution. The runtime answer on any given machine is authoritatively
given by `opencode debug paths`.

### Documented paths

| Surface | Linux | macOS | Windows |
|---|---|---|---|
| Global config file | `$XDG_CONFIG_HOME/opencode/opencode.jsonc` (default `~/.config/opencode/opencode.jsonc`; `.json` also accepted) | `~/.config/opencode/opencode.jsonc` | `%USERPROFILE%\.config\opencode\opencode.jsonc` (documented) — **but see Windows caveat** |
| Agents | `~/.config/opencode/agents/*.md` | `~/.config/opencode/agents/*.md` | `%APPDATA%\opencode\agents\*.md` (runtime) / `%USERPROFILE%\.config\opencode\agents\*.md` (docs) |
| Skills | `~/.config/opencode/skills/<name>/SKILL.md` | same | same caveat as Agents |
| Commands | `~/.config/opencode/commands/*.md` | same | same caveat |
| Global `AGENTS.md` | `~/.config/opencode/AGENTS.md` | same | same caveat |
| Plugins | `~/.config/opencode/plugins/*.ts` | same | same caveat |
| State | `~/.local/state/opencode/` | same | `%LOCALAPPDATA%\opencode\state\` |
| Data (sessions, auth) | `~/.local/share/opencode/` | same | `%LOCALAPPDATA%\opencode\data\` |
| Cache | `~/.cache/opencode/` | same | `%LOCALAPPDATA%\opencode\cache\` |
| Log | `~/.local/share/opencode/log/` | same | `%LOCALAPPDATA%\opencode\log\` |

### Project-level paths (mirrored under `<project>/.opencode/`)

`.opencode/opencode.{json,jsonc}`, `.opencode/agents/`, `.opencode/skills/`,
`.opencode/commands/`, `.opencode/plugins/`, `.opencode/themes/`,
`.opencode/modes/`. Walking up from CWD to git root is the discovery
strategy.

### Environment overrides

- `XDG_CONFIG_HOME` — honoured on Linux (and macOS via `xdg-basedir`).
- `OPENCODE_CONFIG` — exact path to the global config file.
- `OPENCODE_CONFIG_DIR` — additional directory searched like `.opencode/`.
- `OPENCODE_DISABLE_CLAUDE_CODE=1`, `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT=1`,
  `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` — disable cross-reads from
  `~/.claude/`.

### Cross-tool reads opencode already performs natively

opencode walks **both** its own `~/.config/opencode/skills/` **and** the
peer locations `~/.claude/skills/` and `~/.agents/skills/`. It also reads
`~/.claude/CLAUDE.md` as a fallback for global rules. It does **not** read
`~/.gemini/antigravity/skills/`.

Implication for `agents_sync`: if a user already syncs Claude skills onto a
machine, opencode picks them up for free. Writing the same skill into
`~/.config/opencode/skills/` is harmless but redundant. The Antigravity
side, however, must always be reached by an explicit sync.

### Windows path caveat (open issue)

The published troubleshooting page lists Windows paths under
`%USERPROFILE%\.config\opencode\`, matching `xdg-basedir`'s default
output. However:

- Issue [#8235](https://github.com/anomalyco/opencode/issues/8235) reports
  that `xdg-basedir` does not respect Windows conventions and proposes
  switching to `env-paths`. The issue is closed but no merged-fix changelog
  entry confirms a resolution.
- Plugin-ecosystem reports
  ([antigravity-auth#251](https://github.com/NoeFabris/opencode-antigravity-auth/issues/251),
  [#265](https://github.com/NoeFabris/opencode-antigravity-auth/issues/265))
  observe that the application actually resolves `%APPDATA%\opencode\`
  at runtime for some code paths.

**Recommendation**: on Windows, probe both `%APPDATA%\opencode\` and
`%USERPROFILE%\.config\opencode\`, and surface a config option for the
user to pin the choice. Treat `opencode debug paths` as the only oracle.

---

## 4. Agent file format

opencode calls them **agents** (not "modes", "personas", or "subagents" —
those are values of the `mode` field, not the top-level concept). The file
format is Markdown with YAML frontmatter, structurally identical to a Claude
Code subagent file.

### File layout

- Single file: `<filename-stem>.md`.
- Filename stem **is** the agent identity. There is no `name` field in the
  frontmatter, and no UUID.
- User-level location per §3.
- Equivalent inline declaration: an `"agent"` object inside `opencode.json`.

### Frontmatter schema

All fields are optional except `description`.

| Field | Type | Meaning |
|---|---|---|
| `description` | string | Shown in `@`-autocomplete and routing UI |
| `mode` | `"primary"` / `"subagent"` / `"all"` | Defaults to `"all"` |
| `model` | string | Format `provider/model-id`, e.g. `anthropic/claude-sonnet-4-5` |
| `temperature` | float 0–1 | LLM sampling |
| `top_p` | float 0–1 | Nucleus sampling |
| `steps` | int | Max agentic iterations (replaces deprecated `maxSteps`) |
| `permission` | object | Per-tool tri-state — see below |
| `tools` (deprecated) | `{tool: bool}` | Superseded by `permission`; still parsed |
| `color` | string | Hex or theme token, UI only |
| `hidden` | bool | Hide from `@`-autocomplete |
| `disable` | bool | Disable the agent |
| `options` | object | Provider-specific passthrough |
| _(body)_ | Markdown | System prompt |

### Permissions

```yaml
permission:
  edit: deny                # simple form
  bash:                     # glob form
    "git *": allow
    "rm *": deny
    "*": ask
  external_directory:
    "~/projects/shared/**": allow
```

Gated tools: `read`, `edit`, `glob`, `grep`, `bash`, `task`, `skill`, `lsp`,
`question`, `webfetch`, `websearch`, `external_directory`, `doom_loop`,
`todowrite`. Last matching glob wins. Agent-level `permission` overrides
`opencode.json`-level `permission`.

### Verbatim example

```markdown
---
description: Reviews code for best practices and potential issues
mode: subagent
model: anthropic/claude-sonnet-4-5
temperature: 0.2
permission:
  edit: deny
  bash: deny
  webfetch: ask
tools:
  write: false
---

You are a code reviewer. Focus on security, performance, and maintainability.
Do not make any edits. Report findings as a numbered list.
```

### Project vs user scope

Pure path-based: `~/.config/opencode/agents/*.md` for user-level,
`<project>/.opencode/agents/*.md` for project-level. Both are loaded and
merged; project-level overrides user-level by name. Built-in agents (`build`,
`plan`, `general`, `explore`, `scout`) live in the binary and can be
partially overridden by user-defined agents of the same key.

### Known bug

`opencode agent create` writes to `.opencode/agent/` (singular) in some
versions — see issue
[#14410](https://github.com/anomalyco/opencode/issues/14410). The correct
plural form `.opencode/agents/` is the one opencode reads. `agents_sync`
must always write to the plural form.

---

## 5. Skill and Command formats

opencode distinguishes three reusable-instruction primitives. Only the
first speaks the open Agent Skills Specification:

| Primitive | User-invoked | Lazy-loaded by agent | Format |
|---|:---:|:---:|---|
| **Skill** | No | Yes | Folder + `SKILL.md` |
| **Command** | Yes (`/name`) | No | Single `.md` |
| **Rule** (`AGENTS.md`) | No (always on) | No | Single `.md` |

### Skills (open Agent Skills Specification)

Path: `~/.config/opencode/skills/<name>/SKILL.md` (and cross-reads from
`~/.claude/skills/` and `~/.agents/skills/` natively).

Frontmatter fields: `name`, `description`, `license`, `compatibility`,
`metadata`. Folder name must match the `name` field and must match
`^[a-z0-9]+(-[a-z0-9]+)*$` (1–64 chars).

Auxiliary files (`scripts/`, `references/`, `assets/`) are allowed
alongside `SKILL.md` and are loaded on demand by the agent. The
`agents_sync` sync core already propagates auxiliary files verbatim for
the `skill` `customization_type`.

**Compatibility verdict**: opencode skills are a clean fit for the existing
`customization_type = "skill"`. The shared `io_helpers.skill_md` module
defined in `docs/agentic_tool_integration_protocol.md` can be reused
unchanged.

### Commands (opencode-specific)

Path: `~/.config/opencode/commands/<name>.md` — flat file, no folder.

```markdown
---
description: Review code changes for issues
agent: plan
model: anthropic/claude-3-5-sonnet-20241022
subtask: true
---

Review the following changes:
!`git diff`

Check for bugs, security issues, and performance problems.
```

Frontmatter fields: `description`, `agent`, `model`, `subtask`. Body
supports placeholders: `$ARGUMENTS`, `$1`, `$2`, …, `` !`shell` `` (shell
stdout injection), `@path` (file injection). Invoked at the TUI as
`/command-name [args]`.

**Compatibility verdict**: commands have **no equivalent** in Claude Code,
Codex, or Antigravity at parity. Claude Code has `~/.claude/commands/*.md`
with a similar shape, but the frontmatter keys (`agent`, `subtask`) and the
placeholder language differ enough that naive copying would silently drop
fields. Recommendation: defer commands to a future
`customization_type = "command"` rather than fold them into `agent` or
`skill` for v0.5. Keep them out of the first opencode integration release.

### Global rules (`AGENTS.md`)

opencode honours the cross-tool `AGENTS.md` convention at both project
(`<root>/AGENTS.md`) and global (`~/.config/opencode/AGENTS.md`) scopes,
with `CLAUDE.md` as a documented fallback. Possible future
`customization_type = "rule"`, out of scope for v0.5.

---

## 6. Cross-tool comparison

### Agents

| Dimension | Claude Code | Codex | Antigravity | opencode |
|---|---|---|---|---|
| File | `.md` | `.toml` | `.md` (rules) | `.md` |
| Path (user) | `~/.claude/agents/` | `~/.codex/agents/` | n/a as of v0.4 | `~/.config/opencode/agents/` |
| Envelope | YAML frontmatter | TOML root | plain prose | YAML frontmatter |
| Identity anchor | filename + injected `pair_id` in frontmatter | TOML `pair_id` key | n/a | filename + injected `customization_artifact_id` (proposed, untested — see §9 Q1) |
| `name` | filename / `name:` | `name = "..."` | section heading | filename only |
| `description` | `description:` | `description = "..."` | prose | `description:` |
| System prompt | body after `---` | `developer_instructions` | body | body after `---` |
| `model` | bare ID (`claude-opus-4-5`) | `model = "..."` | n/a | **`provider/model-id`** (`anthropic/claude-opus-4-5`) |
| Allow-list | `tools: [Read, Grep]` | inferred from sandbox | n/a | encoded in `permission: {…: allow}` |
| Deny-list | `disallowedTools: [Bash]` | per-MCP `disabled_tools` | n/a | encoded in `permission: {…: deny}` |
| Permission mode | `permissionMode:` (4 values) | `sandbox_mode:` (3 values) | IDE-global | `permission:` object, tri-state per tool, glob-aware |
| MCP servers | per-agent in `mcpServers:` frontmatter | global `config.toml` | global `mcp_config.json` | global `opencode.json` `mcp:` only (not per-agent) |
| Hooks | per-agent in `hooks:` frontmatter | global `hooks` table | none formal | plugin (TS/JS) only |

### Skills (and equivalents)

| Dimension | Claude Code | Codex | Antigravity | opencode |
|---|---|---|---|---|
| Path (user) | `~/.claude/skills/<n>/SKILL.md` | `~/.agents/skills/<n>/SKILL.md` | `~/.gemini/antigravity/skills/<n>/SKILL.md` | `~/.config/opencode/skills/<n>/SKILL.md` |
| Layout | folder | folder | folder | folder |
| Spec | extends agentskills.io | extends agentskills.io | follows agentskills.io | follows agentskills.io |
| Cross-reads | — | — | — | reads `~/.claude/skills/` and `~/.agents/skills/` natively |

### Opencode-specific gaps and mismatches

**Canonical fields with no clean opencode equivalent** (must round-trip
through `per_agentic_tool_only[opencode]`):

- `tools` (allow-list) — opencode has no flat allow-list; closest is
  `permission: {tool: allow}`, but the round-trip is lossy unless the
  raw `permission` object is preserved verbatim.
- `disallowedTools` — same situation; closest is
  `permission: {tool: deny}`.
- `permissionMode` — `bypassPermissions`, `acceptEdits`, `plan` have no
  opencode equivalents.
- `mcpServers` — only declared at global scope in opencode.
- `hooks` — only declared in plugin TS/JS modules.

**Opencode fields with no canonical equivalent** (must live in
`per_agentic_tool_only[opencode]`):

- `temperature`, `top_p`, `steps`, `hidden`, `color`, `mode`, `disable`,
  `options`.

**Tool-name casing mismatch**: Claude Code uses PascalCase (`Read`, `Edit`,
`Bash`, `WebFetch`); opencode uses lowercase with underscores (`read`,
`edit`, `bash`, `webfetch`, `external_directory`, `todowrite`,
`doom_loop`). A normalisation table is required if any cross-tool
permission translation is attempted; some names (`doom_loop`, `lsp`,
`question`) have no Claude equivalent.

**Model-string mismatch**: opencode requires the `provider/` prefix; Claude
expects a bare ID; Codex stores the full string. The canonical should
store the bare ID and a separate `provider` hint, or store the full
`provider/model-id` and strip on render.

---

## 7. Mapping into the `agents_sync` canonical

The canonical schema, per `docs/agentic_tool_integration_protocol.md`, is:

```python
{
  "customization_artifact_id": "<UUIDv4>",
  "customization_type": "agent" | "skill",
  "name": str,
  "description": str,
  "model": str | None,
  "tools": list[str] | None,
  "disallowedTools": list[str] | None,
  "permissionMode": str | None,
  "mcpServers": dict | None,
  "hooks": dict | None,
  "body": str,
  "per_agentic_tool_only": { "<tool_name>": { ... } },
  "per_agentic_tool_extra": { "<tool_name>": { ... } },
}
```

### 7.1 Agents — field map

| opencode frontmatter | canonical | direction notes |
|---|---|---|
| filename stem | `name` | parse: from stem; render: stem from `target_slug(canonical["name"])`. Not written to frontmatter. |
| `customization_artifact_id` (injected) | `customization_artifact_id` | injected on adoption; verified preserved on round-trip — **see §9 Q1**. |
| `description` | `description` | direct copy. |
| `model` | `model` (+ `per_agentic_tool_only[opencode].provider`) | parse: split `provider/model-id` into canonical `model` (bare ID) and stash `provider` in opencode bag. Render: re-attach `provider/` from bag; if absent, infer from `model` prefix table. |
| `permission` (raw) | `per_agentic_tool_only[opencode].permission` | always preserved verbatim — this is the lossless channel. |
| `permission` (lossy summary) | `tools`, `disallowedTools`, `permissionMode` | on parse, **also** populate the coarse canonical fields by walking the map: `"*": x` → `permissionMode = x`; `tool: "allow"` → `tools.append(tool)`; `tool: "deny"` → `disallowedTools.append(tool)`. On render, **prefer** the verbatim `per_agentic_tool_only[opencode].permission`; only reconstruct from canonical fields when the verbatim bag is absent (e.g. artifact originated from Claude). |
| `tools` (deprecated bool map) | normalised on parse into `per_agentic_tool_only[opencode].permission` | never re-emitted in the deprecated form. |
| `mode` | `per_agentic_tool_only[opencode].mode` | opencode-only routing concept. |
| `temperature`, `top_p`, `steps`, `hidden`, `color`, `disable`, `options` | `per_agentic_tool_only[opencode][field]` | each preserved verbatim. |
| _(unknown frontmatter key)_ | `per_agentic_tool_extra[opencode][key]` | verbatim passthrough. |
| body | `body` | direct. |
| `mcpServers` (canonical) | _(not rendered to opencode)_ | opencode has no per-agent MCP frontmatter; keep in `per_agentic_tool_only[claude]`. |
| `hooks` (canonical) | _(not rendered to opencode)_ | opencode has no frontmatter hook mechanism. |

### 7.2 Skills — field map

opencode skills are a strict implementation of the open Agent Skills
Specification. Reuse the shared `io_helpers.skill_md` parser/renderer with:

```python
KNOWN_OPENCODE_SKILL_FIELDS = frozenset({
    "customization_artifact_id", "name", "description",
    "license", "compatibility", "metadata",
})
```

`license`, `compatibility`, and `metadata` are agentskills.io-standard
fields not currently first-class in the `agents_sync` canonical. Store them
in `per_agentic_tool_extra[opencode]` on parse and re-emit verbatim on
render. The auxiliary-file propagation is handled by the sync core
without per-module logic.

### 7.3 Identity injection

**Strategy**: inject `customization_artifact_id` as a top-level YAML
frontmatter key, mirroring the existing Claude `.md` strategy in
`src/agents_sync/claude_io.py`. Use ruamel round-trip mode to preserve
key order, quoting style, and comments in user-authored frontmatter.

**Risk** (DOCS-GAP, §9 Q1): opencode's documentation does not state how
unknown top-level frontmatter keys are handled. The `options:` field
docs hint that unrecognised keys may be forwarded as provider parameters.
If unknown keys are stripped or forwarded harmfully, fall back to one of:
(a) nest the id under `options.agents_sync_id`, (b) embed as an HTML
comment in the body, (c) sidecar `<name>.opencode_sync_id`.

### 7.4 Round-trip stability risks

1. **`tools` allow-list round-trip**: if the canonical `tools` field is
   set (e.g. from Claude) and the verbatim `permission` bag is absent,
   the renderer produces `permission: {tool: "allow", …}`. Re-parsing
   that produces `tools = [tool, …]` again — stable, as long as the
   tool-name casing table is bijective. Bug surface: any tool with no
   Claude equivalent (`doom_loop`, `lsp`, `question`, `todowrite`,
   `external_directory`) must round-trip through the opencode bag.
2. **`permission` glob keys**: ruamel preserves `"*"` as a quoted scalar
   in round-trip mode; the renderer must never emit unquoted `*:` keys.
3. **`mode` defaulting**: if a Claude-side agent is rendered to opencode
   without a stashed `mode`, defaulting to `mode: all` is safe but loses
   user intent. Always preserve the bag.
4. **`steps` vs deprecated `maxSteps`**: on parse, normalise `maxSteps`
   to `steps` in the opencode bag; never re-emit `maxSteps`.
5. **`model` provider prefix**: store the provider hint per-tool (`opencode`
   uses `provider/model-id`, Codex stores the full string, Claude
   expects bare). A cross-tool rename of `claude-sonnet-4-5` →
   `anthropic/claude-sonnet-4-5` would otherwise appear as an mtime-tied
   change every poll.
6. **BOM and CRLF**: opencode does not document BOM/CRLF tolerance. The
   parser should reuse `claude_io._strip_bom_prefix` and the existing
   `FRONTMATTER_RE` (`\r?\n` aware). The renderer always emits LF.
7. **Skill name regex**: opencode enforces
   `^[a-z0-9]+(-[a-z0-9]+)*$` for skill folder names. The existing
   `slugify` produces `[a-z0-9_-]`; a stricter `opencode_skill_slugify`
   that replaces `_` with `-` and collapses repeats is required, with a
   pre-write validity check.

---

## 8. Implementation checklist

The change conforms to v0.4's "no edits to sync core" rule. Files touched:

### 8.1 New files

- `src/agents_sync/agentic_tools/opencode.py` — exports a single
  `AGENTIC_TOOL: AgenticToolSpec` per
  `docs/agentic_tool_integration_protocol.md`. Sketch:

  ```python
  from agents_sync.agentic_tool_spec import (
      AgenticToolSpec, CustomizationTypeIO,
      AgentFileLayout, SkillFileLayout,
  )
  from agents_sync.io_helpers.skill_md import (
      extract_customization_artifact_id_from_skill_md,
      parse_open_spec_skill_md,
      render_open_spec_skill_md,
  )

  KNOWN_OPENCODE_AGENT_FIELDS = frozenset({
      "customization_artifact_id",
      "description", "mode", "model", "temperature", "top_p",
      "steps", "permission", "tools", "color", "hidden",
      "disable", "options",
  })
  KNOWN_OPENCODE_SKILL_FIELDS = frozenset({
      "customization_artifact_id", "name", "description",
      "license", "compatibility", "metadata",
  })

  def extract_customization_artifact_id_from_opencode_agent(text): ...
  def parse_opencode_agent_md(text, prior_canonical=None): ...
  def render_opencode_agent_md(canonical, prior_text=None): ...

  AGENTIC_TOOL = AgenticToolSpec(
      name="opencode",
      supported_customization_types=frozenset({"agent", "skill"}),
      io_per_customization_type={
          "agent": CustomizationTypeIO(
              extract_customization_artifact_id=extract_customization_artifact_id_from_opencode_agent,
              parse=parse_opencode_agent_md,
              render=render_opencode_agent_md,
          ),
          "skill": CustomizationTypeIO(
              extract_customization_artifact_id=extract_customization_artifact_id_from_skill_md,
              parse=lambda text, prior: parse_open_spec_skill_md(
                  text, prior,
                  agentic_tool_name="opencode",
                  known_fields=KNOWN_OPENCODE_SKILL_FIELDS,
              ),
              render=lambda canonical, prior_text: render_open_spec_skill_md(
                  canonical, prior_text,
                  agentic_tool_name="opencode",
                  known_fields=KNOWN_OPENCODE_SKILL_FIELDS,
              ),
          ),
      },
      config_roots={"agent": "agents_dir", "skill": "skills_dir"},
      file_layout={
          "agent": AgentFileLayout(extension=".md"),
          "skill": SkillFileLayout(skill_md_name="SKILL.md"),
      },
  )
  ```

- `tests/agentic_tools/test_opencode.py` — see §8.3.
- `tests/fixtures/opencode/` — two or three real `SKILL.md` files vendored
  from public community repos (joelhooks/opencode-config,
  gotar/opencode-config, farmage/opencode-skills) plus one full-fat agent
  `.md` exercising every known frontmatter field.

### 8.2 Existing files to update

- `src/agents_sync/config.py` — add per-OS defaults (see §3 paths);
  add `opencode_agents_dir` and `opencode_skills_dir` to
  `validate_config`.
- `src/agents_sync/cli.py` — add `--opencode-agents-dir` and
  `--opencode-skills-dir` flags mirroring the existing codex flags.
- `install.sh`, `install-macos.sh`, `install.ps1` — add a commented-out
  `[agentic_tools.opencode]` block to the generated sample config; on
  Windows use `%APPDATA%\opencode\` with the Q2 caveat noted in a
  comment.
- `README.md` — extend the "What It Syncs" table, the "Default Paths"
  table, the Mermaid diagram, the Notes section. Add a short "Enabling
  opencode" subsection covering the `[agentic_tools.opencode]` config
  block and the US-11 `enabled = true` flag.

No changes to `sync.py`, `state.py`, `canonical.py`, `archive.py`,
`daemon.py`, or `identity.py`. The agentic-tool integration protocol
forbids them — per US-10 AC-2, any need for such a change is a
protocol-design failure.

### 8.3 Test matrix

Unit tests (`tests/agentic_tools/test_opencode.py`):

- agent round-trip fixed-point on canonical with every known field.
- agent render byte-determinism.
- `customization_artifact_id` injection when missing.
- `customization_artifact_id` preserved on round-trip.
- unknown frontmatter keys routed to `per_agentic_tool_extra[opencode]`.
- UTF-8 BOM tolerance on parse.
- CRLF tolerance on parse.
- non-mapping YAML frontmatter raises a clean exception (per US-03 AC-10).
- `hooks`, `mcpServers`, `permissionMode`, `sandbox_mode` do **not** appear
  in rendered opencode output.
- `mode: subagent` survives parse → canonical → render.
- skill round-trip fixed-point; BOM tolerance;
  `license`/`compatibility`/`metadata` preserved.
- deprecated `tools` bool map normalises to `permission` and is not
  re-emitted.
- `model` provider prefix is stripped on parse, re-attached on render.
- opencode skill slugify rejects/normalises an underscore-containing name.

End-to-end (`tests/test_e2e_sync_opencode.py` or fixtures in existing
files), covering US-01, US-03, US-06, US-11 with opencode in the mix:

- US-01: opencode agent edited → propagates to claude/codex/antigravity in
  ≤ 2 polls and vice versa.
- US-01: opencode-only fields (`mode`, `color`, `steps`) do not leak into
  Claude or Codex outputs.
- US-03: a new opencode agent without `customization_artifact_id` is
  adopted; counterpart files created on all other available tools.
- US-03: opencode skill collides with an existing Claude skill by
  `(customization_type, target_slug(name))` → reconciliation by mtime;
  loser archived.
- US-03: malformed opencode agent frontmatter (non-mapping YAML) is
  skipped with a structured warning per AC-10.
- US-06: simultaneous edits to the same artifact on opencode and Claude →
  argmax(mtime) wins; loser archived under
  `archive/<id>/{opencode,claude}/`.
- US-11: opencode `agents_dir` missing at startup → status `unavailable`,
  INFO log, daemon continues, other tools unaffected.
- US-11: opencode root reappears mid-life → status transitions to
  `available`, managed artifacts re-extend to opencode.

### 8.4 Effort estimate

| Sub-task | Person-days |
|---|---:|
| Pre-work: empirically test Q1 (unknown-frontmatter-key passthrough), confirm Q2 Windows path | 0.5 |
| `src/agents_sync/agentic_tools/opencode.py` | 1.0 |
| Unit tests | 0.75 |
| Fixtures | 0.25 |
| `config.py` + `cli.py` | 0.5 |
| Installer scripts | 0.25 |
| README and diagram | 0.5 |
| End-to-end / matrix tests | 1.0 |
| Manual e2e against real opencode install on Linux + Windows | 0.5 |
| **Total** | **5.25** |

If Q1 forces a fallback identity-anchor (HTML comment or sidecar file),
add ~1.5 person-days for the alternative mechanism and tests.

### 8.5 Risks and known unknowns

- **Format stability**: opencode's changelog shows no breaking changes to
  agent or skill file formats from late 2025 through May 2026. The
  closest was a TUI keybind config reshape (irrelevant to `agents_sync`).
  Format-stability risk: **LOW** for the next 6 months.
- **Identity anchor**: §9 Q1 — the most material unknown. Resolution must
  precede implementation.
- **Windows path**: §9 Q2 — must be resolved before installer ships
  defaults.
- **Rapid release cadence**: multiple opencode releases per week. The
  `per_agentic_tool_extra[opencode]` passthrough bag absorbs new
  frontmatter keys without action; new structural changes (e.g. a move
  away from YAML frontmatter) would require a re-implementation.
- **Licence**: opencode is MIT; `agents_sync` is MIT. No conflict.

---

## 9. Open questions and known unknowns

### Q1 — DOCS-GAP. Does opencode preserve unknown top-level frontmatter keys on read?

`agents_sync`'s identity model depends on injecting a
`customization_artifact_id` field into an opencode agent's YAML
frontmatter and relying on opencode to ignore (not strip, not forward)
that field. Opencode's docs do not state how unknown keys are handled,
and the `options:` field documentation implies that some unknown keys
may be forwarded as provider model options.

**Resolution path**: install opencode locally, author an agent file with a
`customization_artifact_id: 00000000-…` frontmatter key, restart
opencode, exercise the agent, then inspect the file on disk. If
opencode rewrites the file and removes the key, fall back to:

- (a) nest the id under `options.agents_sync_id` (slightly less elegant
  but uses a documented passthrough channel);
- (b) embed in a trailing HTML comment in the body (
  `<!-- customization_artifact_id: <uuid> -->`) — used in other tools;
- (c) sidecar file `<name>.opencode_sync_id` (most robust, breaks the
  "one file, one identity" invariant).

### Q2 — DOCS-GAP. Canonical Windows path for `~/.config/opencode/agents/`?

Official docs say `%USERPROFILE%\.config\opencode\`. Closed issue
[#8235](https://github.com/anomalyco/opencode/issues/8235) proposed a fix
to `env-paths` semantics. Plugin-ecosystem reports observe
`%APPDATA%\opencode\` at runtime.

**Resolution path**: run `opencode debug paths` on a Windows machine
running the current opencode release. Pin the result in installer
defaults. Surface a manual override config key for users on older or
patched versions.

### Q3 — macOS path

Community configs (joelhooks, gotar) all use `~/.config/opencode/` on
macOS. Docs imply XDG behaviour across Linux and macOS. No conflicting
data found. Risk: **LOW**.

### Q4 — Are frontmatter keys passed to the model as part of the system prompt?

If opencode strips frontmatter before rendering the system prompt,
`customization_artifact_id` injection is invisible to the LLM. If it
does not, the id appears in context. Either is acceptable for sync
correctness but the latter is noisy. To check: inspect opencode source
at the agent loader, or test empirically.

### Q5 — Skill compatibility field semantics

Opencode reads a `compatibility:` field on `SKILL.md` but its allowed
values are not enumerated in the public docs. Community usage suggests
strings like `"opencode"`. Store and re-emit verbatim via
`per_agentic_tool_extra[opencode]`.

### Q6 — Commands as a future customization_type

opencode commands are user-invoked slash commands with the same wire
format as agents but distinct semantics. Claude Code has an analogous
`~/.claude/commands/*.md` directory. A future
`customization_type = "command"` would let `agents_sync` cover this
surface across both tools. Out of scope for v0.5.

---

## 10. Recommendation

**Proceed with adding opencode as the fourth `agentic_tool` for the
`agent` and `skill` customization_types in v0.5**, conditional on
resolving Q1 and Q2 via short empirical tests (≤ 0.5 person-day).

**Rationale**:

- The integration follows the existing v0.4 protocol exactly — one new
  module, config defaults, README updates, no sync-core changes.
- opencode's YAML frontmatter agent format is structurally identical to
  Claude Code's; the ruamel-based round-trip preservation already in
  `claude_io.py` is directly applicable.
- opencode's skill format is full open Agent Skills Specification, so
  the shared `io_helpers.skill_md` module is reusable verbatim.
- opencode is MIT-licensed, actively maintained, and currently the
  fastest-growing alternative CLI agent — high return per implementation
  day.
- The cross-read of `~/.claude/skills/` and `~/.agents/skills/` that
  opencode performs natively means that for users who already sync the
  Claude/Codex/Antigravity triangle, the marginal value of "opencode as
  a writer" is real but bounded — the bigger gain is making
  opencode-authored agents and skills appear on the other three tools.

**Defer**:

- **Commands** to a future `customization_type = "command"` (it has a
  Claude Code peer worth pairing with).
- **MCP servers**, **plugins**, **permission profiles**, **provider
  options** to future `customization_type` extensions, each with their
  own field-stripping strategy.
- **Themes**, **keybinds**, **session state**, **credentials** — never
  sync.

---

## 11. Sources

### opencode official documentation

- <https://opencode.ai/>
- <https://opencode.ai/docs/>
- <https://opencode.ai/docs/config/>
- <https://opencode.ai/docs/agents/>
- <https://opencode.ai/docs/skills/>
- <https://opencode.ai/docs/commands/>
- <https://opencode.ai/docs/rules/>
- <https://opencode.ai/docs/cli/>
- <https://opencode.ai/docs/permissions/>
- <https://opencode.ai/docs/providers/>
- <https://opencode.ai/docs/models/>
- <https://opencode.ai/docs/mcp-servers/>
- <https://opencode.ai/docs/plugins/>
- <https://opencode.ai/docs/custom-tools/>
- <https://opencode.ai/docs/tui/>
- <https://opencode.ai/docs/themes/>
- <https://opencode.ai/docs/keybinds/>
- <https://opencode.ai/docs/troubleshooting/>
- <https://opencode.ai/docs/windows-wsl/>
- <https://opencode.ai/docs/ide/>
- <https://opencode.ai/docs/sdk/>
- <https://opencode.ai/changelog>

### opencode GitHub

- <https://github.com/anomalyco/opencode> (canonical)
- <https://github.com/sst/opencode> (redirect)
- <https://github.com/anomalyco/opencode/releases>
- <https://github.com/anomalyco/opencode/blob/dev/LICENSE>
- <https://github.com/anomalyco/opencode/issues/3461> (agent frontmatter discovery bug)
- <https://github.com/anomalyco/opencode/issues/3631> (`maxSteps` → `steps` migration)
- <https://github.com/anomalyco/opencode/issues/5176> (XDG install path)
- <https://github.com/anomalyco/opencode/issues/6669> (XDG_CONFIG_HOME doc gap)
- <https://github.com/anomalyco/opencode/issues/8235> (Windows path bug)
- <https://github.com/anomalyco/opencode/issues/8390> (Docker image rename)
- <https://github.com/anomalyco/opencode/issues/10411> (non-interactive mode feature request)
- <https://github.com/anomalyco/opencode/issues/13851> (non-interactive pipeline hang)
- <https://github.com/anomalyco/opencode/issues/14410> (`agent create` writes `.opencode/agent/` singular)
- <https://github.com/anomalyco/opencode/issues/18633> (state vs data XDG mis-placement)
- <https://github.com/anomalyco/opencode/issues/18953> (`.opencode/opencode.json{,c}` undocumented source)
- <https://github.com/sst/opencode/issues/806> (MCP resources/prompts feature request)
- <https://github.com/sst/opencode/issues/2643> (Bun runtime in binary)
- <https://github.com/sst/opencode/issues/12432> (`OPENCODE_DISABLE_CLAUDE_CODE=1` over-broad)
- <https://github.com/anomalyco/opencode/issues/22110> (session storage growth)
- <https://github.com/NoeFabris/opencode-antigravity-auth/issues/251> (Windows `%APPDATA%` runtime path)
- <https://github.com/NoeFabris/opencode-antigravity-auth/issues/265> (Windows path doc mismatch)

### Community / third-party

- <https://deepwiki.com/sst/opencode/1.3-installation-and-setup>
- <https://deepwiki.com/sst/opencode/3-configuration-system>
- <https://deepwiki.com/sst/opencode/3.1-configuration-structure>
- <https://deepwiki.com/sst/opencode/3.2-agent-system>
- <https://deepwiki.com/sst/opencode/3.3-provider-configuration>
- <https://deepwiki.com/sst/opencode/5-tools-and-permissions>
- <https://deepwiki.com/sst/opencode/5.2-permission-system>
- <https://deepwiki.com/sst/opencode/5.7-skills-system>
- <https://www.npmjs.com/package/@opencode-ai/plugin>
- <https://hungyi.net/Tech/OpenCode-Configuration-Path-Discovery>
- <https://github.com/joelhooks/opencode-config>
- <https://github.com/gotar/opencode-config>
- <https://github.com/farmage/opencode-skills>
- <https://github.com/KristjanPikhof/OpenCode-Hooks>
- <https://composio.dev/content/mcp-with-opencode>
- <https://lushbinary.com/blog/opencode-plugin-development-custom-tools-hooks-guide/>
- <https://changelogs.directory/tools/opencode/releases/v1.1.1>
- <https://community.chocolatey.org/packages/opencode/1.4.1>

### Peer tool documentation (for comparison)

- <https://code.claude.com/docs/en/sub-agents>
- <https://code.claude.com/docs/en/skills>
- <https://code.claude.com/docs/en/hooks>
- <https://code.claude.com/docs/en/memory>
- <https://developers.openai.com/codex/guides/agents-md>
- <https://developers.openai.com/codex/config-reference>
- <https://developers.openai.com/codex/skills>
- <https://antigravity.google/docs/agent>
- <https://antigravity.google/docs/agent-manager>
- <https://agentskills.io/specification>
- <https://agents.md/>
