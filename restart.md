# Restart — 2026-06-11

> Last updated by Claude at 2026-06-11T00:00:00Z. Session-handoff snapshot. A fresh
> session reading this should be able to resume without further explanation.

## 0. Git pin (do not edit by hand)

- `head_sha`: 4d9e95e6c5b1faf94d3ac32741e4c9120093051c
- `head_short`: 4d9e95e
- `branch`: fix/size-explosion-hardening
- `dirty`: true
- `dirty_summary`: 2 modified (docs), 1 staged deletion, ~20 untracked (the new mcp_server package + docs/audits artifacts + one stray)
- `remote_head`: 4d9e95e (pushed, up to date)
- `saved_at`: 2026-06-11T00:00:00Z

Uncommitted paths (see 3.4 for what/why):
- `M  docs/architecture_implementation_plan.md` — S13b/S13c rows + env-ref→S20 deferral + Progress
- `M  docs/architecture_simplification_proposal.md` — §13 mcp_server entry (package + env-ref deferral)
- `D  src_new/agents_sync/dialects/mcp_server.py` — removed (git rm); replaced by the package
- `?? src_new/agents_sync/dialects/mcp_server/` — the new package (__init__.py, _shared.py, parse.py, render.py)
- `?? docs/audits/**` — review artifacts, intentionally **NOT tracked** (never stage)
- `?? tmp_orig.py` — STRAY scratch file at repo root, not part of this change (see §6)

## 1. Read these first

Order matters:
- `AGENTS.md` (via `~/.claude/CLAUDE.md`) — global rules (POLA/KISS/YAGNI/DRY/SRP/SoC; §3 size ≤40 lines/fn, ≤300/file; §8 fail-fast; §11 commits; §13 bash discipline).
- `docs/architecture_implementation_plan.md` — **the active plan**, now with a **Progress section** (self-sufficient state): Phase A+B ✓, Phase C done through **S13a**; **S13b in progress**; S13c next after it.
- `docs/architecture_simplification_proposal.md` — rev 4 target design. §10 = centralized translation (dialects + shared `field_mapping`); §13 = module map; §12 = cross-cutting homes (secret policy at egress).
- `docs/project_description.md`, `docs/project_requirements.md` (FR-09 = mcp_server matrix), `docs/stories/US-*.md`.
- The `incremental_step` skill (`~/.claude/skills/incremental_step/SKILL.md`) — the per-step gate this work follows.

## 2. Working context (deltas not in the docs)

- **Execution rhythm:** one gated step per `/incremental_step`; user drives with "continue". The gate: detail (surface genuine decisions to the user) → docs → tests + `/audit-tests` (only point tests change) → code → full CI (`bash scripts/ci.sh`) → `/code_and_tests_quality_review` on the diff (hand-orchestrate the **code-quality-auditor** + **test-quality-auditor** subagents in parallel; 3 targets: spec / clean-code / efficiency) → spotless (≤3 loops, else escalate) → write a markdown report `docs/audits/code_audit_<ts>.md` + update `docs/audits/.last_code_review.json` (NEVER stage docs/audits) → `/bcp`.
- **Greenfield-parallel:** new code in `src_new/agents_sync/`, tests in `tests_new/` (`uv run pytest -c pytest_new.ini`). Old `src/` is **reference only, never modified**. Conformance suite (`tests/`, 579) stays green every step. Rebuild suite now **290 green**.
- **Versioning:** each rebuild step is a **PATCH** `feat(rebuild)` (nothing user-visible ships until cutover S24–S25). Now at **0.7.21**. Always `uv lock` + stage `uv.lock` with the bump ([[project_uvlock_version_bump]]).
- **Translation architecture:** `translation.py` dispatches on `surface_format.dialect` → a dialect's pure `parse`/`render`/`extract_id` (take the whole `ToolSurface`). Dialects are **pure, no I/O**. `MalformedSurfaceError(ValueError)` = malformed CONTENT (read phase catches → ParseFailure/freeze); a plain `ValueError` = recipe/config OR not-yet-supported error (fail loud). The distinction is load-bearing and tested via `type(err) is ValueError` / `not isinstance(err, MalformedSurfaceError)`.
- **The new `CanonicalDocument` is a fixed-schema frozen dataclass** (NOT the old dict-of-keys). Schema grows by **flat optional fields** (the established `model`/`effort`/`tools` agent-only pattern). S13a added 8 mcp optionals: `transport`, `command`, `args`, `env`, `cwd`, `timeout`, `disabled`, `always_allow`. `args`/`always_allow` are **order-preserving** (NOT sorted like `tools`); `env` is a frozen string→string map.
- **Decisions locked this session (do NOT re-litigate):**
  - **S12** = the pure `detect_framework_specific` predicate ONLY. Whole-file global rules fold via the `markdown_frontmatter` dialect; `@import` resolution (FS I/O) + framework egress-guard *enforcement* → **read phase S17–S19**.
  - **S13a** = flat optional schema + the **stdio** mcp dialect (transport canonicalization + alias map, inference, command/args array-split, env/cwd/timeout verbatim, disabled, always_allow, per-tool spelling preservation, no-foreign-leak). mcp fields **reset on each parse**.
  - **S13b** (in progress) = **pure behavior-preserving package split**, its own step.
  - **S13c** (next) = http/sse transport (url/headers/auth flat fields, **verbatim**, like stdio env).
  - **Deferred to S20** (tools-as-data, per-tool recipe data): env-reference SYNTAX conversion (`${env:NAME}`↔`${NAME}`↔`{env:NAME}`) + per-tool `env_reference_style` + the dedicated `env_http_headers`/`bearer_token_env_var` carriers + opencode's inverted-polarity `enabled` spelling. Reason: converting env-refs without per-tool render styles would break round-trip.
  - **Deferred to S18:** mcp secret policy (refuse/warn/redact) — runs at planner/executor egress, not the dialect.
  - `keyed_map_slot` now exposes **`read_slot` / `write_slot`** (the shared keyed-map-file mechanism); `mcp_server` reuses them.
- **`mcp_server` reference** (behaviour the conformance suite preserves): old `src/agents_sync/mcp_server_io/{parse,render,headers,dialect,_helpers,_slot_codec}.py` and `src/agents_sync/mcp_secret_policy.py` (env-ref syntax fns: `convert_env_references`/`format_env_reference`/`env_reference_name`/`bearer_env_reference_name`).
- **`docs/audits/` is deliberately UNTRACKED** — never stage; every `/bcp` excludes it. `.last_code_review.json` marker is at `2026_06_09__06_41` / `b88a98a` / `diff`.

## 3. Active task

### 3.1 Goal

Rebuild `agents_sync` as the thin, clean, spec-compliant architecture in the proposal, in small independently-shippable gated steps, then cut over from the old `src/`.

### 3.2 Constraints

- Hard: conformance suite green every step; full `incremental_step` gate to spotless (both code + test audits clean, ≤3 loops or escalate); governance artifacts (description/stories/AC/requirements) change only with explicit user approval of exact text ([[feedback_governance_approval]]); removing/deferring behaviour updates the spec in the same change ([[feedback_spec_code_alignment]]); **no bulk renames** ([[feedback_renames]]) — the S13b split deliberately kept every identifier identical.
- Soft: greenfield-parallel; PATCH bumps; additive YAGNI growth; surface genuine scope/dependency decisions to the user at the detail step (done for S12, S13a, S13b).

### 3.3 Status — what is done

**Phase A (S1–S4) ✓, Phase B (S5–S8d) ✓, Phase C through S13a ✓.**
- **S12 ✓** framework-specificity predicate (`dialects/global_rules`) — `b88a98a` (0.7.20).
- **S13a ✓** stdio mcp dialect + 8 flat optional canonical fields + `keyed_map_slot.read_slot/write_slot` — `5bcb112` (0.7.21).
- **Plan progress persistence** (Progress section + S13a row correction) — `4d9e95e` (HEAD).
- Per-step audit reports under `docs/audits/code_audit_2026_06_0{8,9}*.md` (untracked).
- **S13b — package split: code + docs COMPLETE, full CI GREEN (579 conformance + 290 rebuild, ruff + mypy --strict), but NOT yet quality-reviewed or shipped** (the review was interrupted to run /restart).

### 3.4 Status — what is in progress

**S13b (mcp_server package split) — gate steps 1–5 done, step 6 (quality review) interrupted, not shipped.**
- The single module `src_new/agents_sync/dialects/mcp_server.py` (was 332 lines, over §3 300 limit) was split into a package `src_new/agents_sync/dialects/mcp_server/`:
  - `_shared.py` (55 lines) — field-spelling constants + `_canonical_transport` (used by both parse and render).
  - `parse.py` (202) — `parse` + `extract_id` + all parse helpers/utils.
  - `render.py` (95) — `render` + render helpers.
  - `__init__.py` (26) — re-exports `parse`/`render`/`extract_id` (the trio the translation registry calls; `from agents_sync.dialects import mcp_server` still resolves).
- **Behaviour preserved** — proven by the **unchanged** `tests_new/test_mcp_server.py` (22 tests) + conformance, all green. **No test changes** this step (pure refactor), so `/audit-tests` was a no-op and the **test-quality auditor is not needed** for the review.
- **Identifiers kept identical** across the move (no renames — the no-bulk-rename rule). One intentional non-behavioural text change: the http-not-supported error message + a docstring now say **"(S13c)"** instead of "(S13b)" because http moved to S13c. No test asserts the message text (the http test asserts `type(error.value) is ValueError`).
- `git rm` already staged the old module deletion; the package files are untracked. Docs (plan + proposal) edited (unstaged). Version still **0.7.21** (S13b has not bumped).

### 3.5 Next concrete step

Run the **code-quality-auditor** subagent on the S13b split (diff = the new `mcp_server/` package + the deleted single module + the doc edits), scoped to verifying the split is **behaviour-preserving and structurally clean** (clean DAG `_shared ← parse,render ← __init__`; no cycle; public API unchanged; nothing dropped/duplicated in the move). The exact prompt that was about to run is in the conversation. **Skip the test-quality auditor** (zero test changes). If spotless → write the audit report under `docs/audits/`, update `.last_code_review.json`, then `/bcp` patch **0.7.21 → 0.7.22** staging the package + the two docs + pyproject + uv.lock (NEVER `docs/audits/`, NEVER `tmp_orig.py`).

### 3.6 Open questions / decisions awaiting the user

None blocking. The two S13b scope decisions (defer env-ref conversion + carriers to S20; do the package split as its own step before http) were already made and applied this session.

## 4. Other tasks queued behind the active one

Per `docs/architecture_implementation_plan.md` after S13b ships:
- **S13c** — MCP http/sse transport: `url`/`headers`/`auth` flat canonical fields + url alias detection, inline headers + auth **verbatim** (env-ref conversion stays S20). Added into the new package. medium.
- **S14–S16** — gateways (atomic_file_writer, canonical/state stores, archive+GC). medium.
- **S17–S19** — read phase (resolves `@import`; framework/secret projection predicates land here), secret_policy (S18), execute_sync_plan (sole mint). medium.
- **S20–S23** — tools-as-data + registry (per-tool recipes incl. env-ref styles, carriers, `enabled` polarity), runtime_config, daemon/CLI, portable_library. medium.
- **S24–S25** — cutover (wire daemon read→plan→execute; full conformance green; **parser_bounds size-explosion hardening MUST land here**) + retire old `src/` (directory rename, LOC measurement). large.

## 5. Files touched this session (skim list)

Rebuild source (`src_new/agents_sync/`):
- `dialects/global_rules.py` [created S12 — `detect_framework_specific` + token constant]
- `dialects/mcp_server.py` [created S13a, **deleted S13b** — split into the package]
- `dialects/mcp_server/{__init__,_shared,parse,render}.py` [created S13b]
- `dialects/keyed_map_slot.py` [edited S13a — exposed `read_slot`/`write_slot`]
- `domain_model/canonical_document.py` [edited S13a — 8 flat optional mcp fields]
- `translation.py` [edited S12/S13a — registered global_rules + mcp_server]
Rebuild tests (`tests_new/`): `test_global_rules.py` [created S12], `test_mcp_server.py` [created S13a, UNCHANGED S13b], `test_canonical_document.py` [edited S13a].
Design docs: `docs/architecture_implementation_plan.md`, `docs/architecture_simplification_proposal.md` [edited each step].
Old `src/` [READ ONLY, reference]: `mcp_server_io/{parse,render,headers,dialect,_helpers,_slot_codec}.py`, `mcp_secret_policy.py`, `canonical.py`, `rules_io.py`, `tool_specs/opencode.py`.

## 6. Anything else the next session needs to know

- **Commit gate is `bash scripts/ci.sh`** (ruff + mypy src + mypy src_new + pytest tests/ + pytest -c pytest_new.ini). Pre-push hook also runs it. Fast iteration: `uv run pytest -c pytest_new.ini <files>`.
- **`ruff format <file>` wraps long lines but NOT docstrings/comments** — keep docstring/comment lines ≤100 by hand. Lines ≤100, PEP 695 `type X = ...`.
- **STRAY FILE: `tmp_orig.py` at the repo root** is untracked and not part of any step (likely a leftover scratch). Do NOT stage it; mention to the user / clean it up (don't `rm` without asking — [[feedback_renames]] caution applies to deletions too; just flag it).
- The audits genuinely catch real bugs each step — verify auditor P0/P1 by reproducing before fixing; push back on conscious justified decisions (Rule-of-Three not met, §-sanctioned co-location, scope deferrals).
- 2026-06-11 (restart `save` note): user invoked /restart mid-S13b, right after the package split passed full CI but before the quality review ran. Resume by running the code-quality review on the split, then ship S13b (0.7.22), then `/incremental_step` for S13c.
