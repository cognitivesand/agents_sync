# Restart — 2026-06-15

> Last updated by Claude at 2026-06-15T19:04:56+0200. This file is a session-handoff
> snapshot. A fresh session reading this should be able to resume work without
> further explanation.

## 0. Git pin (do not edit by hand)

- `head_sha`: 7384cfc3d7b83e02991681150516bb3b42a9c3ac
- `head_short`: 7384cfc
- `branch`: fix/size-explosion-hardening
- `dirty`: false (no tracked changes)
- `dirty_summary`: clean (tracked); 32 untracked files — all are `docs/audits/**` audit
  artifacts + `graphify-out/` (left untracked by project convention; NOT pending work)
- `remote_head`: 7384cfc (pushed; upstream = origin/fix/size-explosion-hardening)
- `saved_at`: 2026-06-15T19:04:56+0200

## 1. Read these first

- `~/.claude/AGENTS.md` — global engineering rules (POLA/KISS/YAGNI/DRY/SRP/SoC; functions
  ≤40 lines, modules ≤300; tools-as-data, NO tool-name branches; surgical changes; no bulk renames).
- `docs/architecture_implementation_plan.md` — **the spine.** Step-by-step rebuild plan; the
  "Progress (current state)" block at the top is the live status. Phase F (S20) is now complete.
- `docs/architecture_simplification_proposal.md` (rev 4) — the design the plan builds.
- `docs/project_description.md`, `docs/project_requirements.md`, `docs/stories/US-*.md` — governance.
- `docs/architecture.md` — module map (describes the OLD `src/` tree; the rebuild lives in `src_new/`).

## 2. Working context (non-obvious deltas)

- **Greenfield-parallel REBUILD.** New code in `src_new/agents_sync/`, tests in `tests_new/`.
  Old `src/agents_sync/` is REFERENCE ONLY (never edit it). Cutover (S24–S25) is a directory
  rename `src_new → src` (honours the no-bulk-rename memory). Nothing user-visible ships until cutover.
- **Test wiring (important — an auditor got this wrong this session):** the rebuild suite runs
  via `uv run pytest -c pytest_new.ini` (its `pythonpath=src_new` repoints `agents_sync`). The
  DEFAULT `pytest` (testpaths=['tests']) runs only the OLD conformance suite. There is **no
  `tests_new/conftest.py`** — do NOT add one (it would leak src_new into the conformance run).
- **Full local gate = `bash scripts/ci.sh`** (ruff + mypy src + mypy src_new + pytest tests/ +
  pytest -c pytest_new.ini). The pre-push hook runs it too. Use it as the commit gate.
- **Rebuild version bumps are PATCH `feat(rebuild)`** (plan says so); a bump must also run
  `uv lock` and stage `uv.lock`. No git tag for rebuild steps (nothing user-visible yet).
- **Audit cadence (memory `feedback_audit_cadence`):** the heavyweight `/code_and_tests_quality_review`
  runs ONCE per plan step NUMBER, after all its sub-increments — NOT between sub-increments. The
  S20 audit just ran (this session) and is remediated; the `.last_code_review.json` marker is at HEAD.
- **mcp_server dialect is fully data-driven** via `McpSpellingRecipe` (in `domain_model/tool_surface.py`),
  consumed generically by `dialects/mcp_server/{parse,render,_shared,_carriers}.py`. NO tool-name
  branches anywhere. The canonical stores env-references in ONE fixed style `${env:NAME}`.
- **Tracked gap (NOT yet done):** gemini's `oauth` auth-field spelling — gemini renders mcp auth
  under `auth` not `oauth` (an increment-4-style knob it lacks). Noted in the plan; fold into a cleanup.

## 3. Active task

### 3.1 Goal

Execute the thin-clean-architecture rebuild (`docs/architecture_implementation_plan.md`) one gated
increment at a time, until cutover replaces the old `src/` with `src_new/`.

### 3.2 Constraints specific to this task

- Hard: each increment goes through the `incremental_step` skill gate (docs → red-first tests →
  `/audit-tests` → code → full CI → quality review → ship). Conformance suite (`tests/`) stays
  green at every step. Never edit `src/` (reference only). Governance edits need user approval.
- Soft: rebuild bumps are PATCH `feat(rebuild)`; audit batched per plan-step-number.
- Out of scope: cutover (S24–S25) is later; gemini oauth is a deferred cleanup.

### 3.3 Status — what is done

- **Phase F / S20 COMPLETE (increments 1–7).** This session shipped 5, 6, 7:
  - S20-5 codex mcp carriers → 0.7.38 (`3f6c043`)
  - S20-6 gemini url/transport inference + codex/gemini transport+name suppression → 0.7.39 (`35a6935`)
  - S20-7 per-tool inline env-reference style conversion → 0.7.40 (`a1c5463`)
- **End-of-S20 two-auditor audit + remediation DONE** → 0.7.41 (`7384cfc`, current HEAD). 32 findings
  (9 MAJOR / 18 WARNING / 5 INFO); 31 APPLY-APPROVE + 1 APPLY-OVERRIDE, 0 ESCALATE. Fixed 2 latent
  MAJOR code bugs (parse `name`-reset NFR-16; one shared `reject_shared_write_file` guard raising
  `IntentAbortError` across all multi-surface writers — silent-clobber + poll-isolation). Reports at
  `docs/audits/code_audit_2026_06_15__17_35.md` + `..._remediation_...md` (untracked).
- Full `scripts/ci.sh` green at HEAD (575 rebuild tests + conformance).

### 3.4 Status — what is in progress

Nothing mid-edit — this is a clean shipped checkpoint. Working tree has only untracked artifacts
(`docs/audits/**`, `graphify-out/`), left untracked by project convention. No background agents
(all S20-audit subagents completed and were consumed this session).

### 3.5 Next concrete step

Start **S21 — Runtime config** (`runtime_config` module) per the plan: load/validate/platform
paths, fail-closed config errors + distinct exit code (NFR-10, US-07 AC-7). Drive it through the
`incremental_step` skill (it is its own plan step → its own audit at the end).

### 3.6 Open questions / decisions awaiting the user

None.

## 4. Other tasks queued behind the active one

- **S21 Runtime config** — `runtime_config`: load/validate/platform paths, fail-closed (NFR-10, US-07 AC-7). Medium. (= the active next step.)
- **S22 Daemon + CLI** — `poll_daemon`, `command_line_interface`: failure budget (FR-02), GC tick, latency (NFR-02), export/import/run, exit-code matrix. Large.
- **S23 Portable library** — export; import preview-then-write + `--force`; last-modified-wins / cross-identity retire (US-12, FR-12/15). Medium.
- **Phase G cutover (S24–S25)** — `src_new → src` rename + retirement; `parser_bounds` size-explosion gate (S24). Large.
- **Cleanup: gemini mcp `oauth` auth-field spelling** — small data fix gemini still lacks (renders auth under `auth`). Small.

## 5. Files touched this session (skim list)

- `docs/architecture_implementation_plan.md` [edited] — Phase F progress + S20 row marked complete through inc 7
- `src_new/agents_sync/domain_model/tool_surface.py` [edited] — McpSpellingRecipe knobs (carriers, transport/name suppress, transport_by_url_field/url_field_by_transport, env_reference_style)
- `src_new/agents_sync/dialects/mcp_server/_shared.py` [edited] — headers alias family, env-ref vocab + restyle, coercion helpers
- `src_new/agents_sync/dialects/mcp_server/_carriers.py` [created] — codex http auth carrier fold/split
- `src_new/agents_sync/dialects/mcp_server/parse.py` [edited] · `render.py` [edited] · `__init__.py` [edited]
- `src_new/agents_sync/tools/{codex,gemini_cli,claude,opencode}.py` [edited] — per-tool McpSpellingRecipe data
- `src_new/agents_sync/dialects/keyed_map_slot.py` [edited] · `execute_sync_plan/{__init__,_shared,content_intents,identity_intents}.py` [edited] — remediation
- `tests_new/test_mcp_codex_carriers.py` [created] · `test_mcp_transport_inference.py` [created] · `test_mcp_env_reference_style.py` [created]
- `tests_new/{test_mcp_server,test_mcp_opencode_dialect,test_agentic_tools_registry,test_tool_field_maps,test_execute_sync_plan}.py` [edited]
- `pyproject.toml` [edited] (version 0.7.41 + stale test-comment fix) · `uv.lock` [edited]

## 6. Anything else the next session needs to know

- Memory already covers: no-bulk-renames, releases=tag+gh-release, AC-authoring style, governance
  final-text approval, uv.lock-tracks-bump, spec/code alignment, audit cadence, tools-as-data-no-hardcoding.
- The `docs/audits/**` reports + raw JSON are UNTRACKED by project convention (matches the many
  pre-existing untracked `code_audit_*.md`). Don't `git add -A` them into a feature commit.
- `2026-06-15`: /restart invoked with no argument after shipping the end-of-S20 remediation (0.7.41).
  Save written at a clean checkpoint; next session begins S21.
