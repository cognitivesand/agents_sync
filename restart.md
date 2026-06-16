# Restart — 2026-06-16

> Last updated by Claude at 2026-06-16T00:05:00+0200. This file is a session-handoff
> snapshot. A fresh session reading this should be able to resume work without
> further explanation.

## 0. Git pin (do not edit by hand)

- `head_sha`: 00d212a5c4695d6cacc2e7e3f3149f2614baaa89
- `head_short`: 00d212a
- `branch`: fix/size-explosion-hardening
- `dirty`: false (no tracked changes)
- `dirty_summary`: clean (tracked); 36 untracked files — all `docs/audits/**` audit
  artifacts + `graphify-out/` (left untracked by project convention; NOT pending work)
- `remote_head`: 00d212a (pushed; upstream = origin/fix/size-explosion-hardening)
- `saved_at`: 2026-06-16T00:05:00+0200

## 1. Read these first

- `~/.claude/AGENTS.md` — global engineering rules (POLA/KISS/YAGNI/DRY/SRP/SoC; functions
  ≤40 lines, modules ≤300; tools-as-data, NO tool-name branches; surgical; no bulk renames).
- `docs/architecture_implementation_plan.md` — **the spine.** Step-by-step rebuild plan; the
  "Progress (current state)" block at the top is the live status. Phase F (S20, S21, S22) complete.
- `docs/architecture_simplification_proposal.md` (rev 4) — the design the plan builds.
- `docs/project_description.md`, `docs/project_requirements.md`, `docs/stories/US-*.md` — governance.
- `docs/architecture.md` — module map (describes the OLD `src/` tree; rebuild lives in `src_new/`).
- `docs/agentic_tool_integration_protocol.md` — tool-integration contract (describes the OLD
  `AgenticToolSpec`/`config.py` model; reconciled to the new tools-as-data model at cutover S24).

## 2. Working context (non-obvious deltas)

- **Greenfield-parallel REBUILD.** New code in `src_new/agents_sync/`, tests in `tests_new/`.
  Old `src/agents_sync/` is REFERENCE ONLY (never edit). Cutover (S24–S25) is a directory rename
  `src_new → src`. Nothing user-visible ships until cutover.
- **Test wiring:** rebuild suite runs via `uv run pytest -c pytest_new.ini`; default `pytest`
  runs the OLD conformance suite (`tests/`). Full gate = `bash scripts/ci.sh` (ruff + mypy src +
  mypy src_new + pytest tests/ + pytest -c pytest_new.ini); the pre-push hook runs it.
- **Rebuild bumps are PATCH `feat(rebuild)`**; a bump must run `uv lock` and stage `uv.lock`. No git
  tag for rebuild steps. Each plan step is driven via the **`incremental_step`** skill gate.
- **Audit cadence (memory `feedback_audit_cadence`):** the heavyweight two-auditor
  `/code_and_tests_quality_review` runs ONCE per plan-step NUMBER, after all its sub-increments —
  NOT between them. Sub-increments still get docs → red-first tests → `/audit-tests` → code → full
  CI → commit/`/bcp`.
- **Audit scoping gotcha:** `docs/audits/.last_code_review.json` records HEAD *at review time*, so it
  LAGS the prior step's remediation commit. For each end-of-step audit I scoped the diff to the
  step's own delta (S21 used `7384cfc`; S22 used `936e2e1`) rather than the lagging marker, so the
  prior step's already-adjudicated remediation isn't re-audited. The marker is currently `1130bfb`
  (untracked). The S23 end-of-step audit should reference **`00d212a`** (S22-complete).
- **TWO user design decisions made this session (already applied):**
  1. **S21 default paths = tools-as-data (Option B):** each surface recipe carries a
     `DefaultLocation(anchor, relative_parts)` (anchor = `PathAnchor.HOME` | `CONFIG_ROOT`, or
     `None` for no built-in default); `runtime_config.resolve_default_paths` resolves anchors per-OS.
  2. **S22 sequencing = "build runnable daemon now":** S22a/b/c built `poll_daemon` + `sync_once` +
     CLI now; **export/import deferred to S23** (with `portable_library`); **`parser_bounds` +
     pointing the conformance suite at the new pipeline deferred to S24** (the cutover).
- **`count_available_tools` semantics are PROVISIONAL:** "a tool is available iff ≥1 of its resolved
  roots exists." The old model was "all roots exist + ensure_roots + enabled-flag" (none of which
  exist in the rebuild). The S24 conformance cutover (`tests/test_two_tool_guard.py`,
  `test_nfr17_unattended_operation.py`) validates/refines this; expect possible tweaks then.
- **`run_daemon` (CLI→daemon wiring) is a deliberately-untested thin shim** — its parts
  (`make_periodic_poll`, `watch`, `prune_archive`) are covered; S24 conformance validates the
  assembled pipeline (recorded in the S22 remediation report's reject-guidance).
- **Audit-artifact fidelity note:** the S22 `resolutions.json`/`decisions.json` I wrote under
  `docs/audits/remediation/code_audit_remediation_2026_06_15__23_42/` are faithful captures
  (recommendation + chosen solution + rationale + dissent per finding), NOT byte-for-byte copies of
  the resolver's full 3–5-option enumerations (the raw outputs were very large). The S21 ones are
  similar. Don't treat them as the agents' verbatim transcripts.
- **Subagents occasionally returned `API Error: Overloaded`** mid-run; re-launching the same prompt
  worked. Watch for it on big fan-outs.

## 3. Active task

### 3.1 Goal

Execute the thin-clean-architecture rebuild (`docs/architecture_implementation_plan.md`) one gated
increment at a time, until cutover replaces the old `src/` with `src_new/`.

### 3.2 Constraints specific to this task

- Hard: each plan step goes through the `incremental_step` gate (docs → red-first tests →
  `/audit-tests` → code → full CI → end-of-step `/code_and_tests_quality_review` → ship). Conformance
  suite (`tests/`) stays green at every step. Never edit `src/`. Governance edits need user approval
  of exact final text.
- Soft: rebuild bumps PATCH `feat(rebuild)`; heavyweight audit batched per plan-step-number.
- Out of scope now: cutover (S24–S25); gemini `oauth` mcp auth spelling (deferred cleanup).

### 3.3 Status — what is done

- **S21 — Runtime config COMPLETE.** S21a default-location tool-data (0.7.42 `eaa944b`); S21b
  `runtime_config` load/validate/resolve + exit codes 0/1/2 (0.7.43 `5074745`); end-of-S21 audit +
  remediation → 0.7.44 (`936e2e1`).
- **S22 — Daemon + CLI COMPLETE.** S22a `poll_daemon.watch` (0.7.45 `f871a0f`); S22b `sync_once` +
  `count_available_tools` + `make_periodic_poll` (0.7.46 `2f5e0e1`); S22c `command_line_interface` +
  `__main__` (`run`/`prune`, exit-code matrix) (0.7.47 `1130bfb`); end-of-S22 audit + remediation →
  0.7.48 (`00d212a`, current HEAD). The S22 MAJOR finding (SIGINT/SIGTERM shutdown path untested) was
  fixed with a parametrized signal-delivery test.
- Full `bash scripts/ci.sh` green at HEAD (579 conformance + 640 rebuild tests).

### 3.4 Status — what is in progress

Nothing mid-edit — clean shipped checkpoint. Working tree has only untracked artifacts
(`docs/audits/**`, `graphify-out/`). No background agents (all S22-audit subagents completed/consumed).

### 3.5 Next concrete step

Start **S23 — Portable library** via the `incremental_step` skill: build `portable_library`
(export; import preview-then-write + `--force`; last-modified-wins / cross-identity retire — US-12,
FR-12/15) AND wire the CLI's `export`/`import` subcommands (deferred from S22 per the user decision).
It is its own plan step → its own batched end-of-S23 audit.

### 3.6 Open questions / decisions awaiting the user

None blocking. (Last turn ended by asking "Want me to start S23?" — a go/no-go, not a design
decision. The S22 sequencing decision is already made and applied.)

## 4. Other tasks queued behind the active one

- **S23 Portable library** — `portable_library` + CLI export/import wiring (US-12, FR-12/15). Medium.
  (= the active next step.)
- **Phase G cutover (S24)** — wire `poll_daemon`/CLI `sync_once = read→plan→execute` as the active
  pipeline; **gate: `parser_bounds` size-explosion hardening MUST land first**; point the full
  conformance suite at the new pipeline (validates `count_available_tools` semantics, the two-tool
  guard, `run_daemon` assembly). Large.
- **Phase G S25** — retire superseded old `src/` modules; `src_new → src` rename; measure LOC vs
  ~6–7k target; update `docs/architecture.md` + `docs/agentic_tool_integration_protocol.md` to the
  new model. Large.
- **Cleanup: gemini mcp `oauth` auth-field spelling** — small data fix gemini still lacks. Small.

## 5. Files touched this session (skim list)

- `src_new/agents_sync/runtime_config.py` [created] — load/validate/resolve, exit codes, ConfigurationError
- `src_new/agents_sync/poll_daemon.py` [created] — the poll loop `watch()`
- `src_new/agents_sync/sync_once.py` [created] — read→plan→execute orchestration + count_available_tools + make_periodic_poll
- `src_new/agents_sync/command_line_interface.py` [created] · `__main__.py` [created] — CLI run/prune + exit-code matrix
- `src_new/agents_sync/tools/tool_definition.py` [edited] — PathAnchor + DefaultLocation + default_location field
- `src_new/agents_sync/tools/{claude,codex,cursor,copilot,gemini_cli,opencode}.py` [edited] — default_location data
- `src_new/agents_sync/translation.py` [edited] — KNOWN_DIALECTS public frozenset
- `tests_new/test_runtime_config.py` · `test_tool_default_locations.py` · `test_poll_daemon.py` ·
  `test_sync_once.py` · `test_command_line_interface.py` [created]
- `docs/architecture_implementation_plan.md` [edited] · `docs/architecture_simplification_proposal.md` [edited]
- `pyproject.toml` [edited] (0.7.41 → 0.7.48) · `uv.lock` [edited]
- `docs/audits/**` [created] — S21 + S22 audit/remediation reports + raw JSON (UNTRACKED by convention)

## 6. Anything else the next session needs to know

- Memory already covers: no-bulk-renames, releases=tag+gh-release, AC-authoring style, governance
  final-text approval, uv.lock-tracks-bump, spec/code alignment, audit cadence, tools-as-data-no-hardcoding.
- `docs/audits/**` reports + raw JSON are UNTRACKED by project convention — do NOT `git add -A` them
  into a feature commit. Stage only the intended source/test/doc/version files per increment.
- The plan's "Progress (current state)" block (top of `architecture_implementation_plan.md`) has the
  full per-step ledger through S22; trust it as the live status.
- `2026-06-16`: /restart invoked with no argument after shipping the end-of-S22 remediation (0.7.48).
  Save written at a clean checkpoint; next session begins S23.
