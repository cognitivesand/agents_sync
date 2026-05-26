# Antigravity 2.0 — research and `agents_sync` impact

Google announced **Antigravity 2.0** on **2026-05-19** during the Google I/O 2026 opening keynote. The release reshapes the Gemini / Antigravity / Gemini CLI surface area: Gemini CLI is being absorbed into a new **Antigravity CLI** (`agy`), with the legacy Gemini CLI scheduled to stop serving consumer-tier (free / AI Pro / AI Ultra) requests on **2026-06-18**. Gemini Code Assist Standard / Enterprise customers retain the existing Gemini CLI.

This document collects deep research across six axes — release overview, filesystem layout, skills surface, MCP & extensions, new customization surfaces, and migration — and ends with a consolidated impact on the `agents_sync` adapter set.

The research is being filled in as the six parallel research agents complete. Sections marked **(pending)** below will be replaced with the agent's findings as they return. Last updated: 2026-05-20.

## Status of this research

| § | Topic | Status |
|---|---|---|
| 1 | Release overview & feature inventory | complete |
| 2 | Filesystem layout & config paths | complete |
| 3 | Skills surface (SKILL.md schema, kinds) | complete |
| 4 | MCP & extensions | complete |
| 5 | New customization surfaces (subagents, hooks, slash, rules, memory, modes) | complete |
| 6 | Migration & compatibility with 1.x | complete |
| 7 | Consolidated impact on `agents_sync` | complete |

---

## §1 — Release overview & feature inventory

### 1.1 Official announcement

Google announced **Antigravity 2.0** on **2026-05-19** during the opening keynote of **Google I/O 2026**, delivered by Sundar Pichai ([blog.google/innovation-and-ai/sundar-pichai-io-2026](https://blog.google/innovation-and-ai/sundar-pichai-io-2026/), 2026-05-19). The product-side developer post is on Google's own developer blog, "I/O 2026 developer highlights: Antigravity, Gemini API, AI Studio" ([blog.google/innovation-and-ai/technology/developers-tools/google-io-2026-developer-highlights/](https://blog.google/innovation-and-ai/technology/developers-tools/google-io-2026-developer-highlights/), 2026-05-19), with a companion post, "An important update: Transitioning Gemini CLI to Antigravity CLI" ([developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/), 2026-05-19).

Headline claims (from secondary coverage of the keynote; direct verbatim text from Google's blog was not retrievable via WebFetch in the session):

```
"expanding beyond the coding environment, turning it into a platform
 to develop and manage cohorts of autonomous AI agents"
   — Sundar Pichai, I/O 2026 keynote (per cybernews.com, 2026-05-19)
```

```
"the start of the agentic Gemini era"
   — Sundar Pichai, I/O 2026 keynote (per upstox.com, 2026-05-19)
```

### 1.2 Naming and branding

**Antigravity** is repositioned as an umbrella **agent-first development platform** rather than an IDE. Sub-brands announced on 2026-05-19:

- **Antigravity 2.0** — standalone desktop app (replaces / sits alongside the v1.x IDE).
- **Antigravity CLI** — terminal surface; **Gemini CLI is being folded into it** (TechCrunch 2026-05-19, Google Developers Blog 2026-05-19, virtualizationreview.com 2026-05-19).
- **Antigravity SDK** — programmatic access to the same agent harness.
- **Managed Agents** — a new Gemini API surface that spins up isolated Linux sandboxes per call (MarkTechPost 2026-05-19).
- **Gemini Enterprise Agent Platform** — enterprise deployment surface (SiliconANGLE 2026-05-19).

Gemini CLI is **deprecated for free / AI Pro / AI Ultra tiers, with a stop-serve date of 2026-06-18**; Gemini Code Assist Standard/Enterprise customers retain access. **Gemini CLI extensions** become **Antigravity plugins** under the new branding.

### 1.3 GA status

**Public preview**, free with a personal Gmail account, no credit card or waitlist; paid tiers also live (aibuilderclub.com guide, May 2026). General availability for the **enterprise** track was **not** announced — there is no published governance / certification path yet (winbuzzer.com 2026-05-19). The desktop app, CLI, and SDK are all **shipping as of 2026-05-19**; Managed Agents is in preview in the Gemini API.

### 1.4 Pricing tier changes vs 1.x

Per TechCrunch (2026-05-19), aidirectory.com, and vibecoding.app (May 2026):

- **Free**: rate-limited public preview (shape unchanged from 1.x).
- **AI Pro**: **$20/month** (carried over from 1.x).
- **AI Ultra (new mid-tier)**: **$100/month**, **5×** the Pro limits — newly introduced.
- **AI Ultra top tier**: **$200/month**, **20×** Pro limits, **reduced from $250** (theregister.com 2026-03-12 noted prior user pushback; the cut accompanied the 2.0 launch).
- **Enterprise**: priced via Gemini Enterprise Agent Platform / Google Cloud — no public list price (SiliconANGLE 2026-05-19).

### 1.5 Target audience

Broadened vs 1.x. 1.x was framed as an agentic IDE for individual developers; 2.0 explicitly spans:

- individual developers / startups (Free, Pro, new $100 Ultra mid-tier);
- professional engineering teams ("AI as team member" framing, byteiota May 2026);
- large enterprises with existing Google Cloud footprints (Gemini Enterprise Agent Platform, SiliconANGLE 2026-05-19);
- terminal-first developers via Antigravity CLI (TechCrunch 2026-05-19);
- platform builders embedding agents in their own products via the SDK (MarkTechPost 2026-05-19).

### 1.6 Underlying model

The **default model** in Antigravity 2.0 is **Gemini 3.5 Flash**, announced the same day ([blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-5/](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-5/), 2026-05-19). Per Google's own materials cited via DataCamp and TechCrunch (2026-05-19): Gemini 3.5 Flash **outperforms Gemini 3.1 Pro** on Terminal-Bench 2.1 (76.2 %), GDPval-AA (1656 Elo), and MCP Atlas (83.6 %), and Google states it is **~4× faster than other frontier coding models**. **MCP Atlas** as the tool-use benchmark implies first-class MCP tool-call integration.

### 1.7 Headline feature list

Per Google's developer blog post (2026-05-19), MarkTechPost (2026-05-19), TechCrunch (2026-05-19), 9to5Google (2026-05-19), and SiliconANGLE (2026-05-19):

1. **Standalone agent-first desktop app** (no longer IDE-only).
2. **Multi-agent orchestration** — run multiple agents in parallel against the same workspace.
3. **Dynamic subagents** for parallelized workflows.
4. **Scheduled tasks** — background automation that runs without an open session.
5. **Antigravity CLI** — terminal surface, shares the agent harness with the desktop app (replaces Gemini CLI).
6. **Antigravity SDK** — programmatic access to the same harness.
7. **Managed Agents in Gemini API** — isolated Linux sandbox per call with persistent multi-turn state.
8. **Native voice command support** (parity with Gmail/Docs voice features).
9. **Ecosystem integrations** with AI Studio, Android, Firebase.
10. **Gemini Enterprise Agent Platform** path for deploying Antigravity agents on Google Cloud.

### 1.8 Distribution channels

- **Standalone desktop installer** for Linux, macOS, Windows via [antigravity.google](https://antigravity.google/) (aibuilderclub.com guide, 2026).
- **Antigravity CLI** — distributed via the Google package channels that previously served Gemini CLI; binary name appears to be `agy`, **written in Go** (warpdotdev/warp issue #11368, 2026; agentpedia.codes 2026-05).
- **VS Code Marketplace extensions** can be installed **inside** Antigravity but only via the Antigravity CLI / `.vsix` sideload — Antigravity does not appear as a VS Code extension itself (Medium guide by Anil Gurindapalli, 2026; Jimmy Song blog, 2026). Community helper extensions exist ("Antigravity Storage Manager", "Toolkit for Antigravity") but are third-party.
- **No public information yet** on Jetbrains / Cursor integrations beyond third-party adapters.

### 1.9 Sources (§1)

- [Google I/O 2026 keynote — Sundar Pichai (blog.google, 2026-05-19)](https://blog.google/innovation-and-ai/sundar-pichai-io-2026/)
- [I/O 2026 developer highlights: Antigravity, Gemini API, AI Studio (blog.google, 2026-05-19)](https://blog.google/innovation-and-ai/technology/developers-tools/google-io-2026-developer-highlights/)
- [An important update: Transitioning Gemini CLI to Antigravity CLI (Google Developers Blog, 2026-05-19)](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
- [Gemini 3.5: frontier intelligence with action (blog.google, 2026-05-19)](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-5/)
- [Google launches Antigravity 2.0 (TechCrunch, 2026-05-19)](https://techcrunch.com/2026/05/19/google-launches-antigravity-2-0-with-an-updated-desktop-app-and-cli-tool-at-io-2026/)
- [Google Launches Antigravity 2.0 at I/O 2026 (MarkTechPost, 2026-05-19)](https://www.marktechpost.com/2026/05/19/google-launches-antigravity-2-0-at-i-o-2026-a-standalone-agent-first-platform-with-cli-sdk-managed-execution-and-enterprise-support/)
- [With expanded Antigravity platform, Google accelerates agent-native software development (SiliconANGLE, 2026-05-19)](https://siliconangle.com/2026/05/19/google-accelerates-agent-native-software-development-expanded-antigravity-platform/)
- [Google Expands Antigravity 2.0 Into Multi-Agent Dev Suite (winbuzzer.com, 2026-05-19)](https://winbuzzer.com/2026/05/19/introducing-google-antigravity-20-xcxwbn/)
- [Google flips Antigravity into an agentic dev suite (9to5Google, 2026-05-19)](https://9to5google.com/2026/05/19/google-antigravity-agentic-developer-suite/)
- [Google Moves Gemini CLI Into Antigravity CLI (Virtualization Review, 2026-05-19)](https://virtualizationreview.com/articles/2026/05/19/google-moves-gemini-cli-into-antigravity-cli-as-agent-platform-expands.aspx)
- [Gemini CLI → Antigravity CLI Migration Guide (agentpedia.codes, 2026)](https://agentpedia.codes/blog/gemini-cli-to-antigravity-cli-migration)
- [Antigravity CLI Deep Dive (agentpedia.codes, 2026-05)](https://agentpedia.codes/blog/antigravity-cli-deep-dive)
- [Google AntiGravity Pricing 2026 (vibecoding.app)](https://vibecoding.app/blog/google-antigravity-pricing-2026)
- [Users protest as Google Antigravity price floats upward (The Register, 2026-03-12)](https://www.theregister.com/2026/03/12/users_protest_as_google_antigravity/)
- [Google pushes "agentic AI" at I/O 2026 (cybernews.com, 2026-05-19)](https://cybernews.com/ai-news/google-io-2026-gemini-omni-antigravity-agentic-ai/)
- [Gemini 3.5 Flash: Google's Fastest Agentic Model (DataCamp, 2026)](https://www.datacamp.com/blog/gemini-3-5-flash)
- [Antigravity Global Rules and Gemini CLI Global Context Both Write to `~/.gemini/GEMINI.md` (gemini-cli Issue #16058)](https://github.com/google-gemini/gemini-cli/issues/16058)
- [Support for Google's new Antigravity CLI (agy) — warpdotdev/warp #11368](https://github.com/warpdotdev/warp/issues/11368)
- [Google Antigravity: The Complete Guide (aibuilderclub.com, 2026)](https://www.aibuilderclub.com/blog/google-antigravity-complete-guide)
- [How to Install VS Code Marketplace Extensions in Antigravity (Medium, Anil Gurindapalli, 2026)](https://medium.com/@agurindapalli/how-to-install-vs-code-marketplace-extensions-in-googles-antigravity-ide-example-deepblue-theme-689cdcd735eb)

### 1.10 Implications for `agents_sync` (§1 only — consolidated set in §7)

1. **Gemini CLI is being absorbed into Antigravity CLI by 2026-06-18.** The planned v0.5 `gemini_cli.py` adapter still has a real audience (Gemini Code Assist Standard/Enterprise), but the **default substrate for free / AI Pro / AI Ultra users is moving to Antigravity CLI**. A new dedicated `antigravity_cli.py` adapter is likely warranted, distinct from both the existing `antigravity.py` (IDE / desktop) and the planned `gemini_cli.py`. Per agentpedia.codes and gemini-cli #16058, **the two share `~/.gemini/GEMINI.md`** today — a sync collision risk to model explicitly.

2. **Customization-type surface area has grown beyond skills.** Antigravity CLI exposes **Agent Skills, Hooks, Subagents, and Plugins** (formerly Gemini CLI Extensions). The current `antigravity.py` (v0.4.1) supports only `skill`. Hooks and subagents are natural new customization types to scope for v0.5+.

3. **Rebrand without config-root rename so far.** The `~/.gemini/antigravity/skills/` path appears unchanged in 2.0 coverage; no evidence of a move to `~/.antigravity/`. Existing `antigravity.py` path constants remain valid; treat as confirmed until Google publishes 2.0 docs explicitly.

Model change (Gemini 3.5 Flash default) is **not relevant** to sync semantics.

---

## §2 — Filesystem layout & config paths

Antigravity 2.0 ships alongside the new **Antigravity CLI** (binary name `agy`, written in Go), the Antigravity SDK, and the Managed Agents service in the Gemini API. Crucially for `agents_sync`, Gemini CLI is being absorbed into Antigravity CLI, with consumer-tier Gemini CLI requests scheduled to start failing on 2026-06-18.

### 2.1 Top-line finding

**The user-level config root has NOT moved to `~/.antigravity/` or `~/.config/antigravity/`.** Antigravity 2.0 keeps its user data under the existing `~/.gemini/` tree, simply adding new sibling subdirectories. The Antigravity desktop application's binary cache and OS-conventional dirs (e.g. `~/Library/Application Support/Antigravity` on macOS, `%APPDATA%\Antigravity` on Windows) continue to follow Electron/Chromium conventions and are separate from the user-authored config tree under `~/.gemini/`.

### 2.2 Linux / macOS user-level paths

| Concern | Antigravity 1.x | Antigravity 2.0 |
|---|---|---|
| Config root | `~/.gemini/` | `~/.gemini/` (unchanged) |
| Standalone app data | `~/.gemini/antigravity/` | `~/.gemini/antigravity/` (now means **2.0 standalone app**) |
| IDE app data | (same as above) | `~/.gemini/antigravity-ide/` (new, holds the 1.x IDE app data) |
| Backup snapshot | n/a | `~/.gemini/antigravity-backup/` (created automatically during the 1.x → 2.0 update) |
| Antigravity CLI (`agy`) | n/a | `~/.gemini/antigravity-cli/` (separate config tree per `agentpedia.codes`) |
| Global skills | `~/.gemini/antigravity/skills/<name>/SKILL.md` | `~/.gemini/antigravity/skills/<name>/SKILL.md` (unchanged) |
| Memory file | `~/.gemini/GEMINI.md` | `~/.gemini/GEMINI.md` (still shared, conflict not yet resolved — see Issue #16058) |
| MCP server config | `~/.gemini/antigravity/mcp_config.json` (often a symlink) | same — must be excluded from any rsync/copy |

The 2.0 update splits live data between the 2.0 standalone app (`antigravity/`) and the legacy IDE (`antigravity-ide/`). Multiple reports note that the migration commonly strands user data (brain entries, conversations, scratch space) in `antigravity-backup/` and requires manual `rsync` to restore.

### 2.3 Windows paths

| Concern | Path |
|---|---|
| User config root | `%USERPROFILE%\.gemini\` (same as 1.x) |
| Standalone 2.0 app | `%USERPROFILE%\.gemini\antigravity\` |
| Legacy IDE | `%USERPROFILE%\.gemini\antigravity-ide\` |
| Backup snapshot | `%USERPROFILE%\.gemini\antigravity-backup\` |
| Desktop app binary cache | `%APPDATA%\Antigravity\` |

### 2.4 macOS-specific desktop app cache (NOT user-authored config)

- `~/Library/Application Support/Antigravity/User/{settings.json, keybindings.json, snippets}`
- `~/Library/Application Support/Antigravity/auth-tokens`
- `~/Library/Application Support/Antigravity/Cache`, `.../GPUCache`
- `~/Library/Caches/com.google.antigravity`
- `~/Library/Preferences/com.google.antigravity.plist`

These are Electron-managed and **not** part of the user-authored customization surface `agents_sync` cares about.

### 2.5 Workspace-level config

| Concern | Antigravity 1.x | Antigravity 2.0 |
|---|---|---|
| Workspace dir | `<project>/.agent/` (singular) | `<project>/.agents/` (plural) is now the canonical, natively recognised dir; `<project>/.antigravity/agents/` is also documented for project-specific subagent YAMLs |
| Workspace skills | `<project>/.agent/skills/` | `<project>/.agents/skills/` |
| Workspace rules | `<project>/.agent/rules/` | `<project>/.agents/rules/` |
| Workspace workflows | n/a / inconsistent | `<project>/.agents/workflows/` |
| Cross-tool rules file | n/a | `AGENTS.md` at project root (Antigravity ≥ v1.20.3, retained in 2.0); `GEMINI.md` overrides `AGENTS.md` when both are present |

Google's migration docs (`antigravity.google/docs/gcli-migration`) confirm that "workspace skill folders and inline MCP config in `settings.json` still need manual moves because their canonical locations changed" — implying the `.agent/` → `.agents/` rename is real and **not auto-migrated**.

### 2.6 Environment variables

- **No `ANTIGRAVITY_HOME` variable is documented** in any reachable source as of 2026-05-20.
- The Linux AUR/Arch wrapper uses `XDG_CONFIG_HOME` only to locate an optional flags file (`~/.config/antigravity-flags.conf`); the application itself still anchors data under `~/.gemini/` regardless of `XDG_CONFIG_HOME`.
- On Windows, Playwright-integration bugs were tracked specifically because `HOME` is not set by default — confirming the app relies on `%USERPROFILE%` / `HOME` rather than a dedicated override.

### 2.7 Migration semantics

- The 1.x → 2.0 update creates `~/.gemini/antigravity-backup/` automatically as a snapshot and re-initialises `~/.gemini/antigravity/` for the 2.0 standalone app, then attempts to copy legacy IDE data into `~/.gemini/antigravity-ide/`. A documented bug ("IDE Wizard Migration Failure on Update", Google AI Dev Forum 2026-05) causes the wizard to crash with `EEXIST` when the `mcp_config.json` symlink already exists in the destination.
- There is **no read-only fallback** from 2.0 to 1.x paths; if a user reverts apps, the backup directory is their only recourse.
- For CLI users, `agy plugin import gemini` ports extensions, slash-commands, and most MCP entries from `~/.gemini/` into `~/.gemini/antigravity-cli/`, but **workspace skills and inline MCP config in `settings.json` are NOT migrated** and must be moved manually.

### 2.8 Relationship with Gemini CLI

`~/.gemini/` remains shared between the (sunsetting) Gemini CLI and the entire Antigravity family. The known conflict on `~/.gemini/GEMINI.md` (Issue #16058) persists into 2.0 — both Antigravity Global Rules and Gemini CLI Global Context write to the same file. From 2026-06-18, Gemini CLI consumer-tier requests stop working, but the `~/.gemini/` root will remain populated by Antigravity tools.

### 2.9 New state/cache dirs to exclude from sync

- `~/.gemini/antigravity-backup/` — migration snapshot, transient.
- `~/.gemini/antigravity/brain/` and `~/.gemini/antigravity/conversations/` — runtime conversation state, not user-authored.
- `~/.gemini/antigravity/mcp_config.json` — often a symlink; copying it can break active MCP connections.
- All `~/Library/Application Support/Antigravity/**` (macOS) and `%APPDATA%\Antigravity\**` (Windows) — Electron caches, GPU cache, auth tokens.

### 2.10 Sources (§2)

- [Google launches Antigravity 2.0 (TechCrunch, 2026-05-19)](https://techcrunch.com/2026/05/19/google-launches-antigravity-2-0-with-an-updated-desktop-app-and-cli-tool-at-io-2026/)
- [Google Launches Antigravity 2.0 at I/O 2026 (MarkTechPost, 2026-05-19)](https://www.marktechpost.com/2026/05/19/google-launches-antigravity-2-0-at-i-o-2026-a-standalone-agent-first-platform-with-cli-sdk-managed-execution-and-enterprise-support/)
- [Google Antigravity 2.0 becoming full agentic development suite (9to5Google, 2026-05-19)](https://9to5google.com/2026/05/19/google-antigravity-agentic-developer-suite/)
- [I/O 2026 developer highlights (Google blog, 2026-05-19)](https://blog.google/innovation-and-ai/technology/developers-tools/google-io-2026-developer-highlights/)
- [Transitioning Gemini CLI to Antigravity CLI (Google Developers Blog, 2026-05-19)](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
- [Antigravity is Dead. Long Live Antigravity. (dev.to / turingsoracle, 2026-05)](https://dev.to/turingsoracle/antigravity-is-dead-long-live-antigravity-186m)
- [Gemini CLI → Antigravity CLI Migration Guide (agentpedia.codes, 2026-05)](https://agentpedia.codes/blog/gemini-cli-to-antigravity-cli-migration)
- [Antigravity CLI Deep Dive: Google's Go-Based Terminal Agent (agentpedia.codes, 2026-05)](https://agentpedia.codes/blog/antigravity-cli-deep-dive)
- [Fixing the Antigravity 2.0 Installer Directory Conflict (Google AI Dev Forum, 2026-05)](https://discuss.ai.google.dev/t/fixing-the-antigravity-2-0-installer-directory-conflict/145591)
- [Antigravity Bug Report: IDE Wizard Migration Failure on Update (Google AI Dev Forum, 2026-05)](https://discuss.ai.google.dev/t/antigravity-bug-report-ide-wizard-migration-failure-on-update/145851)
- [`~/.gemini/GEMINI.md` collision (gemini-cli Issue #16058)](https://github.com/google-gemini/gemini-cli/issues/16058)
- [Standardize skill locations across AntiGravity and Gemini CLI (gemini-cli Issue #17495)](https://github.com/google-gemini/gemini-cli/issues/17495)
- [Authoring Google Antigravity Skills (Google Codelabs)](https://codelabs.developers.google.com/getting-started-with-antigravity-skills)
- [Build Autonomous Developer Pipelines using agents.md and skills.md in Antigravity (Google Codelabs)](https://codelabs.developers.google.com/autonomous-ai-developer-pipelines-antigravity)
- [Antigravity Rules: Guide with AGENTS.md & Examples (agentpedia.codes, 2026)](https://agentpedia.codes/blog/user-rules)
- [Antigravity Skills Setup Guide (agentpedia.codes, 2026)](https://agentpedia.codes/blog/antigravity-skills-setup-guide)
- [How to sync Antigravity settings across Macs (ConfigMesh)](https://configmesh.app/guides/antigravity-sync-macos)
- [How to Clear Antigravity Cache (agentpedia.codes, 2026)](https://agentpedia.codes/blog/clear-antigravity-cache)
- [docs: Windows config path is incorrect (opencode-antigravity-auth #251)](https://github.com/NoeFabris/opencode-antigravity-auth/issues/251)
- [AUR antigravity package (Arch Linux)](https://aur.archlinux.org/packages/antigravity)

### 2.11 Implications for `agents_sync` (§2 only)

- **`antigravity.py` `config_roots` keys: no change required for v0.5.** The user-level root `~/.gemini/antigravity/` is unchanged, so the existing `skill` customization_type adapter continues to work against the 2.0 standalone app. The adapter does NOT need to read from a hypothetical `~/.antigravity/`.
- **Skills path constant: unchanged.** `~/.gemini/antigravity/skills/<name>/SKILL.md` still holds globally-scoped skills in 2.0. Workspace-scoped skills, if/when `agents_sync` starts handling them, must be read from `<project>/.agents/skills/` (plural), not the 1.x `<project>/.agent/skills/`. Worth adding a compat-read of the singular form during a transition window since older repos will still carry it.
- **Backward-compatibility fallback: needed for the CLI surface, not the desktop app.** Antigravity CLI introduces a new sibling `~/.gemini/antigravity-cli/` tree. When `agents_sync` adds CLI support, it should sync to both `~/.gemini/antigravity/skills/` (desktop) and `~/.gemini/antigravity-cli/skills/` if/once that path is confirmed by the official `antigravity.google/docs/gcli-migration` mapping. **Add an explicit excludes list** for `antigravity-backup/`, `brain/`, `conversations/`, and `mcp_config.json` to avoid clobbering symlinks and transient state.
- **`gemini_cli.py` (planned for v0.5): affected.** The Gemini CLI ↔ Antigravity split is not a clean split of config roots — they still share `~/.gemini/` and specifically still collide on `~/.gemini/GEMINI.md`. `gemini_cli.py` should therefore (a) treat `~/.gemini/GEMINI.md` as a shared resource (last-writer-wins risk worth flagging in US-12 import semantics), (b) hard-code an exclusion for the `antigravity/`, `antigravity-ide/`, `antigravity-backup/`, and `antigravity-cli/` subdirectories so the Gemini CLI adapter does not accidentally walk into Antigravity territory, and (c) plan for the 2026-06-18 consumer-tier cutoff by surfacing a deprecation warning when invoked against a `~/.gemini/` that lacks Antigravity siblings.

---

## §3 — Skills surface

Skills are explicitly carried forward as one of the four headline 1.x features preserved in 2.0 (alongside Hooks, Subagents, and Extensions, which are renamed to "Antigravity plugins"). The skill surface evolves rather than breaking; the changes are additive plus one path rename with explicit backward compatibility.

### 3.1 Frontmatter schema — 1.x vs 2.0

The required-vs-optional split has not been broken; `name` and `description` remain the only required fields, and `allowed-tools` is still recognised. 2.0 documents three additional optional fields that 1.x did not (`license`, `compatibility`, `metadata`), and `version` appears in 2.0 example skills though the official docs still treat it as soft metadata rather than a load-bearing contract.

| Field | 1.x | 2.0 |
|---|---|---|
| `name` | required | required (unchanged; ≤64 chars, must match folder) |
| `description` | required | required (unchanged; semantic trigger) |
| `allowed-tools` | optional | optional (still experimental; **not** renamed to `tools`) |
| `license` | absent | optional (new) |
| `compatibility` | absent | optional (new) |
| `metadata` | absent | optional, free-form mapping (new) |
| `version` | absent (de facto) | optional, surfaced in 2.0 examples |

**No public information** that `model`, `priority`, `triggers`, or `expires_at` are part of the 2.0 schema. A `trigger: always_on` / `trigger: model_decision` field is documented for *Rules* files in 2.0, but those are a sibling artefact, not part of `SKILL.md`.

```yaml
---
name: security-auditor
description: Use when reviewing code for OWASP Top-10 issues or secrets.
allowed-tools: [read, grep, bash]
license: Apache-2.0
compatibility:
  antigravity: ">=2.0"
  agent-skills-spec: "1.x"
version: "1.2.0"
metadata:
  author: jane@example.com
  tags: [security, audit]
---
```

### 3.2 Field validity, rename, deprecation

No 1.x field is renamed or deprecated. `name`, `description`, and `allowed-tools` keep their 1.x semantics. **No public information** confirming an `allowed-tools → tools` rename. The "deprecated tool-use formats" called out in 2.0 migration notes refer to *custom agent* prompt structures, not skill frontmatter.

### 3.3 New skill kinds / types

2.0 does **not** introduce a typed `kind:` discriminator in frontmatter. Instead, ecosystem documentation describes three *de facto* role categories that all share the same `SKILL.md` shape: Domain Skills, Specialist Agents (persona instruction sets), and Commands/Workflows (multi-step procedures). Antigravity itself layers a separate three-artefact taxonomy in 2.0 — **Rules** (passive, always-on), **Skills** (agent-triggered), and **Workflows** (user-triggered macros) — but only Skills use `SKILL.md`. Rules and Workflows are sibling Markdown files with their own (different) frontmatter.

### 3.4 Auxiliary file layout

The 1.x `scripts/`, `references/`, `assets/` convention is preserved. 2.0 adds explicit guidance on *progressive disclosure*: keep `SKILL.md` ≤ 500 lines / ~5,000 tokens and push verbose material into `references/`, which is only loaded if the agent dereferences it. **No public information** about a new manifest file (e.g. `skill.json`, `manifest.yaml`) inside the skill folder.

### 3.5 Discovery paths

The most concrete breaking-ish change: 2.0 changes the **workspace** scope default.

| Scope | 1.x path | 2.0 path |
|---|---|---|
| Global | `~/.gemini/antigravity/skills/<name>/SKILL.md` | `~/.gemini/antigravity/skills/<name>/SKILL.md` (unchanged; also reads `~/.agent/skills/`) |
| Workspace | `<project>/.agent/skills/<name>/SKILL.md` | `<project>/.agents/skills/<name>/SKILL.md` (new default; `.agent/skills/` still read as fallback) |

The path is now `.agents/` (plural) with documented backward compatibility for the singular `.agent/`. There is no documented cloud-hosted skill registry in 2.0; "Managed Agents" is a separate runtime concept, not a skill location.

### 3.6 Skill packages

Google itself does not ship a signed/zipped `.agskill` or equivalent package format in 2.0. Packaging happens one rung up via the renamed **Antigravity plugins** (formerly Extensions): a plugin is a distribution that bundles `SKILL.md` files plus host-tool metadata (e.g. `.claude-plugin/marketplace.json`, `.agents/plugins/marketplace.json`). The individual `SKILL.md` files inside a plugin are still plain folder-based skills.

### 3.7 Built-in (system) skills

2.0 ships expert-vetted bundled skills users should not author themselves: **Modern Web Guidance** (>100 use cases, early preview), open-sourced **Android skills** via the stable Android CLI, and the DeepMind **science-skills** collection. These should be treated as read-only on the sync side.

### 3.8 Compatibility with the Anthropic Agent Skills open spec

2.0 stays compliant. Anthropic's spec was published to `agentskills.io` and released under Apache-2.0 / CC-BY-4.0 in late 2025, and Antigravity 2.0 skills are explicitly described as working "identically whether you're invoking them in Claude Code's CLI, Cursor's IDE, or Gemini's command-line tool" — i.e. the on-disk `SKILL.md` shape is unchanged. The new optional fields (`license`, `compatibility`, `metadata`) are present in the Anthropic reference spec as well, so 2.0 is *extending alongside* the spec rather than diverging.

### 3.9 1.x compatibility

1.x skill files round-trip into 2.0 without edits: 2.0 reads the legacy `.agent/skills/` workspace path, the legacy global path is unchanged, and the frontmatter schema is strictly additive. Migration concerns documented for 2.0 ("about 80% of custom agents migrate automatically") apply to **custom agents**, not skills.

### 3.10 Sources (§3)

- [Google launches Antigravity 2.0 (TechCrunch, 2026-05-19)](https://techcrunch.com/2026/05/19/google-launches-antigravity-2-0-with-an-updated-desktop-app-and-cli-tool-at-io-2026/)
- [Google Launches Antigravity 2.0 at I/O 2026 (MarkTechPost, 2026-05-19)](https://www.marktechpost.com/2026/05/19/google-launches-antigravity-2-0-at-i-o-2026-a-standalone-agent-first-platform-with-cli-sdk-managed-execution-and-enterprise-support/)
- [Transitioning Gemini CLI to Antigravity CLI (Google Developers Blog, 2026-05-19)](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
- [All the news from the Google I/O 2026 Developer keynote (Google Developers Blog, 2026-05-19)](https://developers.googleblog.com/all-the-news-from-the-google-io-2026-developer-keynote/)
- [Google Antigravity Documentation — antigravity.google/docs/skills](https://antigravity.google/docs/skills)
- [Antigravity Changelog (May 2026) — gradually.ai](https://www.gradually.ai/en/changelogs/antigravity/)
- [SKILL.md Format Specification — DeepWiki anthropics/skills](https://deepwiki.com/anthropics/skills/2.2-skill.md-format-specification)
- [Agent Skills Specification — agentskills.io](https://agentskills.io/specification)
- [How to Create AI Agent Skills in Google Antigravity & VS Code — Sabbirz blog, 2026](https://www.sabbirz.com/blog/how-to-create-ai-agent-skills-in-google-antigravity-vs-code)
- [Mastering Agent Skills: The Open Standard — antigravity.codes](https://antigravity.codes/blog/mastering-agent-skills)
- [Confused About Where to Put Your Agent Skills — Medium / Google Cloud Community, 2026](https://medium.com/google-cloud/confused-about-where-to-put-your-agent-skills-ea778f3c64f3)
- [How to Update Antigravity 2.0 — blog.ni18.in, 2026](https://blog.ni18.in/how-to-update-antigravity-2/)
- [antigravity-awesome-skills plugins documentation — sickn33](https://github.com/sickn33/antigravity-awesome-skills/blob/main/docs/users/plugins.md)
- [google-deepmind/science-skills — GitHub](https://github.com/google-deepmind/science-skills)
- [Build Better AI Agents with Google Antigravity Skills and Workflows — KDnuggets, 2026](https://www.kdnuggets.com/build-better-ai-agents-with-google-antigravity-skills-and-workflows)
- [Extend SKILL.md frontmatter — cline/cline issue #9934, 2026](https://github.com/cline/cline/issues/9934)

### 3.11 Implications for `agents_sync` (§3 only)

- **`parse_antigravity_skill_md` / `render_antigravity_skill_md`**: no signature change needed. The functions already route unknown frontmatter keys into `per_agentic_tool_extra["antigravity"]`, so `license`, `compatibility`, `metadata`, and `version` flow through losslessly today.
- **`KNOWN_FIELDS`** (currently `name`, `description`, `allowed-tools` plus pair-id): worth widening to also enumerate `license`, `compatibility`, `metadata`, `version`. This is cosmetic (changes which keys are *labelled* known-Antigravity vs unknown) rather than load-bearing for round-trip correctness.
- **Canonical `skill` schema** (v0.4.x): `name`, `description`, `allowed-tools` remain the only canonically-promoted fields. No protocol-breaking change required for v0.5. If the project later wants `version` or `license` to be cross-tool-canonical, that is a clean v0.6 additive extension.
- **Round-trip of 1.x files through a 2.0-aware adapter**: clean. No migration step. The only operational concern is the **workspace path rename** `.agent/skills/` → `.agents/skills/`. The adapter currently targets the global path `~/.gemini/antigravity/skills/`, which is unchanged; if/when `agents_sync` adds workspace-scope support, it should write `.agents/skills/` and read both.
- **New skill kinds → new `customization_type`?** Not warranted. The three role categories (Domain / Specialist Agent / Commands-Workflows) are conventions on top of the same `SKILL.md` shape. The genuinely distinct sibling artefacts in 2.0 — **Rules** and **Workflows** — *would* warrant their own `customization_type`s (e.g. `rule`, `workflow`) **if** the project later decides to sync them. Out of scope for v0.5 unless covered by the existing `rules` type.

## §4 — MCP & extensions

Antigravity 2.0 ships alongside Gemini 3.5, the Antigravity CLI (a Go rewrite of Gemini CLI), the Antigravity SDK, Managed Agents in the Gemini API, and a WebMCP browser-side preview. Gemini CLI sunsets 2026-06-18.

### 4.1 MCP config location

Antigravity 2.0 reuses the existing per-tool split that already existed in 1.x. The IDE/desktop app reads MCP servers from a dedicated file under the Gemini home; the CLI continues to read `~/.gemini/settings.json[mcpServers]` (the Antigravity CLI inherits Gemini CLI's settings file because it is the literal successor binary).

| Surface | 1.x path | 2.0 path |
|---|---|---|
| Antigravity desktop / IDE | `~/.gemini/antigravity/mcp_config.json` | `~/.gemini/antigravity/mcp_config.json` (unchanged) |
| Gemini CLI | `~/.gemini/settings.json` → `mcpServers` | n/a — Gemini CLI is sunsetting |
| Antigravity CLI (new) | n/a | `~/.gemini/settings.json` → `mcpServers` (inherited) |

The IDE file is explicitly described as separate from the CLI's `settings.json` and is typically a symlink; the published 2026-05 migration guidance calls out that the upgrader *excludes* `mcp_config.json` from the migration because it usually points at user-managed MCP state. No `~/.antigravity/` top-level directory has appeared in any 2026-05-19/20 source.

### 4.2 Schema changes

The Antigravity 2.0 release does **not** appear to break the 1.x `mcpServers` object schema. The three transports inherited from Gemini CLI are still the documented ones — `stdio` (`command`/`args`/`env`), SSE (`url`), and Streamable HTTP (`httpUrl`/`headers`).

A new optional field cluster — `serverUrl` + `authProviderType` + `oauth.scopes` — is observed in Google's own first-party server entries (e.g. AlloyDB, Developer Knowledge) shipped via the Cloud Data Agent Kit extension. It is unclear from current public docs whether `serverUrl`/`authProviderType` are first-party-only or general-purpose; treat as observed-but-unverified for now.

```json
// Stdio (unchanged from 1.x)
{
  "mcpServers": {
    "n8n-mcp": {
      "command": "node",
      "args": ["/usr/local/lib/node_modules/n8n-mcp/dist/mcp/index.js"],
      "env": {"MCP_MODE": "stdio", "LOG_LEVEL": "error"}
    },

    // Streamable HTTP (unchanged keys)
    "google-developer-knowledge": {
      "httpUrl": "https://developerknowledge.googleapis.com/mcp",
      "headers": {"X-Goog-Api-Key": "${DEV_KNOWLEDGE_KEY}"}
    },

    // New auth-aware variant observed on Google first-party servers
    "alloydb": {
      "serverUrl": "https://alloydb.googleapis.com/mcp",
      "authProviderType": "google_credentials",
      "oauth": {"scopes": ["https://www.googleapis.com/auth/cloud-platform"]}
    }
  }
}
```

No WebSocket or gRPC transport has been documented for Antigravity 2.0 as of 2026-05-20. WebMCP is a separate Chrome-side standard, not a new client-side transport in the CLI/IDE.

### 4.3 Shared vs separate MCP config with Gemini CLI

Still shared *de facto*: Antigravity CLI is the renamed Gemini CLI binary and continues to read `~/.gemini/settings.json[mcpServers]`. The Antigravity IDE retains its separate `~/.gemini/antigravity/mcp_config.json`. There is no new "Antigravity-only" MCP servers file outside of the existing IDE one.

### 4.4 New auth mechanisms

The platform-level Antigravity CLI now uses OAuth for Google identity (login via browser), but for **per-MCP-server** auth the public picture as of 2026-05-20 is:

- `${VAR}` env-var substitution still works for `command`, `args`, `env`, `url`, `headers` (unchanged).
- A new optional `oauth.scopes` + `authProviderType: "google_credentials"` shape is observed on Google first-party servers; this delegates token acquisition to the host's already-authenticated Google session.
- Generic third-party OAuth client-id/secret in `mcpServers` is *still not supported*: as recently as April 2026 Google docs state "Antigravity doesn't support the MCP OAuth specifications" for arbitrary servers. Whether 2.0 closes this gap on launch day is not documented yet.
- No mTLS or service-account fields documented.

### 4.5 Extension manifest

Gemini CLI "extensions" are renamed to **"Antigravity plugins"** in 2.0. No public 2026-05-19/20 source describes the new manifest filename or directory layout — i.e. whether `gemini-extension.json` is renamed to `antigravity-plugin.json`, whether the directory is now `~/.antigravity/plugins/<name>/`, or whether 1.x extension files are read as-is. Treat plugin manifest layout as **no public information yet**.

### 4.6 Skills vs plugins/extensions boundary

2.0 keeps the four 1.x primitives — Skills, Hooks, Subagents, and Plugins (formerly Extensions) — as distinct concepts. Skills are still folder-shaped (`SKILL.md` + assets) and load on-demand based on agent context; plugins are still the curated, installable distribution unit that *bundles* skills, hooks, MCP server entries, and rules. No re-drawing of the boundary is announced.

### 4.7 First-party MCP servers

2.0 ships and promotes a set of Google-authored MCP servers usable from both the IDE and the CLI:

- **Google Workspace** (Gmail, Drive, Calendar, Docs, Sheets, Chat, People) via the `gws` MCP server.
- **Google Developer Knowledge** MCP.
- **Google Cloud Data Agent Kit** servers (AlloyDB, BigQuery, etc.).

These are surfaced through `mcpServers` entries the user (or a plugin's install hook) writes into the same config file — they are *not* hard-wired system services. For sync purposes they look the same as any third-party entry.

### 4.8 Trust model

The 1.x per-server `trust: bool` field is not documented as having evolved into an enum. What 2.0 ships at the *workspace* level is "Trusted Workspaces" plus a per-tool auto-approve list and a browser-domain allowlist at `~/.gemini/antigravity/browserAllowlist.txt`, plus a `--auto-approve` CLI flag for session-scoped bypass. No `"signed_only"` / `"allowlisted"` enum has surfaced in 24h post-release.

### 4.9 Tool-discovery prefix

The 1.x `mcp_<alias>_<tool>` convention is preserved. The prefix is configurable via `MCP_TOOL_PREFIX` for users who want to rename it (e.g. `external_*`), but the default remains `mcp_`.

### 4.10 Forward compatibility

A 1.x `mcpServers` block — `stdio`, SSE, or Streamable HTTP — is readable as-is in 2.0 with no documented breakage. The migration tool deliberately *skips* `mcp_config.json` to avoid clobbering it. Per-server `trust`, `includeTools`, `excludeTools`, and `timeout` are not announced as removed or renamed.

### 4.11 Sources (§4)

- [Transitioning Gemini CLI to Antigravity CLI (Google Developers Blog, 2026-05-19)](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
- [TechCrunch — Google launches Antigravity 2.0 (2026-05-19)](https://techcrunch.com/2026/05/19/google-launches-antigravity-2-0-with-an-updated-desktop-app-and-cli-tool/)
- [MarkTechPost — Antigravity 2.0 at I/O 2026 (2026-05-19)](https://www.marktechpost.com/2026/05/19/google-launches-antigravity-2-0-at-i-o-2026-a-standalone-agent-first-platform-with-cli-sdk-managed-execution-and-enterprise-support/)
- [I/O 2026 developer highlights (Google blog, 2026-05-19)](https://blog.google/innovation-and-ai/technology/developers-tools/google-io-2026-developer-highlights/)
- [Chrome for Developers — WebMCP early preview (2026-05-19)](https://developer.chrome.com/blog/webmcp-epp)
- [How to use MCP servers in Antigravity (agentpedia.codes 2026)](https://agentpedia.codes/blog/antigravity-mcp-tutorial)
- [Gemini CLI → Antigravity CLI migration guide (agentpedia.codes 2026)](https://agentpedia.codes/blog/gemini-cli-to-antigravity-cli-migration)
- [Antigravity security guide (agentpedia.codes)](https://agentpedia.codes/blog/antigravity-security-guide)
- [Auto-approve & autopilot guide (agentpedia.codes 2026)](https://agentpedia.codes/blog/antigravity-auto-accept-autopilot-guide)
- [Authenticate to Google MCP servers (Google Cloud Docs, 2026-04)](https://docs.cloud.google.com/mcp/authenticate-mcp)
- [Use MCP servers — Google Cloud Data Agent Kit](https://docs.cloud.google.com/data-cloud-extension/antigravity/use-mcp-servers)
- [CLI plugins and extensions — Google Cloud Data Agent Kit](https://docs.cloud.google.com/data-cloud-extension/antigravity/use-cli-plugins)
- [Developer Knowledge MCP server (Google Developers)](https://developers.google.com/knowledge/mcp)
- [Google Workspace MCP servers in Antigravity (Google Codelabs)](https://codelabs.developers.google.com/google-workspace-mcp-antigravity)
- [github-mcp-server install-antigravity.md](https://github.com/github/github-mcp-server/blob/main/docs/installation-guides/install-antigravity.md)
- [n8n-mcp ANTIGRAVITY_SETUP.md](https://github.com/czlonkowski/n8n-mcp/blob/main/docs/ANTIGRAVITY_SETUP.md)
- [Auth guide for Cloud MCP servers in Antigravity (Google AI Developers Forum)](https://discuss.ai.google.dev/t/guide-fixing-authentication-for-the-google-developer-knowledge-mcp-server-and-other-cloud-servers-in-antigravity/136601)

### 4.12 Implications for `agents_sync` (§4 only)

1. **Canonical `mcp_server` fields (v0.5).** The 1.x field set remains sufficient for the *baseline* Antigravity 2.0 case. Add three *optional* canonical fields, marked nullable so 1.x and non-Google adapters can ignore them: `server_url` (distinct from `url`), `auth_provider_type` (enum like `"google_credentials"`), `oauth_scopes` (list[str]).
2. **`SharedKeyedMapLayout.shared_path`.** Antigravity 2.0's IDE MCP file is still `~/.gemini/antigravity/mcp_config.json`; Antigravity CLI still uses `~/.gemini/settings.json[mcpServers]`. Existing v0.5 layout values do **not** need to change.
3. **New transports.** No new transport types (WebSocket, gRPC) announced. WebMCP lives in Chrome.
4. **First-party MCP servers — sync or skip?** First-party Workspace / Developer Knowledge / Cloud Data Agent Kit servers are user-authored entries in the same `mcpServers` map; they should stay in scope for sync. Recommend a documented opt-out allowlist (names matching `^google-`, `gws`, `alloydb`) for users who want them host-local.
5. **NFR-15 secret-redaction heuristics.** Existing `headers.Authorization`, `headers.X-*-Api-Key`, and `env.*_TOKEN`/`*_SECRET`/`*_KEY` patterns cover the observed 2.0 cases. Add `authProviderType` to a "carry verbatim, never redact" allowlist so it doesn't accidentally get masked.
6. **`gemini_cli.py` adapter — fork or not?** Do not fork yet. Keep one `gemini_cli.py` module with two layout instances ("gemini-cli settings", "antigravity ide mcp_config"). Revisit only if Google ships a distinct `~/.antigravity/` tree.
7. **Open items.** Plugin manifest filename/path (§4.5), whether per-server `trust` evolves into an enum (§4.8), whether generic third-party OAuth lands for `mcpServers` (§4.4). All three are "no public information yet" as of 2026-05-20.

## §5 — New customization surfaces

Scope: what's new for **Antigravity users** in 2.0. "New" = did not exist for Antigravity 1.x users, regardless of Gemini CLI history. Antigravity 2.0 ships as a standalone desktop app plus Antigravity CLI (`agy`, Go-based) plus SDK plus Managed Agents.

### 5.1 Subagents / personas

**Shipped, file-backed, multi-tier.** 2.0 introduces **dynamic subagents** as a first-class feature (1.x had only the implicit built-in browser subagent). The primary agent acts as orchestrator and delegates to specialised subagents (Architect, Coding, etc.).

- **Global subagent path:** `~/.subagents/` — community-reported layout has a `manifest.json` registry plus per-agent directories with instruction + state files.
- **Project subagent path:** `<workspace>/.subagents/`.
- **Persona authoring file:** `agents.md` (lowercase, distinct from `AGENTS.md` rules) lets users declare named expert personas that the orchestrator can call.
- **Identity field:** YAML frontmatter `name` + `description` (description acts as the routing/trigger signal). `tools:` and `model:` fields appear in community templates; no official schema doc has been published as of 2026-05-20.
- **Scope:** user-level (`~/.subagents/`) and project-level.
- **Sync risks:** `manifest.json` is a stateful registry (likely contains absolute paths or machine IDs) — must be excluded or rebuilt on the receiving host. `agents.md` is plain Markdown and safe to sync.
- **Caveat:** the official `antigravity.google/docs/agent` page does not commit to `~/.subagents/` as the canonical path — that path is from community projects. Treat as **announced + shipped feature, schema TBD**.

### 5.2 Slash commands

**Unified into Skills as of 2.0 / Antigravity CLI.** Behavioural change vs both 1.x (which had no user slash commands) and Gemini CLI (which used `~/.gemini/commands/*.toml`).

- **Path:** user-defined slash commands are now authored as **Skills** under `~/.gemini/antigravity/skills/<command-name>/SKILL.md` (global) or `<workspace>/.agents/skills/<command-name>/SKILL.md` (workspace).
- **Format:** Markdown with YAML frontmatter (`name`, `description` mandatory).
- **Identity:** the Skill folder name doubles as the slash command name.
- **Workflow slash commands:** additionally, text files in `.agents/workflows/` register chat-invocable orchestration commands that chain personas + skills.
- **Migration:** `agy plugin import gemini` migrates `~/.gemini/commands/*.toml` into the Skills layout; the legacy TOML format is preserved for plugin-imported commands but new authoring is Markdown.
- **Scope:** user, project. No cloud slash-command surface documented.
- **Sync risks:** SKILL.md is portable; workflow files reference persona names that must exist on the target machine.

### 5.3 Hooks

**Announced and present in Antigravity CLI; standalone app status mixed.**

- The Antigravity CLI explicitly inherits Gemini CLI's hooks subsystem ("Antigravity CLI keeps Agent Skills, Hooks, Subagents, Extensions").
- **Path/schema:** hooks live in `settings.json` under a `hooks` key, with `PreToolUse` / `PostToolUse` matchers and command lists — same shape as the Gemini CLI hooks schema, since the CLI is the successor.
- **Plugin hooks:** plugins can ship `hooks/hooks.json` wrapped in `{"hooks": {...}}`.
- **Marketing also lists "JSON hooks"** as a headline 2.0 feature for the standalone app, but at least one cross-platform tracking project (context-mode) reports the standalone app "has no session support, no hooks" today — **announced for 2.0 but inconsistently shipped between CLI (shipped) and standalone app (partial/aspirational)** as of 2026-05-20.
- **Scope:** user (`~/.gemini/settings.json`), workspace (`<workspace>/.gemini/settings.json`), and plugin-bundled.
- **Sync risks:** hook commands are arbitrary shell strings — they reference local binaries and absolute paths; safe to sync only with path normalisation.

### 5.4 Rules

**Cross-tool rules already shipped in 1.20.3 (2026-03-05); 2.0 keeps them.**

- **`AGENTS.md`** — cross-tool rules file readable by Antigravity, Cursor, Claude Code. Introduced for Antigravity in v1.20.3.
- **User-level path:** `~/.gemini/AGENTS.md` (created by Antigravity's "+ Global" UI action).
- **Project-level path:** `<workspace>/AGENTS.md` and `<workspace>/.agent/rules/*.md`.
- **`GEMINI.md`** remains the Antigravity-specific override file at `~/.gemini/GEMINI.md` (user) and `<workspace>/GEMINI.md` (project). Splits concerns with AGENTS.md rather than replacing it.
- **Format:** plain Markdown, no required frontmatter.
- **Scope:** user, project. No `.mdc` Cursor-style frontmatter rules — Antigravity uses bare Markdown.
- **Sync risks:** very low (pure prose). One known conflict: `~/.gemini/GEMINI.md` is shared with the legacy Gemini CLI, which can cause double-writes (gemini-cli #16058).

### 5.5 Memory

**Implicit memory exists; user-syncable surface is limited.**

- The standalone app maintains "brain entries," "scratch space," and "conversation files" under `~/.gemini/antigravity/`. These are auto-written, not Cascade-style user-curated memories.
- The 2.0 migration is known to strand these into `~/.gemini/antigravity-backup/` for many users — confirming this is **opaque session/state storage, not a portable customization**.
- **No formal "memory file" surface** comparable to Windsurf Cascade's `global_rules.md` has been publicly documented. The closest user-authored persistent memory is `GEMINI.md` / `AGENTS.md`.
- **Sync risk:** **do not sync.** This is session state, not customization.

### 5.6 Modes / profiles / personas

**Shipped, but largely UI-bound, not file-syncable.**

- **Autonomy profiles:** four preset modes — Secure, Review-driven development, Agent-driven development, Custom. The "Custom" profile lets users define terminal auto-execute policy, allow/deny lists, browser URL allowlists.
- **Work modes:** Planning mode, Fast mode (auto-switched by the agent).
- **Agent Personas:** distinct domain-expert presets selectable from the UI; the user-authored equivalent is the `agents.md` persona file from §5.1.
- **Persistence:** autonomy custom settings live in the standalone app's `settings.json` under the per-OS Antigravity user-settings tree (macOS: `~/Library/Application Support/Antigravity/User/settings.json`; Linux: `~/.config/Antigravity/User/settings.json`; Windows: `%APPDATA%\Antigravity\User\settings.json`). There's no separate `modes/` directory.
- **Sync risks:** allow/deny command lists are environment-sensitive; review before syncing.

### 5.7 Plugins / extensions evolution

**Renamed and re-rooted.**

- 1.x "extensions" (`~/.gemini/extensions/<name>/`) → 2.0 **"Antigravity plugins."**
- `agy plugin import gemini` migrates extensions, commands, and most MCP entries; **workspace skill folders and inline MCP config in `settings.json` require manual moves**.
- Plugin marketplace flags 2.0-incompatible plugins; users can run them in "limited mode" or wait for an update.
- No public official path for the plugin install root in 2.0 has been confirmed today — community workarounds still reference `~/.gemini/extensions/` for now.
- **Sync risk:** plugins frequently bundle binaries and absolute paths in manifests — exclude from sync until canonical 2.0 path and lockfile format are documented.

### 5.8 Cloud-side artifacts

**Limited and enterprise-gated.**

- The **Gemini Enterprise Agent Platform** integration allows org-managed agent templates and policies, plus **custom agent templates in AI Studio** for enterprise. These are account-stored, not file-backed.
- **Managed Agents in the Gemini API** are cloud-hosted execution environments — not customization in the on-disk sense.
- For individual users, there is **no public Cursor-style "User Rules" cloud pane** documented as of 2026-05-20.
- **Sync risk:** out-of-scope for any file-based sync tool.

### 5.9 Keybindings / status line / themes

**Shipped, VS Code-derived, file-backed.**

- **Keybindings:** `~/Library/Application Support/Antigravity/User/keybindings.json` (macOS), `%APPDATA%\Antigravity\User\keybindings.json` (Windows), `~/.config/Antigravity/User/keybindings.json` (Linux). JSON format identical to VS Code.
- **Themes:** VS Code-compatible; user theme choice stored in `settings.json` under `workbench.colorTheme`; the theme extension itself lives in the (still community-tracked) Antigravity extensions folder.
- **Status line / color overrides:** `settings.json["workbench.colorCustomizations"]`.
- **Scope:** user, machine-local.
- **Sync risks:** keybindings.json is OS-keyed (`mac`, `linux`, `windows` blocks) so cross-OS sync needs platform-aware merging. Themes referenced by name will fail silently if the underlying extension isn't installed on target.

### 5.10 Anything else under `~/.gemini/antigravity/`

Confirmed sub-paths in 2.0:

- `~/.gemini/antigravity/skills/` — user-level skills (unchanged from 1.x).
- `~/.gemini/antigravity/mcp_config.json` — MCP server configuration, often a symlink; **explicitly excluded** from the migration rsync recipe.
- `~/.gemini/antigravity/` (root) — opaque brain/scratch/conversation files (do not sync; see §5.5).
- **Scheduled tasks** are announced as a 2.0 feature (cron-like schedules invoking agents) but **no public file path or schema has been published** in the 24 hours since launch. Treat as **announced, schema TBD**.

### 5.11 Sources (§5)

- [All the news from the Google I/O 2026 Developer keynote (developers.googleblog.com, 2026-05-19)](https://developers.googleblog.com/all-the-news-from-the-google-io-2026-developer-keynote/)
- [Transitioning Gemini CLI to Antigravity CLI (developers.googleblog.com, 2026-05-19)](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
- [I/O 2026 developer highlights (blog.google, 2026-05-19)](https://blog.google/innovation-and-ai/technology/developers-tools/google-io-2026-developer-highlights/)
- [MarkTechPost — Google Launches Antigravity 2.0 (2026-05-19)](https://www.marktechpost.com/2026/05/19/google-launches-antigravity-2-0-at-i-o-2026-a-standalone-agent-first-platform-with-cli-sdk-managed-execution-and-enterprise-support/)
- [TechCrunch — Antigravity 2.0 (2026-05-19)](https://techcrunch.com/2026/05/19/google-launches-antigravity-2-0-with-an-updated-desktop-app-and-cli-tool-at-io-2026/)
- [9to5Google — Agentic developer suite (2026-05-19)](https://9to5google.com/2026/05/19/google-antigravity-agentic-developer-suite/)
- [Creati.ai — Antigravity 2.0 multi-agent (2026-05-20)](https://creati.ai/ai-news/2026-05-20/google-antigravity-20-turns-coding-into-multi-agent-development/)
- [DEV — Antigravity is Dead. Long Live Antigravity. (2026-05)](https://dev.to/turingsoracle/antigravity-is-dead-long-live-antigravity-186m)
- [Antigravity Cheat Sheet (agentpedia.codes, 2026)](https://agentpedia.codes/blog/antigravity-cheat-sheet)
- [Antigravity Rules: AGENTS.md guide (agentpedia.codes, 2026)](https://agentpedia.codes/blog/user-rules)
- [AGENTS.md cross-tool guide (agentpedia.codes, 2026)](https://agentpedia.codes/blog/antigravity-agents-md-guide)
- [Gemini CLI → Antigravity CLI migration guide (agentpedia.codes, 2026)](https://agentpedia.codes/blog/gemini-cli-to-antigravity-cli-migration)
- [MCP setup guide (agentpedia.codes, 2026)](https://agentpedia.codes/blog/antigravity-mcp-tutorial)
- [Antigravity v1.20.3 release (Google AI Dev Forum, 2026-03-05)](https://discuss.ai.google.dev/t/antigravity-update-1-20-3-2026-3-5/129320)
- [Authoring Google Antigravity Skills (Google Codelabs)](https://codelabs.developers.google.com/getting-started-with-antigravity-skills)
- [Build Autonomous Developer Pipelines using agents.md and skills.md (Google Codelabs)](https://codelabs.developers.google.com/autonomous-ai-developer-pipelines-antigravity)
- [Antigravity Agent Modes / Settings (Google docs)](https://antigravity.google/docs/agent-modes-settings)
- [Antigravity sub agents forum thread (Google AI Dev Forum)](https://discuss.ai.google.dev/t/antigravity-sub-agents/114381)
- [Scheduled / cron-like tasks (Google AI Dev Forum)](https://discuss.ai.google.dev/t/can-antigravity-agents-run-scheduled-cron-like-tasks-e-g-checking-an-external-service-every-10-minutes/128340)
- [OleynikAleksandr/antigravity-subagents (community)](https://github.com/OleynikAleksandr/antigravity-subagents)
- [fpozoc/antigravity-hooks (hook templates)](https://github.com/fpozoc/antigravity-hooks)
- [gemini-cli Issue #16058 (`GEMINI.md` conflict)](https://github.com/google-gemini/gemini-cli/issues/16058)
- [mksglu/context-mode platform-support (Antigravity has no hook support)](https://github.com/mksglu/context-mode/blob/main/docs/platform-support.md)
- [Hacker News — Google Antigravity 2.0 (2026-05-19)](https://news.ycombinator.com/item?id=48196838)
- [Hacker News — Antigravity 2.0 installer breaks existing IDEs (2026-05-19)](https://news.ycombinator.com/item?id=48199074)

### 5.12 Implications for `agents_sync` (§5 only)

**Coverage by the planned v0.5 customization_types `{agent, skill, rules, slash_command, mcp_server}`:**

- **`skill`** — already supported; in 2.0 the path remains `~/.gemini/antigravity/skills/`. No adapter change needed.
- **`slash_command`** — partially redundant for Antigravity, because 2.0 collapses slash commands into Skills (`skills/<cmd>/SKILL.md`). The `slash_command` type still makes sense for Claude Code / Gemini CLI legacy / Cursor, but for Antigravity the adapter should map `slash_command` writes to the Skills path or refuse the write and log "use skill instead." Document in the adapter.
- **`rules`** — fits cleanly: `AGENTS.md` (and `GEMINI.md` if we want Antigravity-specific overrides) at user level (`~/.gemini/AGENTS.md`) and project level. Add to `antigravity.py`'s `supported_customization_types`.
- **`agent`** — fits the new dynamic-subagent feature, but the **canonical schema is unconfirmed** (`~/.subagents/` with `manifest.json` is community-derived, not Google-confirmed). **Recommend a spike** before committing the adapter; ship `agent` for Claude Code/Gemini CLI first and gate Antigravity behind a feature flag until Google publishes a doc.
- **`mcp_server`** — fits, but two Antigravity-specific quirks must be honoured: (a) JSON key is `serverUrl` not `url` for the new auth-aware form; (b) `mcp_config.json` is often a symlink and is **explicitly excluded** from the Antigravity 2.0 migration rsync. The adapter must detect symlinks and refuse to overwrite without `--force`.

**Gaps — new `customization_type` values to consider:**

- **`hooks`** — new for Antigravity-via-CLI; same shape as Gemini CLI's `settings.json[hooks]`. Worth adding for v0.6 once the standalone-app hook story stabilises. High sync risk because hook commands are arbitrary shell.
- **`mode`** / **`profile`** — the autonomy-profile custom config is stored in the per-OS Antigravity `User/settings.json`. Out of scope for v0.5.
- **`keybindings`** — straightforward JSON sync but OS-keyed; defer.
- **`workflow`** — `.agents/workflows/*` files are a real authoring surface and don't fit any existing type cleanly. Likely v0.6.

**`antigravity.py` adapter — `supported_customization_types` recommendation for v0.5:** `{skill, rules, mcp_server}` confirmed; add `slash_command` with the "writes go to Skills" caveat in the docstring; **defer `agent`** until Google publishes the subagent file schema.

**Out-of-scope (record in `docs/project_description.md`):** Gemini Enterprise Agent Platform templates, AI Studio cloud agent templates, Managed Agents (Gemini API), auto-written brain/scratch/conversation files, scheduled tasks (schema unpublished).

**Hard forks from Gemini CLI conventions that strain the path-ownership model:**

1. **Slash commands** — Gemini CLI uses `~/.gemini/commands/*.toml`; Antigravity 2.0 has folded them into Skills (Markdown). `gemini_cli.py` and `antigravity.py` cannot share a writer for `slash_command` — they must diverge. Cleanest hard fork.
2. **Plugins/Extensions** — same name, different canonical root after migration (currently undocumented for 2.0). Treat as separate adapter concerns; do not assume a shared `~/.gemini/extensions/` writer.
3. **`~/.gemini/GEMINI.md`** is co-owned by Gemini CLI and Antigravity (#16058). The path-ownership model must explicitly choose one owner — recommend **Antigravity owns it post-2.0**, since Gemini CLI is being deprecated on 2026-06-18; for `rules`, prefer `AGENTS.md` over `GEMINI.md` as the synced artifact to avoid the conflict entirely.

## §6 — Migration & compatibility with 1.x

Antigravity 2.0 shipped on 2026-05-19 alongside a Go-based `agy` CLI, an SDK, and Managed Agents in the Gemini API. ~24 hours in, the picture below is what is verifiable; everything else is flagged "no public information yet".

### 6.1 Migration tooling

Google did not ship a single one-shot `antigravity migrate`. The official path is the new CLI's plugin importer:

> "`agy plugin import gemini` handles extensions, commands, and most MCP entries. However, workspace skill folders and inline MCP config in `settings.json` still need manual moves because their canonical locations changed."
> (agentpedia.codes migration guide, 2026-05-19)

It runs automatically on first launch ("Antigravity CLI prompts to migrate Gemini CLI extensions to Antigravity plugins") and can be re-run explicitly. **Dry-run / reversibility / idempotency are not documented** — no public information yet. The desktop installer also performs an in-place workspace upgrade on first launch ("Upgrade workspace format? The upgrade re-indexes your project files, refreshes the agent context graph, and converts old task definitions to the new schema").

Google says **"About 80% of custom agents migrate automatically, while the other 20% need a tweak to the system prompt or tool list"** and the desktop UI flags the latter with a yellow "Needs Review" tag in the Agents panel.

### 6.2 1.x SKILL.md forward-compat

The 1.x SKILL.md frontmatter contract (delimited `---`, `name:`, `description:`, optional `allowed-tools:`) is still parsed by 2.0. Failure modes are unchanged from 1.x:

> "A SKILL.md is silently skipped if either field is missing, if the delimiters (`---` on their own lines) are absent, or if any text (an H1 title, a comment, even a blank line) appears before the opening `---`."

For workspace skills, the canonical directory drifted: "Antigravity now defaults to `.agents/skills`, but still maintains backward support for `.agent/skills`." Global-scope skills remain at `~/.gemini/antigravity/skills/`. No public information yet on whether 2.0 emits deprecation warnings on load.

### 6.3 Path deprecations

`~/.gemini/` is **not** retired in 2.0 — Google reused it and added two sibling directories. The user-visible layout:

| 1.x path | 2.0 status | Notes |
|---|---|---|
| `~/.gemini/antigravity/skills/<name>/SKILL.md` | **Kept** (live data for the 2.0 standalone app) | Often left incomplete after first launch — see §6.5 |
| `~/.gemini/antigravity-ide/` | **New** (live data for the 1.x IDE if both installed) | Coexistence is fragile (§6.10) |
| `~/.gemini/antigravity-backup/` | **New** (migration snapshot) | Frequently more complete than the live directory |
| `~/.gemini/settings.json` | **Kept** but schema-migrated on first launch | See §6.5 |
| `~/.gemini/GEMINI.md` | **Kept**, still read | Pre-existing conflict with Antigravity Global Rules persists (gemini-cli #16058) |
| `~/.gemini/extensions/<name>/gemini-extension.json` | **Deprecated** — migrated to Antigravity plugins by `agy plugin import gemini` | Manifest renamed; old path still readable for fallback |
| `~/.gemini/agents/<name>.md` | **Kept** | Gemini-CLI subagents; 2.0 still reads them |
| `~/.gemini/commands/<name>.toml` | **Kept**; migrated to plugin commands by the importer | |
| `~/.gemini/oauth_creds.json`, `installation_id` | **Kept in place** (see §6.6–§6.7) | |

### 6.4 Field deprecations

| Field | 1.x meaning | 2.0 status |
|---|---|---|
| `name` (frontmatter) | required | **Required**, unchanged |
| `description` (frontmatter) | required | **Required**, unchanged |
| `allowed-tools` (frontmatter) | hint, not enforced in 1.x | **Still parsed, still not enforced** in 2.0 desktop |
| Deprecated 1.x tool-use prompt formats inside agent bodies | accepted | **Accepted with warning** — desktop tags as "Needs Review"; CLI behaviour not documented |

No fields are documented as a **hard fail** in 2.0 yet. No public information yet on a schema-version field analogous to `schema: v2`.

### 6.5 settings.json schema migration

Yes — first launch rewrites `~/.gemini/settings.json` in place. The pre-migration copy is dropped into `~/.gemini/antigravity-backup/`. Inline MCP entries inside `settings.json` are **not** migrated automatically; users must move them by hand to the new MCP config location. Recovery advice from the community is to `rsync ~/.gemini/antigravity-backup/ ~/.gemini/antigravity/ --exclude mcp_config.json`, because **"`mcp_config.json` is usually a symlink pointing at your local MCP server configuration — overwrite it and you break your active MCP connections"**.

### 6.6 Auth migration

`~/.gemini/oauth_creds.json` is preserved on the 1.x → 2.0 upgrade — community reports show the desktop app reusing existing Google sign-in state on launch. However, a login-crash bug is already reported on 2.0 (`TypeError: Do not know how to serialize a BigInt` on first auth refresh), forcing some users into a re-prompt. **Preserved in the happy path, re-prompt in the crash path.**

### 6.7 Telemetry / installation_id continuity

`installation_id` is kept in `~/.gemini/`; no public information yet on whether 2.0 issues a fresh ID or stitches the old one through to the new telemetry pipeline.

### 6.8 Roll-back path

Downgrade is supported but lossy. The official store keeps "View Previous Releases" → **1.23.2** available; uninstalling 2.0 and reinstalling 1.x is the documented path.

> "You can uninstall 2.0 and reinstall an older version from your local backup — but your 2.0 workspace files won't open in 1.x, so you'd need to restore from your pre-update backup too."

Skills written in the 1.x format survive the round-trip; workspaces touched by 2.0 do not.

### 6.9 Community / ecosystem impact

First-24-hour signal is mixed:

- **`sickn33/antigravity-awesome-skills`** (1,400+ skills, the largest community catalogue) advertises Antigravity coverage at v11.3.0; its README and CATALOG already list Antigravity as a target alongside Claude Code, Cursor, Codex CLI, and Gemini CLI. No 2.0-specific changelog entry retrievable today (CHANGELOG returned a load error on direct fetch).
- A Hacker News thread is dominated by the **installer-clobber bug**: "The 2.0 installer dropped `app.asar` (2.0 code) next to the IDE's `app/` folder, and the asar wins — so both `Antigravity IDE.exe` and `Antigravity.exe` end up loading 2.0."
- A separate forum thread ("Whats with Antigravity 2.0?") shows confusion about whether 2.0 is opt-in.

### 6.10 Coexistence with Gemini CLI

Gemini CLI is being sunset for individual/AI Pro/Ultra tiers on **2026-06-18**; enterprise (Code Assist Standard/Enterprise, Cloud) and paid API-key access continue. There is no version-lock between Antigravity 2.0 and a specific Gemini CLI release — the two are diverging products that share the `~/.gemini/` directory by historical accident. Installing 2.0 alongside the 1.x IDE causes an OS-level binary collision on Windows (the `app.asar` issue); the recommended workaround is to pick one product per machine.

### 6.11 Sources (§6)

- [Transitioning Gemini CLI to Antigravity CLI (Google Developers Blog, 2026-05-19)](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
- [google-gemini/gemini-cli Discussion #27274 (2026-05-19)](https://github.com/google-gemini/gemini-cli/discussions/27274)
- [TechCrunch — Google launches Antigravity 2.0 (2026-05-19)](https://techcrunch.com/2026/05/19/google-launches-antigravity-2-0-with-an-updated-desktop-app-and-cli-tool/)
- [Gemini CLI → Antigravity CLI Migration Guide (agentpedia.codes, 2026-05-19)](https://agentpedia.codes/blog/gemini-cli-to-antigravity-cli-migration)
- [How to Downgrade Antigravity & Disable Auto-Update (agentpedia.codes, 2026-05-19)](https://agentpedia.codes/blog/antigravity-downgrade-disable-auto-update)
- [Antigravity is Dead. Long Live Antigravity. (DEV.to, 2026-05-19)](https://dev.to/turingsoracle/antigravity-is-dead-long-live-antigravity-186m)
- [How to Update Antigravity 2.0 (blog.ni18.in, 2026-05-19)](https://blog.ni18.in/how-to-update-antigravity-2/)
- [Hacker News — Antigravity 2.0 installer breaks existing IDEs (2026-05-19)](https://news.ycombinator.com/item?id=48199074)
- [Hacker News — Google Antigravity 2.0 (2026-05-19)](https://news.ycombinator.com/item?id=48196838)
- [Google AI Developers Forum — "Antigravity 2.0 is awful…" (2026-05-19)](https://discuss.ai.google.dev/t/antigravity-2-0-is-awful-heres-how-to-get-the-previous-version/145512)
- [Google AI Developers Forum — Installation/Update Bug solution (2026-05-19)](https://discuss.ai.google.dev/t/solution-for-antigravity-2-0-installation-update-bug/145787)
- [Google AI Developers Forum — IDE Wizard Migration Failure (2026-05-19)](https://discuss.ai.google.dev/t/antigravity-bug-report-ide-wizard-migration-failure-on-update/145851)
- [gemini-cli Issue #16058 — `GEMINI.md` conflict](https://github.com/google-gemini/gemini-cli/issues/16058)
- [sickn33/antigravity-awesome-skills](https://github.com/sickn33/antigravity-awesome-skills)
- [Login-crash gist (BigInt serialize) (2026-05-19)](https://gist.github.com/Abd2023/206fbfedf1e4531e8cad0a285357d8b7)
- [agensi.io — SKILL.md Specification (2026-05-19)](https://www.agensi.io/learn/skill-md-format-reference)

### 6.12 Implications for `agents_sync` (§6 only)

**Shim in `src/agents_sync/agentic_tools/antigravity.py`.** Not yet, and probably not ever in the strict sense: the 1.x SKILL.md frontmatter contract is **forward-compatible** into 2.0. The existing reader stays valid. Two surgical changes are warranted:

1. Add `.agents/skills` as a recognised workspace-scope skill directory **in addition to** `.agent/skills`, because 2.0 default-writes the new path.
2. Treat `~/.gemini/antigravity-backup/` as **read-only, never sync-source**. If `agents_sync` blindly snapshots `~/.gemini/`, it will pick up the migration backup and risk overwriting the live `antigravity/` on the next round-trip. Add a hard-coded exclude of `antigravity-backup/`, `antigravity-ide/`, and `mcp_config.json` (the last because it is typically a symlink to a local MCP socket file; copying its target breaks active connections).

**One-shot `agents-sync migrate antigravity`.** Don't build one. Google's `agy plugin import gemini` already covers extensions/commands/MCP, and the desktop-app first-launch flow handles workspaces. What `agents_sync` should add is a **detect-and-warn** pass: on snapshot/restore, if 2.0 paths (`antigravity-backup/`, `.agents/skills`) are observed, emit one log line pointing the user at Google's migration guide.

**v0.5 timing against the 2.0 GA window.** Hold v0.5 until **at least 2026-06-01** — the 24-hour signal includes a known installer-clobber bug (`app.asar` collision), a login crash (`BigInt` serialize), and the antigravity-backup stranding issue. The 2026-06-18 Gemini CLI sunset is the hard deadline for being ready.

**Downgrade-during-sync data loss risk.** Real. A user who runs `agents-sync` against an active 2.0 install, then downgrades to 1.23.2, will see workspace files that "won't open in 1.x", and the archive may now contain a mix of 1.x global skills + 2.0 workspace artefacts that no single version can fully consume. Mitigation: the archive's per-pair `last_modified` (US-12 / state schema v3) should be extended with an `antigravity_version` tag captured at snapshot time. On restore, refuse to apply 2.0-tagged artefacts to a 1.x install and vice-versa, with a `--force` escape hatch.

**`docs/v0.5_implementation_plan.md` additions needed:**

- New section: *Antigravity 2.0 surface*. List the three new directories under `~/.gemini/`, declare two as excluded from snapshot, document the `.agents/skills` vs `.agent/skills` precedence.
- Extend the state schema (currently v3) to record `antigravity_version` per pair; bump to v4 if the field is required for correctness.
- Add an AC: *"Given a 2.0 install with `antigravity-backup/` present, snapshot MUST NOT include `antigravity-backup/` or `antigravity-ide/`, and MUST NOT follow the `mcp_config.json` symlink."*
- Add a Phase: *Antigravity 2.0 compatibility validation* — manual test plan against a fresh 2.0 install, a 1.x install, and a 2.0 install rolled back to 1.x.
- Defer any "automated migration" feature to v0.6 at earliest; v0.5 only needs to safely coexist with whatever state Google's own migrator leaves behind.

## §7 — Consolidated impact on `agents_sync`

Synthesising the per-section findings into adapter, protocol, governance, and sequencing decisions.

### 7.1 Adapter structure — three modules, not one

The Antigravity ecosystem after 2.0 is **three distinct surfaces** sharing `~/.gemini/`:

1. **Antigravity 2.0 standalone desktop app** — owner of `~/.gemini/antigravity/` (skills, mcp_config.json, brain/conversations).
2. **Antigravity CLI (`agy`, Go-based)** — owner of `~/.gemini/antigravity-cli/` for plugin imports, but reads `~/.gemini/settings.json[mcpServers]` (inherited from Gemini CLI).
3. **Gemini CLI** — sunsetting for consumer tiers on 2026-06-18; remains live for Code Assist Standard / Enterprise.

Recommendation: **three adapter modules**, not one.

| Module | Status | `supported_customization_types` for v0.5 |
|---|---|---|
| `antigravity.py` (existing) | extend | `{skill, rules, mcp_server, slash_command}` — `slash_command` writes route to Skills with a docstring caveat |
| `gemini_cli.py` (planned for v0.5) | ship as planned | `{agent, rules, slash_command, mcp_server}` — no `skill` per D3 path-ownership |
| `antigravity_cli.py` (new, v0.6 target) | spike now, ship later | TBD — most likely `{skill, rules, mcp_server, slash_command, hooks}` |

`antigravity_cli.py` is **not** required for v0.5 GA. It is deferred to v0.6 with a spike in v0.5 to confirm the `~/.gemini/antigravity-cli/` schema. v0.5 ships with the existing two-adapter split.

### 7.2 `antigravity.py` adapter — required v0.5 changes

The existing skills-only adapter expands to `{skill, rules, mcp_server, slash_command}` with these specific edits:

- **Skills**: no parse/render change. The 1.x SKILL.md frontmatter contract (name, description, optional allowed-tools) is forward-compatible into 2.0. Optional-field widening of `KNOWN_FIELDS` to include `license`, `compatibility`, `metadata`, `version` is cosmetic.
- **Rules**: add support for `~/.gemini/AGENTS.md` (user-level) as the canonical surface. Treat `~/.gemini/GEMINI.md` as **shared with Gemini CLI** (open conflict #16058); the adapter writes `AGENTS.md` exclusively and reads both. Path-ownership: **Antigravity owns `~/.gemini/GEMINI.md` post-2.0** because Gemini CLI sunsets on 2026-06-18.
- **MCP server**: `SharedKeyedMapLayout(shared_path="~/.gemini/antigravity/mcp_config.json", map_key_path=("mcpServers",))`. Detect symlinks before write and refuse to overwrite without `--force`. Accept the new optional fields `serverUrl`, `authProviderType`, `oauth.scopes` (route to `per_agentic_tool_only` until Google confirms they're general-purpose).
- **Slash commands**: writes go to `~/.gemini/antigravity/skills/<command-name>/SKILL.md` because 2.0 unified slash commands into Skills. The adapter docstring must state this explicitly so it doesn't look like a bug.
- **Workspace path rename**: `<project>/.agent/skills/` → `<project>/.agents/skills/`. Read both, write the plural form. Workspace scope is still out of scope for v0.5 per the project description, but the adapter constants should encode the new path so v0.6 can flip it on without protocol changes.
- **Excludes**: hard-code excludes for `antigravity-backup/`, `antigravity-ide/`, `brain/`, `conversations/`, and `mcp_config.json` symlinks to avoid clobbering migration snapshots and active MCP connections.

### 7.3 Protocol additions — no breaking changes

The v0.5 protocol surface (`rules`, `slash_command`, `mcp_server` customization_types; `RulesFileLayout`, `SlashCommandFileLayout`, `SharedKeyedMapLayout`) absorbs 2.0 without protocol changes. Three additive extensions are recommended:

1. **Optional `mcp_server` canonical fields**: `server_url` (string; distinct from `url`), `auth_provider_type` (enum), `oauth_scopes` (list[str]). Marked nullable so 1.x adapters and non-Google adapters can ignore them.
2. **NFR-15 allowlist**: add `authProviderType` to a "carry verbatim, never redact" allowlist so secret-redaction heuristics don't mask it.
3. **State schema v4 (deferred to v0.6 unless required earlier)**: add `antigravity_version` per-pair to enable refusing to apply 2.0-tagged artefacts to a 1.x install (and vice-versa). Not strictly required for v0.5 because users on the 2026-05-19+ release will all be on 2.0 by the 2026-06-18 cutoff.

The `agent` customization_type (US-13 mentions it indirectly via `supported_customization_types` examples) does **not** need adjustment for 2.0. Antigravity 2.0's dynamic subagent feature exists but its on-disk schema is community-derived (`~/.subagents/` with `manifest.json`) and unconfirmed by Google. **Spike in v0.5; commit to a schema in v0.6.**

### 7.4 Governance edits — `docs/project_description.md`

Three additions are warranted; all qualify as governance edits and must be reviewed before applying.

- **Release-history entry for the 2.0 transition.** Add a bullet noting that v0.5 ships against Antigravity 2.0, that Gemini CLI consumer tiers sunset on 2026-06-18, and that `antigravity.py` expands from `{skill}` to `{skill, rules, mcp_server, slash_command}`.
- **Out-of-scope additions**: brain/scratch/conversation files under `~/.gemini/antigravity/`; Managed Agents (Gemini API); AI Studio cloud agent templates; Gemini Enterprise Agent Platform; scheduled tasks (schema unpublished); plugins (path unconfirmed).
- **Glossary clarification**: distinguish "Antigravity desktop", "Antigravity CLI (`agy`)", and "Gemini CLI" as three sibling agentic_tools. Currently the glossary lists "Google Antigravity" once.

### 7.5 US-13 acceptance criteria — amendments needed

US-13 currently lists nine ACs covering rules/slash_command/mcp_server. Three need amendment or addition for 2.0:

- **AC-3 (`mcp_server` round-trip)**: add a clause about not following symlinks when writing `mcp_config.json` — "the daemon MUST detect that the shared file is a symlink and refuse the write absent `--force`".
- **AC-8 (per-slot archive)**: clarify that for Antigravity's `mcp_config.json`, the archive entry holds the prior slot's serialised JSON fragment under the synthetic filename `<server-name>.json` per the protocol's SharedKeyedMapLayout semantics. No semantic change, just a worked example.
- **New AC-10 (Antigravity-specific excludes)**: "Given an Antigravity 2.0 install with `antigravity-backup/`, `antigravity-ide/`, `brain/`, or `conversations/` present, when the daemon snapshots `~/.gemini/antigravity/`, no artifact from any of those directories is included in the canonical store; one structured warning per detected directory per session is emitted pointing the user at Google's migration guide."

These are within US-13's scope; no new story needed.

### 7.6 Sequencing — what ships before 2026-06-18

The Gemini CLI consumer-tier sunset on **2026-06-18** is the hard deadline. v0.5 PRs must land before then so users migrating off Gemini CLI find functioning Antigravity 2.0 support in `agents_sync`. Recommended order (one PR per row):

| Order | PR | Why this position |
|---|---|---|
| 1 | `feat/v0.5-rules` | Already merged into `feat/v0.5-plan` — review and forward to main |
| 2 | `feat/v0.5-slash-command` | Already merged into `feat/v0.5-plan` — review and forward to main |
| 3 | `feat/v0.5-mcp-server` | In progress (per `docs/v0.5_mcp_server_implementation_plan.md`). Carries the new optional fields (`server_url`, `auth_provider_type`, `oauth_scopes`) and the symlink-refuse logic. |
| 4 | `feat/v0.5-antigravity` (NEW) | Extend `antigravity.py` from `{skill}` to `{skill, rules, mcp_server, slash_command}`. Add the path excludes. Add the workspace `.agents/skills` constant for v0.6 readiness. |
| 5 | `feat/v0.5-gemini-cli` | Branch already exists on origin. Hard-exclude `antigravity*/` subdirs; treat `~/.gemini/GEMINI.md` as shared (defer to `AGENTS.md`). Plan for 2026-06-18 deprecation warning. |
| 6 | `feat/v0.5-cursor` | Branch already exists on origin. No Antigravity overlap. |
| 7 | `feat/v0.5-copilot` | Branch already exists on origin. No Antigravity overlap. |
| 8 | `feat/v0.5-antigravity_cli` (DEFERRED to v0.6) | `~/.gemini/antigravity-cli/` schema is still being shaken out. Spike-only in v0.5; ship in v0.6. |

The umbrella PR #14 (`feat/v0.5-plan` → `main`) should merge **before** the individual adapter PRs forward to main, so the plan/protocol/governance edits land first and the adapter PRs have a stable target.

**Hold v0.5 GA until at least 2026-06-01** to let the 2.0 launch bugs (installer-clobber, BigInt login crash, antigravity-backup stranding) settle. Shipping `agents_sync` v0.5 with "Antigravity 2.0 supported" before those settle traps users on whichever version `agents_sync` happens to snapshot first.

### 7.7 Open items to revisit at v0.5 freeze

These are "no public information yet" as of 2026-05-20. None block v0.5 ship; all should be tracked as v0.6 spikes:

- **Subagent file schema**: `~/.subagents/` with `manifest.json` is community-derived. Google has not published the canonical layout. Defer the `agent` customization_type's Antigravity coverage to v0.6.
- **Plugin manifest filename and root**: 2.0 renamed "extensions" to "Antigravity plugins" but the new manifest path is undocumented. Do not ship plugin sync.
- **Per-server `trust` enum**: 1.x had `trust: bool`; 2.0 may introduce `"signed_only" | "allowlisted" | "explicit"`. No evidence yet; track.
- **Generic third-party OAuth in `mcpServers`**: Google docs as of 2026-04 still say "Antigravity doesn't support the MCP OAuth specifications" for arbitrary servers. Watch for this to land.
- **Antigravity CLI canonical layout for skills**: `~/.gemini/antigravity-cli/skills/` is plausible but unconfirmed.
- **Scheduled tasks**: announced as a 2.0 feature but file path and schema unpublished.
- **Standalone-app hook support**: marketing lists "JSON hooks" for the desktop app; community trackers say "no session, no hooks" on the desktop today. Watch.

### 7.8 Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `mcp_config.json` symlink clobber on snapshot | High (default install state) | High (breaks active MCP) | Hard-coded symlink detection + `--force` gate |
| `antigravity-backup/` picked up as snapshot source | High (Google's own migration writes it) | Medium (canonical store contaminated with stale state) | Hard-coded exclude in `antigravity.py` discovery |
| `~/.gemini/GEMINI.md` double-write between Antigravity and Gemini CLI | Medium (gemini-cli #16058) | Medium (conflict loop) | Path-ownership: Antigravity owns post-2026-06-18; prefer `AGENTS.md` for new rules |
| `.agent/` vs `.agents/` workspace path divergence | Medium (Google didn't auto-migrate) | Low (read-both, write-plural handles it) | Adapter constants encode both; document precedence |
| Antigravity 1.x → 2.0 downgrade during sync window | Low (uncommon user action) | High (workspaces don't open in 1.x) | State schema v4 adds `antigravity_version`; refuse cross-version restore with `--force` escape |
| New first-party MCP servers (Workspace, Cloud Data Kit) leak credentials via sync | Low if NFR-15 secret-redaction is on | Medium | Existing heuristics cover; allowlist `authProviderType` from masking |
| Antigravity 2.0 launch bugs stranding user data | Confirmed (24h post-launch) | High | Hold `agents_sync` v0.5 GA until 2026-06-01 |
| Schema-TBD items (subagents, plugins) regressing later | Medium | Low if deferred | Defer to v0.6; document as RFC items |

### 7.9 Bottom line

`agents_sync` v0.5 needs **one new adapter (`antigravity.py` extension)** and **three additive protocol fields on `mcp_server`** to cover Antigravity 2.0 cleanly. No protocol-breaking changes. No new customization_types beyond what v0.5 already plans. The `gemini_cli.py` adapter ships as planned with documented sunset semantics. `antigravity_cli.py` defers to v0.6 with a spike in v0.5. The 2026-06-18 Gemini CLI sunset is the deadline; the 2026-06-01 v0.5 GA target leaves a 17-day buffer for users to migrate.
