# Restart — 2026-06-15

> Last updated by Claude at 2026-06-15T11:22:57+02:00. Session-handoff snapshot. A fresh
> session reading this should be able to resume without further explanation.

## 0. Git pin (do not edit by hand)

- `head_sha`: 463dfba08c87aebc2cab1f8b318ba9959f4e140c
- `head_short`: 463dfba
- `branch`: fix/size-explosion-hardening
- `dirty`: true (untracked `docs/audits/**` ONLY — deliberately never staged)
- `dirty_summary`: clean apart from untracked `docs/audits/` artifacts
- `remote_head`: 463dfba (pushed, up to date)
- `saved_at`: 2026-06-15T11:22:57+02:00

The working tree carries no in-progress code edits. Every shipped step was committed +
pushed. The only untracked paths are `docs/audits/*.md` + `.last_code_review.json` +
`raw_audits_results/` — these are review artifacts that are **intentionally never tracked**
(every `/bcp` excludes them); do not stage them.

## 1. Read these first

Order matters:
- `AGENTS.md` (via `~/.claude/CLAUDE.md`) — global rules (POLA/KISS/YAGNI/DRY/SRP/SoC; §3 size
  ≤40 lines/fn, ≤300/file; §7 tests; §8 fail-fast; §11 commits; §13 bash discipline).
- `docs/architecture_implementation_plan.md` — **the active plan**, with a self-sufficient
  **Progress section** at the top: Phases A+B+C+D+E ✓; **Phase F (S20) in progress** — S20
  increment 1 done; increment 2 next.
- `docs/architecture_simplification_proposal.md` — rev 4 target design. §6 intents, §8 executor,
  §9 gateways, §10 translation seam, §12 cross-cutting homes, §13 module map.
- `docs/project_description.md`, `docs/project_requirements.md` (FR-09 mcp, FR-10 rules
  precedence, FR-11 freeze, FR-14 digest, FR-15 state; NFR-01 preserve, NFR-03 atomic, NFR-05
  no-churn, NFR-07 bounded archive, NFR-11/18 extensibility, NFR-15 secrets), `docs/stories/US-*.md`.
- The `incremental_step` skill (`~/.claude/skills/incremental_step/SKILL.md`) — the per-step gate.

## 2. Working context (deltas not in the docs)

- **Execution rhythm:** one gated step per `/incremental_step`; user drives with "continue" /
  "next SXX". The gate: detail (surface genuine decisions) → docs → tests + `/audit-tests`
  (only point tests change) → code → full CI (`bash scripts/ci.sh`) →
  `/code_and_tests_quality_review` (hand-orchestrate **code-quality-auditor** +
  **test-quality-auditor** in parallel; 3 targets: spec / clean-code / efficiency) → spotless
  (≤3 loops, else escalate) → markdown report `docs/audits/code_audit_<ts>.md` + update
  `.last_code_review.json` (NEVER stage `docs/audits/`) → `/bcp`.
- **AUDIT CADENCE (set by the user this session, memory [[feedback_audit_cadence]]):** the full
  two-auditor review runs **once per step NUMBER**, after ALL its sub-letter increments (e.g.
  after all of S20x, before S21) — NOT between each sub-increment. Sub-increments still get docs,
  red-first tests, full CI, and their own commit/`/bcp`; only the heavy audit is deferred to the
  numbered-step boundary. This halves auditor token spend.
- **Greenfield-parallel:** new code in `src_new/agents_sync/`, tests in `tests_new/`
  (`uv run pytest -c pytest_new.ini`). Old `src/` is **reference only, never modified**.
  Conformance suite (`tests/`, 579) stays green every step. Rebuild suite now **519 green**.
- **Versioning:** each rebuild step is a **PATCH** `feat(rebuild)` (nothing user-visible ships
  until cutover S24–S25). Now at **0.7.33**. Always `uv lock` + stage `uv.lock`
  ([[project_uvlock_version_bump]]).
- **Zero mocks in rebuild tests:** real FS via `tmp_path`; fault injection ONLY at the
  `os`/`shutil` boundary (monkeypatch `os.replace`/`os.write`/`os.fsync`/`shutil.copy2`);
  reuse-of-prior-parse is proven with a **sentinel canonical** a fresh parse could never produce,
  never a spy. The test auditor runs **empirical mutation testing** — it has caught real surviving
  mutations (S17 slot-digest, S19 ×3); take its coverage-gap findings seriously.
- **Architecture invariants (load-bearing, tested):** `translation.py` is the ONLY dialect seam
  (parse/render/extract_id + S19's remove_surface_content/surface_fragment_text); the executor
  imports ZERO dialects. `MalformedSurfaceError(ValueError)` = malformed CONTENT (read phase →
  `ParseFailure` → freeze); plain `ValueError` = recipe/config error (fail loud). The new
  `IntentAbortError(RuntimeError)` (S19) = plan-vs-state inconsistency → `failed`, converges next
  poll. `CanonicalDocument` is a frozen fixed-schema dataclass; schema grows by flat optional
  fields. `mint_artifact_id` has exactly ONE call site (executor adopt). Digest recipes in
  `read_tool_surfaces.surface_content_digest` must match what the read phase observes (no churn,
  NFR-05) — the executor records via that function.

## 3. Active task

### 3.1 Goal

Rebuild `agents_sync` as the thin, clean, spec-compliant architecture in the proposal, in small
independently-shippable gated steps, then cut over from the old `src/`.

### 3.2 Constraints

- Hard: conformance suite (579) green every step; full `incremental_step` gate to spotless;
  governance artifacts (description/stories/AC/requirements) change only with explicit user
  approval of exact text ([[feedback_governance_approval]]); removing/deferring behaviour updates
  the spec in the same change ([[feedback_spec_code_alignment]]); no bulk renames
  ([[feedback_renames]]); ≤40 lines/fn, ≤300/file (split into a package when a module would
  exceed it — done for mcp_server S13b and execute_sync_plan S19).
- Soft: greenfield-parallel; PATCH `feat(rebuild)` bumps; additive YAGNI growth; surface genuine
  scope decisions at the detail step; audit once per step number (§2).

### 3.3 Status — what is done

**Phases A–E ✓ complete. Phase F (S20) in progress.** All shipped + pushed:
- **S13b** ✓ 0.7.22 — mcp_server package split.
- **S13c** ✓ 0.7.23 (stdio boundary hardening) + 0.7.24 (http/sse transport) — **Phase C done**.
- **S14** ✓ 0.7.25 — `atomic_file_writer` gateway (NFR-03; write/move/dir-swap, transient retry).
- **S15** ✓ 0.7.26 (`canonical_store`) + 0.7.27 (`sync_state_store` + shared `store_quarantine`).
- **S16** ✓ 0.7.28 — `artifact_archive` (archive-before-write + tiered GC) — **Phase D done**.
- **S17** ✓ 0.7.29 — `read_tool_surfaces` + `rules_import_resolution` (read phase, FR-10/FR-11,
  @import US-15) — **Phase E begins**.
- **S18** ✓ 0.7.30 — `secret_policy` (NFR-15 detection + egress enforcement).
- **S19** ✓ 0.7.31 (content family) + 0.7.32 (identity family — sole mint, rename/remove
  two-phase) — **Phase E done**; executor is a package `execute_sync_plan/`.
- **S20 increment 1** ✓ **0.7.33 (HEAD 463dfba)** — tools-as-data core: `ToolDefinition` + 3
  recipe types + 7 tool data modules + `agentic_tools_registry` (`tool_definition`,
  `surface_specs_for`); 39 tests incl. 25-pair cross-adapter agent matrix + per-tool mcp
  round-trips through the REAL dialects (NFR-11/18). **Phase F begins.**
- Per-step audit reports under `docs/audits/code_audit_2026_06_*.md` (untracked); marker
  `.last_code_review.json` at `2026_06_12__15_46` / `bb1005a` / `diff` (S19 — the S20-1 audit is
  deferred to the end-of-S20 numbered-step boundary per the new cadence).

### 3.4 Status — what is in progress

**Nothing mid-edit.** S20 increment 1 is fully shipped (committed + pushed as 463dfba). The
working tree is clean apart from the deliberately-untracked `docs/audits/`. No background agents
running. No half-applied refactor. The session ended at a clean step boundary.

### 3.5 Next concrete step

Begin **S20 increment 2 — per-tool field maps + mcp spellings** via `/incremental_step`. First
action: read the seven old `src/agents_sync/*_io.py` modules (`claude_io`, `codex_io`,
`cursor_io`, `copilot_io`, `gemini_cli_io`, `opencode_io`) + `src/agents_sync/field_names.py` to
extract the per-tool field tables (model/effort/tools spellings) and the mcp dialect overrides
(from the old `McpServerDialect` instances in `src/agents_sync/tool_specs/*.py`), then move them
into the S20 tool data modules as recipe data. The detail step must surface which overrides land
in increment 2 vs which defer further (env-ref styles and carriers may be their own increment).

### 3.6 Open questions / decisions awaiting the user

None blocking. The audit-cadence decision was made and memorized this session. S20 increment
boundaries are the resuming session's to propose at the detail step.

## 4. Other tasks queued behind the active one

Per the plan after S20 completes (the **S20 deferral queue** — recorded in the plan's
deferred-items list + the S20 row):
- **S20 later increments** — per-tool field maps (model/effort/tools); mcp spellings (opencode
  `environment` for env + inverted-polarity `enabled`, array command mode, claude `oauth` render
  field); env-reference SYNTAX conversion + per-tool `env_reference_style` +
  `env_http_headers`/`bearer_token_env_var` carriers; the **skill (directory-tree) dialect** +
  antigravity recipes; reserved names; `CanonicalDocument.from_dict` type-coercion hardening
  (S15 note); the two **S19 watch-items** (planner pruning a vanished tool's recorded surface
  after rename; same-file render targets once tools-as-data makes them reachable). medium–large.
- **S21** — `runtime_config` (load/validate/platform paths; resolves the config keys the
  registry's `surface_specs_for` consumes; fail-closed exit code, NFR-10, US-07 AC-7). medium.
- **S22** — `poll_daemon` + `command_line_interface` (sync_once = read→plan→execute wiring;
  owns the cross-poll observation cache, structured logging incl. quarantine/secret events,
  GC tick, exit-code matrix). medium.
- **S23** — `portable_library` (export; import preview-then-write + `--force`; secret egress at
  export/import; last-modified-wins; US-12). medium.
- **S24** — cutover: daemon read→plan→execute live; full conformance green; **parser_bounds
  size-explosion hardening MUST land here** (the branch's original purpose). large.
- **S25** — retire old `src/`: directory rename, fold `tests_new/`→`tests/`, measure LOC vs
  ~6–7k target, architecture.md reflects final map. large.

## 5. Files touched this session (skim list)

Rebuild source created/edited (`src_new/agents_sync/`):
- `dialects/mcp_server/{__init__,_shared,parse,render}.py` [S13b split, S13c http/sse]
- `dialects/keyed_map_slot.py` [S19 `remove_slot`]
- `domain_model/canonical_document.py` [S13c url/headers/auth fields]
- `atomic_file_writer.py` [S14 created; S15 `move_file_atomic`; S16 `retry_transient_io` public]
- `canonical_store.py` [S15a], `sync_state_store.py` [S15b], `store_quarantine.py` [S15b]
- `artifact_archive.py` [S16]
- `read_tool_surfaces.py` [S17; S19 `surface_content_digest`], `rules_import_resolution.py` [S17]
- `secret_policy.py` [S18]
- `execute_sync_plan/{__init__,_shared,content_intents,identity_intents}.py` [S19 package]
- `translation.py` [S19 `remove_surface_content`/`surface_fragment_text`]
- `tools/{tool_definition,_shared_formats,claude,codex,cursor,copilot,gemini_cli,opencode,antigravity,agentic_tools_registry}.py` [S20-1]
Rebuild tests (`tests_new/`): `test_mcp_server`, `test_canonical_document`, `test_atomic_file_writer`,
  `test_canonical_store`, `test_sync_state_store`, `test_artifact_archive`,
  `test_read_tool_surfaces`, `test_secret_policy`, `test_execute_sync_plan`,
  `test_agentic_tools_registry`.
Design docs (edited each step): `docs/architecture_implementation_plan.md`,
  `docs/architecture_simplification_proposal.md`.
Old `src/` [READ-ONLY reference]: `*_io.py`, `tool_specs/*.py`, `mcp_secret_policy.py`,
  `archive.py`, `archive_gc.py`, `state.py`, `canonical.py`, `rules_io.py`,
  `filesystem_windows_retry.py`, `discovery/*`.
Memory created: `feedback_audit_cadence.md`.
Archived: `tmp_orig.py`, `execute_sync_plan_s19a_single_module.py` → `archive/`.

## 6. Anything else the next session needs to know

- **Commit gate is `bash scripts/ci.sh`** (ruff + mypy src + mypy src_new + pytest tests/ +
  pytest -c pytest_new.ini). Pre-push hook also runs it. Fast iteration:
  `uv run pytest -c pytest_new.ini <files>`.
- **`ruff format <file>` wraps code but NOT docstrings/comments** — keep those ≤100 by hand.
- **`docs/audits/` is deliberately UNTRACKED** — every `/bcp` excludes it; never stage it.
- The auditors genuinely catch real bugs each step (S15 reproduced P0 TypeError-escape, S16
  containment tautology, S17 frozen-slot stale digest, S19 rename/remove non-transactional). Verify
  auditor P0/P1 by reproducing before fixing; push back on conscious justified decisions.
- 2026-06-15 (restart `save` note, no argument): user invoked `/restart` at a clean S20-1 step
  boundary, switched model to Opus 4.8 + effort xhigh. Resume by detailing S20 increment 2.
