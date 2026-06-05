# Restart — 2026-06-05

> Last updated by Claude at 2026-06-05T12:30:00Z. This file is a session-handoff
> snapshot. A fresh session reading this should be able to resume work without
> further explanation.

## 0. Git pin (do not edit by hand)

- `head_sha`: 5ab57e39cf4c2b7bf7030e2039851973c6e17d9c
- `head_short`: 5ab57e3
- `branch`: fix/size-explosion-hardening
- `dirty`: true
- `dirty_summary`: 1 untracked (docs/audits/raw_audits_results/ — review scratch, intentionally uncommitted)
- `remote_head`: 5ab57e39cf4c2b7bf7030e2039851973c6e17d9c (up to date)
- `saved_at`: 2026-06-05T12:30:00Z

## 1. Read these first

Order matters:

- `AGENTS.md` (loaded via `~/.claude/CLAUDE.md`) — global engineering rules (POLA/KISS/YAGNI/DRY/SRP/SoC; §3 size limits; §8 fail-fast; §11 commits; §13 bash discipline).
- `docs/architecture_implementation_plan.md` — **the active plan**: the greenfield rebuild as gated steps S1–S25, each run through the `incremental_step` skill. Read the "per-step gate", "build location", and the S1–S25 table.
- `docs/architecture_simplification_proposal.md` — rev 4 target design (decision/execution split, centralized translation, one mint site, stored-canonical-as-input). Hardened across 3 critique passes.
- `docs/project_description.md`, `docs/project_requirements.md` (FR-01…16, NFR-01…18), `docs/stories/US-*.md` — governing spec.
- `docs/architecture.md` — the **as-built** (old `src/`) architecture; describes current code, NOT the rebuild.
- The `incremental_step` skill at `~/.claude/skills/incremental_step/SKILL.md` — the per-step gate this work follows.

## 2. Working context (deltas not in the docs)

- **We are executing the rebuild, one gated step per `/incremental_step` invocation.** The user drives with "ok"/"lets continue"/"next step".
- **Greenfield-parallel mode (user-chosen).** New code lives in `src_new/agents_sync/` (package name unchanged), tests in `tests_new/`. Old `src/agents_sync/` runs untouched; conformance suite (`tests/`, 579 tests) must stay green every step. **Cutover (S24–S25) is a directory rename** `src_new/agents_sync → src/agents_sync` (no import churn — honours the no-bulk-rename memory). `src_new` is NOT in the shipped wheel yet (`pyproject [tool.hatch...] packages=["src/agents_sync"]`).
- **Test isolation:** default `pytest` is pinned to `tests/` (`pyproject testpaths`); the rebuild runs via `uv run pytest -c pytest_new.ini` (its `pythonpath=src_new` puts the rebuild's `agents_sync` first). `scripts/ci.sh` runs both scopes + `mypy src_new`. ruff isort `known-first-party=["agents_sync"]`.
- **Per-step gate (the skill):** detail → docs → tests + `/audit-tests` (only point tests change) → code → full CI → `/code_and_tests_quality_review` on the diff (3 targets: spec compliance; clean code POLA/DRY/KISS/YAGNI/SRP/SoC; efficiency/sparsity) → spotless (max 3 audit→fix loops, else STOP+escalate) → commit + `/bcp`.
- **Versioning convention:** S1 was MINOR (0.7.0, "rebuild started"); each subsequent rebuild module is PATCH (S2=0.7.1, S3a=0.7.2, S3b=0.7.3), type `feat(rebuild)`, because nothing shipped changes until cutover.
- **YAGNI rule in force:** defer consumer-driven fields to the step that consumes them (e.g. `SurfaceFormat` recipe fields → S9 translation / S17 read phase). Confirmed with user on S3b.
- **Gotchas learned:** (a) frozen dataclasses over dict/list bags aren't truly immutable — `canonical_document` needed a recursive deep-freeze (mappings→MappingProxyType, lists→tuples; `_thaw` restores lists for round-trip) — took 4 review loops. (b) `/audit-tests` red-first catches vacuous test values (S2: an all-digit UUID's `.upper()` is a no-op). (c) The agents_sync daemon is running and auto-adopts new skills — it injected a `pair_id` into `incremental_step/SKILL.md` (live dogfooding; don't hand-mint ids).
- **Audit scratch:** `docs/audits/raw_audits_results/code_audit_2026_06_05__11_59/` holds per-step auditor JSONs from the manual review loops — untracked, not a clean skill run. Leave or clean; do not commit as-is.

## 3. Active task

### 3.1 Goal

Rebuild `agents_sync` as the thin, clean, spec-compliant architecture in the proposal, in small independently-shippable gated steps, then cut over from the old `src/`.

### 3.2 Constraints specific to this task

- Hard: conformance suite (`tests/`) green at every step boundary; each step passes the full `incremental_step` gate to **spotless** (max 3 review loops or escalate); governance artifacts (description/stories/AC/requirements) only change with explicit user approval of exact text.
- Soft: greenfield-parallel build in `src_new/`; PATCH bumps per rebuild module; YAGNI (defer consumer-driven shape).
- Out-of-scope (ruled out): refactor-in-place (user chose greenfield-parallel); a user-facing `prune` CLI (GC is daemon-internal); package-name rename at cutover (directory rename instead).

### 3.3 Status — what is done

Rebuild **Phase A (pure domain core)** nearly complete:
- **S1** ✓ `src_new/agents_sync/domain_model/canonical_document.py` — pure canonical entity (deep-frozen, content_digest excl. metadata FR-14, lossless round-trip NFR-16). Commit `26e3fae` (0.7.0).
- **S2** ✓ `artifact_identity.py` — sole `mint_artifact_id` + `validate_artifact_id` (UUIDv4, fail-fast). Commit `74245fd` (0.7.1).
- **S3a** ✓ `artifact_naming.py` — `slugify_name` + `candidate_key`. Commit `fa33361` (0.7.2).
- **S3b** ✓ `tool_surface.py` — `KeyedMapSlot`, minimal `SurfaceFormat(dialect)`, `ToolSurface`. Commit `5ab57e3` (0.7.3, current HEAD).
- Earlier this session: the proposal (rev 4) + implementation plan + the `incremental_step` skill were authored; governance amendments 017 (NFR-11/US-10 implementation-neutral) and 018 (US-09 AC-4 "quarantine") applied. All on this branch, pushed.
- Rebuild test suite: **56 green** (`uv run pytest -c pytest_new.ini`); conformance **579 green**.

### 3.4 Status — what is in progress

Nothing mid-edit. Last step (S3b) is fully shipped. The only uncommitted path is the untracked `docs/audits/raw_audits_results/` review scratch (see §2). The restart-save commit stages ONLY `restart.md`.

### 3.5 Next concrete step

Run `/incremental_step` for **S4 — sync-plan vocabulary** (`domain_model/sync_plan`: the `SyncIntent` types + `SyncResult` counts, per proposal §6). In S4's detail step, decide scope: the intents' payloads are partly consumer-driven (planner S5–S8 emits, executor S19 performs), so likely build the intent identity/result vocabulary and grow payloads with the planner (same YAGNI call as S3b) — confirm with the user.

### 3.6 Open questions / decisions awaiting the user

None blocking. (Execution-mode and S3b-scope decisions already made.)

## 4. Other tasks queued behind the active one

Per the plan (`docs/architecture_implementation_plan.md`), in order:
- **S4** — sync-plan vocabulary (SyncIntent + SyncResult). small. NEXT.
- **S5–S8** — the pure planner (recover_identity → reconcile_known → adopt_candidates → compute_sync_plan + guards). medium-large.
- **S9–S13** — translation core + dialects. medium.
- **S14–S16** — gateways (atomic_file_writer, canonical/state stores, archive+GC). medium.
- **S17–S19** — read phase, secret_policy, execute_sync_plan. medium.
- **S20–S23** — tools-as-data + registry, runtime_config, daemon/CLI, portable_library. medium.
- **S24–S25** — cutover (wire daemon to read→plan→execute; full conformance green) + retire old `src/` (directory rename, LOC measurement). large.

## 5. Files touched this session (skim list)

Rebuild (working set):
- `src_new/agents_sync/__init__.py` [created]
- `src_new/agents_sync/domain_model/__init__.py` [created]
- `src_new/agents_sync/domain_model/canonical_document.py` [created]
- `src_new/agents_sync/domain_model/artifact_identity.py` [created]
- `src_new/agents_sync/domain_model/artifact_naming.py` [created]
- `src_new/agents_sync/domain_model/tool_surface.py` [created]
- `tests_new/test_canonical_document.py` `tests_new/test_artifact_identity.py` `tests_new/test_artifact_naming.py` `tests_new/test_tool_surface.py` [created]
- `pytest_new.ini` [created]
- `pyproject.toml` [edited — testpaths, isort known-first-party, tests_new ignore, version]
- `scripts/ci.sh` [edited — mypy src_new + tests_new stages]

Docs/governance/skill (earlier this session):
- `docs/architecture_simplification_proposal.md` [created→rev4]
- `docs/architecture_implementation_plan.md` [created]
- `docs/stories/US-10-extensible-agentic_tool-registry.md` [edited]
- `docs/project_requirements.md` [edited — NFR-11]
- `docs/stories/US-09-concurrency-safety.md` [edited — AC-4]
- `docs/amendment/017-…md` `docs/amendment/018-…md` [created]
- `~/.claude/skills/incremental_step/SKILL.md` [created — the gate skill]

## 6. Anything else the next session needs to know

- Reference (do NOT modify) old-code equivalents when building rebuild modules: `src/agents_sync/canonical.py`, `identity.py`, `state.py` (slugify/_WINDOWS_RESERVED_BASENAMES), `agentic_tool_spec.py`, `shared_keyed_map_io.py`.
- The full local gate is `bash scripts/ci.sh` (ruff + mypy src + mypy src_new + pytest tests/ + pytest -c pytest_new.ini). Use it as the commit gate.
- `/bcp` is run per step; bumps are PATCH for rebuild modules; no git tag on this feature branch.
- The old P0–P8 TODO task list in the harness is **stale/superseded** by the plan's S1–S25; ignore it.
- 2026-06-05 (restart invocation note): user invoked `/restart` after S3b shipped, before starting S4.
