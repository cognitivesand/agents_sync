# agents_sync — Implementation Plan (thin clean architecture)

- **Status:** plan (for execution). Builds the design in
  `docs/architecture_simplification_proposal.md` (rev 4) in small, independently
  testable steps.
- **Date:** 2026-06-05
- **Governing artifacts:** `docs/project_requirements.md`, `docs/stories/US-*.md`,
  `docs/project_description.md`, and the proposal above. Each step traces to them.

> Every step is small, shippable, and reversible, and passes the **per-step gate**
> below before the next begins. No step is "done" until it is *spotless*.

---

## Progress (current state)

- **Branch:** `fix/size-explosion-hardening` · **Version:** `0.7.48` (each rebuild step is a
  PATCH `feat(rebuild)`; nothing user-visible ships until cutover S24–S25).
- **Phase A — domain core:** S1–S4 ✓ (shipped through 0.7.15).
- **Phase B — planner:** S5, S6a–S6c, S7, S8a–S8d ✓ (shipped through 0.7.15).
- **Phase C — translation:** S9 ✓ (0.7.16) · S10 ✓ (0.7.17) · S11a ✓ (0.7.18) · S11b ✓ (0.7.19)
  · S12 ✓ (0.7.20) · S13a ✓ (0.7.21) · S13b ✓ (0.7.22) · **S13c ✓ (0.7.23 hardening,
  0.7.24 http/sse)** — Phase C complete.
- **Phase D — gateways:** S14 ✓ (0.7.25) · S15 ✓ (0.7.26, 0.7.27) · **S16 ✓ (0.7.28
  artifact_archive)** — Phase D complete.
- **Phase E:** S17 ✓ (0.7.29 read_tool_surfaces + rules_import_resolution) · **S18 ✓
  (0.7.30 secret_policy — headers detection now matches NFR-15's any-literal text)**.
- **Phase E complete:** S17 · S18 · **S19 ✓ (0.7.31 content family, 0.7.32 identity
  family — all 11 intents executable; executor is a package)**.
- **Phase F:** S20 increment 1 ✓ (0.7.33 — tools-as-data core); increment 2 ✓ (0.7.34 —
  per-tool agent field maps); increment 3 ✓ (0.7.35 — opencode mcp dialect via `McpSpellingRecipe`,
  data-driven); mcp render `per_tool_extra` deep-thaw fix ✓ (0.7.36 — foreign nested objects);
  increment 4 ✓ (0.7.37 — claude/cursor/copilot mcp render-field spellings: transport field
  `type`, claude/copilot auth `oauth`, pure data); increment 5 ✓ (0.7.38 — codex mcp carriers:
  `http_headers`/`env_http_headers`/`bearer_token_env_var` fold onto canonical `headers` via NEW
  `McpSpellingRecipe` knobs, fixed canonical `${env:NAME}` representation; no carrier strands in
  `per_tool_extra`); increment 6 ✓ (0.7.39 — transport-field-less tools: gemini url/transport
  inference (`httpUrl`↔http, `url`↔sse) + gemini/codex transport- and name-field suppression via
  NEW knobs `transport_by_url_field`/`url_field_by_transport`, optional `transport_render_field`/
  `name_render_field`; closes the increment-5 codex `per_tool_only` transport drift); increment 7
  ✓ (0.7.40 — per-tool inline env-reference *style*: NEW `env_reference_style` (prefix, suffix)
  knob; parse canonicalizes any form (`${NAME}`/`{env:NAME}`/`${env:NAME}`) → `${env:NAME}` for
  stable digests, render restyles to the tool's native form (claude/gemini `${NAME}`, opencode
  `{env:NAME}`, others canonical) across env/auth/headers). **S20 complete.**
- **S20 audit done:** the batched end-of-S20 two-auditor `/code_and_tests_quality_review` ran and
  was remediated → 0.7.41. **S21 in progress** (Runtime config), split into sub-increments because
  the per-tool-default-paths design (user choice: tools-as-data) spans two concerns: **S21a**
  (default-location DATA on each surface recipe — 0.7.42) ✓ and **S21b** (`runtime_config`:
  resolve anchors → paths, load/validate TOML fail-closed, distinct exit codes 0/1/2 — 0.7.43) ✓.
  **S21 COMPLETE.** End-of-S21 two-auditor `/code_and_tests_quality_review` ran (all AUDIT_PASS; 9
  WARNING/INFO findings, 0 CRITICAL/MAJOR) and was remediated → 0.7.44 (`assert_never` exhaustive
  anchor dispatch; `_load_config_file` requires the `[agents-sync]` table; +test/docstring hardening;
  4 findings accepted-as-is).
- **S22 in progress** (Daemon + CLI). **Sequencing (user decision — "build runnable daemon now"):**
  S22a/S22b/S22c build a runnable daemon; export/import land in S23 (with `portable_library`);
  `parser_bounds` + pointing the conformance suite at the new pipeline stay at S24 (the cutover).
  - **S22a** (`poll_daemon.watch` — the poll loop: systemic-only failure budget FR-02, low-freq GC
    tick NFR-07/08, clean SIGINT/SIGTERM shutdown US-07 AC-2/AC-3, transition-only logging
    NFR-12/13, exit codes NFR-10; `sync_once`/`run_gc` are injected callables) — 0.7.45 ✓.
  - **S22b** (`sync_once` — one poll's read→plan→execute orchestration + `count_available_tools`
    [new-model: a tool is available when ≥1 resolved root exists; S24 conformance validates] +
    `make_periodic_poll` [threads state + digest cache across polls, NFR-08]) — 0.7.46 ✓.
    `sync_once` is its own module (poll_daemon stays loop-only — SRP).
  - **S22c** (`command_line_interface` + `__main__` — `run` (→ `watch(make_periodic_poll(config))`)
    + `prune` (→ `prune_archive`), argparse, exit-code matrix config→2/runtime→1/normal→0;
    `home`/`env`/`run_daemon` injectable for testability; export/import deferred to S23) — 0.7.47 ✓.
  **S22 COMPLETE.** End-of-S22 two-auditor `/code_and_tests_quality_review` ran (14 findings, 1 MAJOR
  / 9 WARNING / 4 INFO, 0 CRITICAL) and was remediated → 0.7.48: the MAJOR — the SIGINT/SIGTERM
  shutdown path (US-07 AC-2) was untested — is closed with a parametrized signal-delivery test; GC
  cadence now advances by the interval (NFR-08); `tool_definitions` default collapsed to one home;
  +3 test-assertion strengthenings; 5 findings accepted-as-is. Next plan step: **S23 — Portable
  library** (`portable_library`: export; import preview-then-write + `--force`; last-modified-wins /
  cross-identity retire — US-12, FR-12/15), which also wires the CLI's export/import subcommands.
  **Tracked gap / later cleanup:** gemini's `oauth`
  auth-field spelling — an increment-4-style auth knob gemini still lacks (renders auth under
  `auth`, not `oauth`).
- **Audit cadence:** the end-of-S20 two-auditor audit runs once, after the final S20
  sub-increment (before S21) — not between sub-increments. Each sub-increment still gets docs,
  red-first tests, full CI, and its own commit/`/bcp`.
- **Phases D–G (S14–S25):** not started.
- **Deferred, tracked here so they are not lost:** size-explosion hardening (`parser_bounds`) →
  S24 gate; mcp `@import` resolution + framework egress-guard *enforcement* → read phase S17–S19;
  mcp secret policy → S18; per-tool field-spelling overrides (incl. opencode `enabled` inversion)
  + codex `env_http_headers`/`bearer_token_env_var` carriers → S20 (carriers ✓ increment 5); the
  per-tool inline `env_reference_style` (the `${env:NAME}`↔`${NAME}`↔`{env:NAME}` *style*
  conversion) → S20 increment 7; `CanonicalDocument.from_dict` type-coercion hardening
  (it silently coerces e.g. `tools: "abc"` / `timeout: "x"` instead of raising into the store's
  quarantine catch — S15 audit note) → revisit when the schema next grows (S20); S19 audit
  watch-items for **S20**: (a) verify the planner prunes a vanished tool's recorded surface
  after a rename (else the record keeps a stale old-slug entry under the new name), (b) when
  tools-as-data can make two targets share one render file, either chain prior_text through
  same-file targets or keep relying on the executor's loud duplicate-render-file guard
  (project has it; give rename/remove siblings if reachable). Each rebuild
  step also writes a markdown report under `docs/audits/` (untracked).

---

## The per-step gate

Every step is executed through the **`incremental_step` skill**, which defines the
fixed gate (its single source of truth):

> detail the step → update docs → write/adjust tests then **`/audit-tests`** (the
> only point tests may change) → code → run the full tests → **`/code_and_tests_quality_review`**
> on the modified files against three targets (1 spec compliance, 2 clean code:
> POLA/DRY/KISS/YAGNI/SRP/SoC, no antipatterns, 3 efficiency/sparsity/no bloat) →
> **spotless** gate (max **3** audit→fix loops, else stop and escalate) →
> commit + **`/bcp`**.

Order is fixed; tests change only at the `/audit-tests` substep; a step ships
independently and is "done" only when spotless. See the skill for the full rules.

---

## Build location: a parallel tree (`src_new/` + `tests_new/`)

The greenfield build lives in **`src_new/`** (package name unchanged: `agents_sync`),
with its unit tests in **`tests_new/`**. The existing `src/agents_sync/` keeps
running untouched, so the conformance suite stays green throughout. Isolation:
the default `pytest` run is pinned to `tests/` (`testpaths`), and `tests_new/` runs
as its own stage whose `conftest.py` puts `src_new/` first on `sys.path` (the
editable install is a plain `.pth`, so this wins cleanly). `scripts/ci.sh` runs
both scopes plus `mypy --strict` over `src_new/`.

**Cutover (S24–S25) is a directory rename**, not a code rename: delete the old
`src/agents_sync/`, move `src_new/agents_sync/` → `src/agents_sync/`, fold
`tests_new/` into `tests/`. Because the package name never changes, no internal
import is rewritten (honouring the no-bulk-rename rule).

## Safety net: the conformance suite

The existing behavioural tests (`test_e2e_sync`, `test_round_trip`,
`test_cross_adapter_adoption_matrix`, `test_antigravity_three_way`,
`test_first_boot_reconciliation`, the per-tool `test_*_io`, the size-explosion
regressions, …) are the **conformance suite**. They encode the user-visible
behaviour and must stay green through every step and across the cutover. New
per-step unit tests are additive; the conformance suite is the invariant.

---

## Build order (dependency-first; each row is one gated step)

The new modules are built and unit-tested in isolation (pure core → translation →
gateways → read/execute → tools/drivers), then the daemon is cut over to them and
the superseded modules retired. The conformance suite holds throughout.

### Phase A — Pure domain core (no I/O)
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S1 | Canonical document | `domain_model/canonical_document` | schema, normalise (idempotent), content-digest excludes metadata (FR-14), dict round-trip |
| S2 | Artifact identity | `domain_model/artifact_identity` | `mint_artifact_id` is the sole minter; `validate_artifact_id` (UUIDv4); single-caller static guard |
| S3a | Artifact naming & candidate key | `domain_model/artifact_naming` | slug rule (Windows-reserved guard) + `candidate_key` (kind+slug); the identity grouping for id-less candidates (US-03) |
| S3b | Tool surface & format (minimal) | `domain_model/tool_surface` | `KeyedMapSlot`, `ToolSurface` (tool, kind, location, surface_format), minimal `SurfaceFormat` (dialect) — immutable hashable value objects the planner consumes. The recipe fields (known/tool-only fields, reserved names, filename precedence) grow with their consumers in S9 (translation) / S17 (read phase), per YAGNI |
| S4 | Sync plan vocabulary | `domain_model/sync_plan` | closed `IntentKind` vocabulary (the 11 intents the planner S5–S8 emits and the executor S19 performs, named per proposal §6) + immutable `SyncResult` (changed / failed / blocked / frozen / diagnosed); value semantics. The per-intent payload dataclasses grow with their emitter in S5–S8 (planner) / S19 (executor), per YAGNI — same call as S3b |

### Phase B — The planner (pure, the brain)
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S5 | Recover identity | `plan/recover_identity` (+ minimal `observation`, `sync_state` inputs) | managed vs candidate; recover by well-formed embedded id (precedence) then recorded location ownership; never mint (FR-11). Introduces the minimal `SurfaceObservation` (tool_surface + embedded_id) and `SyncState`/`ArtifactRecord` (recorded surface locations) that this step reads; their other fields (digest, mtime, parsed canonical) grow with their consumers in S6–S8 / S17, per YAGNI |
| S6a | Reconcile known — content rule + freeze | `plan/reconcile_known` (+ grows `observation`, `sync_state`, `sync_plan` intents) | the **unified content rule**: freeze if the artifact won't parse (FR-11); else digest-detect the changed surfaces, absorb the freshest (highest `modified_time`, alphabetical tiebreak — US-06 AC-4) and project the canonical onto the other surfaces; else unchanged (US-01). Grows `SurfaceObservation` (+content_digest/modified_time/parsed+`ParseFailure`), `ArtifactRecord.surfaces` (→`RecordedSurface` location+digest), and `sync_plan` (the `FreezeArtifact`/`AbsorbToolEdit`/`ProjectToTools` payloads). Extend-to-newly-available and the tied-mtime WARN are deferred (registry → S8/S20; logging → S22) |
| S6b | Reconcile known — surface-shape (rename + remove) | `plan/reconcile_known` (+ grows `sync_state`, `sync_plan`) | the per-artifact shape diff: canonical slug ≠ recorded slug → `rename_artifact` (US-04, replaces the projection); a recorded tool with no observation this poll → `remove_artifact`, short-circuiting content (US-11). `mv` needs no intent (a moved tool still has an observation → not a vanish; recompute records the new location). Grows `ArtifactRecord` (+recorded `name` for slug compare) and `sync_plan` (`RenameArtifact`/`RemoveArtifact`). The cross-artifact downgrades — `reject_collision` (slug clash) and glitch → `reproject_canonical` — are deferred to S8 |
| S6c | Reconcile known — canonical authority | `plan/reconcile_known` (+ grows `sync_state`, `sync_plan`, `canonical_document`) | the stored canonical (read-phase input) is corrupt → `rebuild_corrupt_canonical`; or it changed out of band (its digest moved with no surface change → an import) → `reproject_canonical` (US-09). Adds the `stored_canonical: CanonicalDocument \| CorruptCanonical \| None` input (None until S8 wires it), the `CorruptCanonical` marker (parallels `ParseFailure`), `ArtifactRecord.canonical_digest`, and the `ReprojectCanonical`/`RebuildCorruptCanonical` payloads. Pipeline: freeze → rebuild → remove → content → reproject |
| S7 | Adopt candidates | `plan/adopt_candidates` (+ `plan/winner_selection`, grows `sync_plan`) | the per-candidate-local fates: group the parsed id-less candidates by (kind,slug) → `adopt_new_artifact` (winner by the shared mtime tiebreak, US-03 AC-7); each unparseable candidate (no slug to group by) → `report_unadoptable` (US-03, never minted). Extracts the shared `freshest` winner-selection (US-06 AC-4 / US-03 AC-7) into `plan/winner_selection`, reused by `reconcile_known`. Grows `sync_plan` (`AdoptNewArtifact`/`ReportUnadoptable`). The managed-match → `absorb_into_managed` downgrade is cross-artifact (S8); cross-identity retire is import (S23) |
| S8a | compute_sync_plan — assembly + two-tool guard | `plan/compute_sync_plan` (+ `sync_plan` `SyncPlan` container) | whole-plan assembly: `recover_identity` → `reconcile_known` per managed artifact (threading each `stored_canonical`) → `adopt_candidates`, collected into the new `SyncPlan` container. Plus the **two-tool guard** (the simplest, most global downgrade): fewer than two available tools → drop every destructive intent (`adopt_new_artifact`, `absorb_into_managed`, `project_to_tools`, `rename_artifact`, `remove_artifact`) (US-07 AC-5). Adds the `available_tool_count` input. Pure, no FS. The key-conflict and glitch downgrades are S8b/S8c |
| S8b | compute_sync_plan — collision guard | `plan/compute_sync_plan` (+ `sync_plan` `RejectCollision`) | the whole-poll **managed-key index**: each managed artifact's *effective* `(kind, slug)` — kind from its observations, name from `record.name` with any pending `rename_artifact` new name applied. A key shared by ≥2 managed ids → drop all their intents and emit `reject_collision` (untouched, structured error naming the colliding ids + slug). One mechanism covers both US-03 AC-8 (two managed already at one key) and US-04 AC-5 (a rename *creating* the clash). Adds the `RejectCollision` payload. Pure, no FS |
| S8c | compute_sync_plan — absorb-into-managed guard | `plan/compute_sync_plan` (+ `sync_plan` `AbsorbIntoManaged`) | reuses S8b's managed-key index (after rejection, so only *non-colliding* keys remain): an `adopt_new_artifact` whose candidate group's `(kind, slug)` matches a managed key → `absorb_into_managed` instead (managed wins, no mint — US-03 AC-6). Adds the `AbsorbIntoManaged` payload and adds `ABSORB_INTO_MANAGED` to the two-tool destructive set. Pure, no FS |
| S8d | compute_sync_plan — glitch guard | `plan/compute_sync_plan` | the per-tool whole-poll vanish count: a `remove_artifact` on a tool that suffered a *glitch* — ≥2 of its recorded artifacts vanished this poll → `reproject_canonical` instead (restore from canonical, no removal propagated — US-11 AC-9); exactly one vanished recorded artifact stays a deliberate deletion. Redirects existing intents (no new payload). Pure, no FS. (Framework-specific projection hold-back is US-15, at S12 with its read-phase flag; the `private` flag was retired — amendment 019.) |

### Phase C — Translation (centralized; dialects are the only wire-format code)
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S9 | Translation core + markdown dialect | `translation`, `dialects/markdown_frontmatter` | `file_to_canonical`/`canonical_to_file`/`extract_artifact_id` (each takes the whole `ToolSurface` — the seam keys per-tool bags and stamps `kind`); round-trip, no-foreign-leak (NFR-06/16), malformed→raise, id-in-isolation. **Size-explosion hardening is out of scope here** (own concern → `parser_bounds`, §13); see the S24 gate |
| S10 | Keyed-map dialect | `dialects/keyed_map_slot`, `dialects/field_mapping` | one slot in a shared file (mcp); round-trip, sibling preservation, no-foreign-leak, id-in-isolation. Extracts the shared recipe-application (`field_mapping`) that `markdown_frontmatter` and `keyed_map_slot` both use. `SurfaceFormat` grows `map_key_path` + `file_format`. **JSON format only**; TOML (codex mcp) + JSONC land with the structured-text codec at S11 (an unimplemented format fails loud) |
| S11a | Structured-text codec + keyed-map wiring | `dialects/structured_text`, `dialects/keyed_map_slot` | the shared `json`+`toml` codec (`deserialize`/`serialize`): key-order + data round-trip, **comments not preserved**, stdlib only (`tomllib` read + hand-rolled TOML writer; no new dependency). `keyed_map_slot` switches to it, removing the S10 toml fail-loud stub — **unblocks codex mcp (toml)**. JSONC deferred (no tool declares it; a correct comment strip must be string-aware) |
| S11b | Structured-text whole-file dialect | `dialects/structured_text` | the whole-file `parse`/`render`/`extract_id` for a structured-text artifact (codex's whole-`.toml` agent), using the S11a codec + `field_mapping` with body-field handling |
| S12 | Framework-specificity predicate | `dialects/global_rules` | the pure `detect_framework_specific` text-scan + tool-private-path token constant the egress guard consumes (US-15 detection). Whole-file global rules **fold via `markdown_frontmatter`** (no new dialect code — rules differ only by recipe data). `@import` resolution (FS I/O), the source/effective body split, and the egress-guard *enforcement* (US-15 AC-1/2/3/4/6/7) land in the **read phase (S17–S19)**, where the I/O and the planner live |
| S13a | MCP dialect — stdio core + canonical schema | `domain_model/canonical_document`, `dialects/mcp_server` | grow `CanonicalDocument` with flat optional mcp_server fields (`transport`, `command`, `args`, `env`, `cwd`, `timeout`, `disabled`, `always_allow`) — same pattern as the existing agent-only `model`/`effort`/`tools` optionals; the stdio dialect over a keyed-map slot: transport canonicalization + alias map (`local`→`stdio`, `streamableHttp`→`streamable-http`, validated against the canonical set), transport inference (command→stdio), command/args (array-form split), env (verbatim), cwd/timeout, disabled, always_allow, per-tool spelling preservation, unknown→`per_tool_extra`. Default alias lists are module constants (per-tool overrides deferred to tools-as-data S20 — incl. opencode's inverted-polarity `enabled` spelling, which round-trips verbatim via `per_tool_extra` until then). http/sse fails loud (S13c). FR-09 |
| S13b | MCP dialect — package split | `dialects/mcp_server` (→ package) | behavior-preserving refactor: split the stdio dialect module into a `mcp_server/` package (`parse` / `render` / shared vocabulary `_shared`) to respect the 300-line limit and set up http. **No new behaviour** — the unchanged S13a tests are the proof the refactor preserved behaviour. FR-09 |
| S13c | MCP dialect — stdio hardening, then http/sse transport | `dialects/mcp_server`, `domain_model/canonical_document` | two gated increments. **(1) stdio hardening** — the S13b-audit P1s: non-int `timeout` (incl. bool), non-string `env` values, and non-string `cwd`/`command`/`args`/`always_allow` items are malformed content → `MalformedSurfaceError` (the locked S13a schema declares the types; fail loud per §8, no silent `str()` reprs); array-form `command` records its spelling in `per_tool_only` and renders back as an array. **(2) http/sse** — `url`/`headers`/`auth` flat canonical fields + url alias detection (`url`/`httpUrl`/`serverUrl`), inline `headers` + `auth` maps (**verbatim**, like S13a's stdio env), per-tool url/auth spelling preservation (`auth`/`oauth` aliases; `headers` has a single default spelling, so no alias machinery until S20 per-tool overrides). FR-09 |
| — | MCP env-reference conversion + carriers | `tools/*` recipes (S20) | env-reference SYNTAX conversion (`${env:NAME}`↔`${NAME}`↔`{env:NAME}`), the per-tool `env_reference_style`, and the dedicated `env_http_headers`/`bearer_token_env_var` carriers are **per-tool recipe data** → land with tools-as-data at **S20** (converting env-refs without per-tool render styles would break round-trip). Until then env/headers/auth round-trip verbatim |
| — | MCP secret policy (refuse/warn/redact) | `secret_policy` (read phase) | NOT in the dialect — enforcement runs at the planner/executor egress (proposal §12), landing at **S18** alongside the other secret/egress guards |

### Phase D — Gateways (the only filesystem touch points)
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S14 | Atomic file writer | `atomic_file_writer` | temp+rename, staged folder swap (NFR-03 atomic visibility), OS-quirk retry, no lock |
| S15 | Canonical & state stores | `canonical_store`, `sync_state_store` | round-trip; corrupt → quarantine (US-09 AC-4); schema/versioning |
| S16 | Archive + GC | `artifact_archive` | archive-before-write (NFR-01); tiered retention GC tier-boundaries (NFR-07); unparseable-safe |

### Phase E — Read phase, secrets, executor
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S17 | Read tool surfaces | `read_tool_surfaces` | two increments. **(1) core** — declarative surface specs (directory / keyed-map / FR-10 rules-precedence; populated by tools-as-data at S20) → `SurfaceObservation`s: raw-text digest, mtime, isolation-extracted id, parse with `MalformedSurfaceError`→`ParseFailure` (recipe errors stay loud); re-parse only changed via a previous-observations map (same digest → reuse prior parsed; the daemon owns the cache, S22); a malformed keyed-map file yields `ParseFailure` for its previously-known slots (freeze, never removal). **(2)** `@import` resolution + source/effective body split (the S12 deferral). Write-target inspection → its consumer (S19/S20); directory-tree (skill-folder) surfaces → their dialect at S20 |
| S18 | Secret policy | `secret_policy` | detection heuristics + egress enforcement at adopt/render/export/import (NFR-15); refuse vs accept-warn |
| S19 | Execute sync plan | `execute_sync_plan` | two increments. **(1) content family** — freeze/report/reject (result-only: frozen/diagnosed), absorb_tool_edit (secret egress at absorb → `blocked`), project_to_tools/reproject_canonical (render egress; per-artifact transaction: archive ALL first, write only if all archives landed — US-06 AC-6; identical renders skipped, NFR-05), rebuild_corrupt_canonical (freshest parsed observation); `read_tool_surfaces` exposes `surface_content_digest` so recorded digests match the next poll's observations (no churn). Render targets resolve through this poll's observations (records carry no `surface_format`); rules-surface projection (composite import digest) → S20 with the rules recipes. **(2) identity family** — adopt_new_artifact (the SOLE mint + id injection + pre-injection archive), absorb_into_managed, rename_artifact, remove_artifact (+ the S16-deferred `archive_canonical`) |

### Phase F — Tools as data, drivers, library
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S20 | Tool definitions + registry | `tools/*`, `tools/agentic_tools_registry` | increments. **(1) data core** — `ToolDefinition` + per-kind surface recipes (config key + layout + `SurfaceFormat`, no callables) for all 7 tools over the kinds today's dialects support (agent / slash_command / rules / mcp_server; codex agents + gemini commands are whole-file TOML; antigravity registers empty until the skill dialect); `surface_specs_for` skips unresolved config keys (US-11); cross-adapter agent matrix + per-tool mcp round-trips through the REAL dialects (NFR-11/18). **(2) per-tool agent field maps** ✓ — model/effort/tools (+ claude `disallowedTools`/`permissionMode`, codex `model_reasoning_effort`) fold onto existing canonical attrs as additive `known_fields` data, zero dialect change; opencode model/tools *transforms* (provider-split, tools→permission) and gemini private `tools` deferred. **(3) opencode mcp dialect (data-driven)** ✓ — a per-tool `McpSpellingRecipe` (data in the tool module, NO dialect tool-branches): opencode `environment` (env), inverted `enabled` (disabled), `array` command, `type` + `local`/`remote` transport values, `oauth` auth; the `_shared.py` module constants become defaults. (Plus the mcp render `per_tool_extra` deep-thaw fix.) **(4) mcp render-field spellings, simple tools** ✓ — claude/cursor/copilot transport field `type` + claude/copilot `oauth` auth, pure `McpSpellingRecipe` data, zero dialect change. **(5) codex mcp carriers** ✓ — codex's HTTP auth carriers fold onto the canonical `headers` map via NEW `McpSpellingRecipe` knobs (`headers_render_field`, `env_http_headers_field`, `bearer_token_env_var_field`, optional `auth_render_field`): `http_headers` is codex's `headers` spelling; an `env_http_headers` entry (`X`→`TOK`) and a `bearer_token_env_var` (`TOK`) fold to `headers[X]="${env:TOK}"` / `headers.Authorization="Bearer ${env:TOK}"` and split back out on render (literals stay in `http_headers`); codex has no generic auth block (`auth_render_field=None`). Uses the FIXED canonical `${env:NAME}` representation — the per-tool inline *style* is increment 7. No carrier strands in `per_tool_extra`. **(6) gemini mcp url/transport inference** ✓ — transport-field-less tools, data-driven: gemini infers transport from the url-field spelling (`httpUrl`→http, `url`→sse via `transport_by_url_field`) and renders it back (`url_field_by_transport`); gemini + codex suppress the transport field and inner name (`transport_render_field`/`name_render_field` = `None`). Closes the increment-5 codex transport `per_tool_only` drift. gemini's `oauth` auth spelling deferred (an increment-4-style knob). **(7) env-reference syntax conversion** ✓ — the per-tool `env_reference_style` (a `(prefix, suffix)` data knob, no tool-name branch): parse canonicalizes any recognized form (`${NAME}`/`{env:NAME}`/`${env:NAME}`) to `${env:NAME}` so digests are stable; render restyles `${env:NAME}` to the tool's native inline form (claude/gemini `${NAME}`, opencode `{env:NAME}`, cursor/codex/copilot canonical) across env/auth/headers values. **(later)** the skill (directory-tree) dialect + antigravity recipes, reserved names, `from_dict` hardening, the S19 watch-items |
| S21 | Runtime config | `runtime_config` | load/validate/platform paths; fail-closed config errors + distinct exit code (NFR-10, US-07 AC-7) |
| S22 | Daemon + CLI | `poll_daemon`, `command_line_interface` | systemic-only failure budget (FR-02), GC tick, latency (NFR-02); export/import/run; exit-code matrix (NFR-10) |
| S23 | Portable library | `portable_library` | export; import preview-then-write + `--force`; last-modified-wins / cross-identity retire (US-12, FR-12/15) |

### Phase G — Cutover & retirement
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S24 | Cut the daemon over | `poll_daemon` `sync_once` = read → plan → execute | the **full conformance suite** stays green against the new pipeline. **Gate:** `parser_bounds` size-explosion hardening (deferred from S9 — bounded YAML composer, front-matter scan window, text-size cap) MUST be in place; the size-explosion regression tests in the conformance suite enforce it |
| S25 | Retire superseded modules | delete old discovery/adoption/sync/etc. | full suite green; measure LOC vs target (~6–7k); architecture.md reflects the final map |

Steps may be split further if any one cannot pass the gate as a single increment;
they may not be merged (each must remain independently shippable).

---

## Definitions

- **Spotless** = full CI green + `/audit-tests` clean on the step's tests +
  `/code_and_tests_quality_review` clean on all three targets for the step's
  modified files, with zero outstanding findings.
- **Audit→fix loop** = one (review → remediate) cycle. Max 3 per step; on the
  third still-not-spotless, stop and escalate rather than proceed or weaken a
  test/criterion.
- **Cutover discipline:** the conformance suite is never red at a step boundary;
  a step that would leave it red is not done.

---

## Relationship to prior work

This plan supersedes the earlier phased plan (`elegant-bubbling-token`). The
602c6d remediation and the dedup/simplification already on
`fix/size-explosion-hardening` realise pieces of the target (single mint site,
archive GC, daemon failure policy, collapsed dead fields); where a step's outcome
already exists and is spotless, the step's gate is satisfied by verifying it, not
rebuilding it.
