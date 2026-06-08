# Restart — 2026-06-08

> Last updated by Claude at 2026-06-08T01:10:00Z. This file is a session-handoff
> snapshot. A fresh session reading this should be able to resume work without
> further explanation.

## 0. Git pin (do not edit by hand)

- `head_sha`: 8a27e3aea34d32546289be2c86cc490ede7f4778
- `head_short`: 8a27e3a
- `branch`: fix/size-explosion-hardening
- `dirty`: true
- `dirty_summary`: 8 untracked (all under `docs/audits/` — review artifacts, intentionally NOT tracked)
- `remote_head`: 8a27e3aea34d32546289be2c86cc490ede7f4778 (up to date)
- `saved_at`: 2026-06-08T01:10:00Z

## 1. Read these first

Order matters:

- `AGENTS.md` (loaded via `~/.claude/CLAUDE.md`) — global engineering rules (POLA/KISS/YAGNI/DRY/SRP/SoC; §3 size limits; §8 fail-fast; §11 commits; §13 bash discipline).
- `docs/architecture_implementation_plan.md` — **the active plan**: the greenfield rebuild as gated steps S1–S25. Read the per-step gate, build location, and the S1–S25 table (S6 is now split into S6a/b/c; S7 narrowed; S8 expanded — see the rows).
- `docs/architecture_simplification_proposal.md` — rev 4 target design. **§7 is the live reference for the planner** (the simplified `compute_sync_plan`): §7.2 reconcile_known (the layered guard-pipeline), §7.3 candidate adoption, §7 step 4 the cross-artifact guards.
- `docs/project_description.md`, `docs/project_requirements.md` (FR/NFR), `docs/stories/US-*.md` — governing spec (US-03/04/06/07/09/11/12/13/15 are the planner's ACs).
- The `incremental_step` skill (`~/.claude/skills/incremental_step/SKILL.md`) — the per-step gate this work follows.

## 2. Working context (deltas not in the docs)

- **We are executing the rebuild one gated step per `/incremental_step` invocation.** User drives with "next"/"continue". Each step ships independently via `/bcp`.
- **Per-step gate:** detail (+confirm scope) → docs → tests + `/audit-tests` (only point tests change) → code → full CI (`bash scripts/ci.sh`) → `/code_and_tests_quality_review` on the diff (3 targets) → spotless (≤3 audit→fix loops) → commit + `/bcp`.
- **Greenfield-parallel:** new code in `src_new/agents_sync/`, tests in `tests_new/`. Old `src/` untouched; conformance suite (`tests/`, **579 green**) must stay green every step. Rebuild suite now **117 green** (`uv run pytest -c pytest_new.ini`). Cutover (S24–S25) is a directory rename.
- **Versioning:** each rebuild module is a PATCH `feat(rebuild)` (nothing shipped changes until cutover). Now at **0.7.9** (S7). **Always `uv lock` + stage `uv.lock` with the version bump** — see [[project_uvlock_version_bump]] memory (it lagged once).
- **`docs/audits/` is deliberately UNTRACKED** — the project does not track review artifacts. Every `/bcp` excludes them. Leave them; do not commit.
- **YAGNI growth pattern (established):** input/vocabulary types are grown additively with their consumer. New read-phase/observation fields default-valued (additive, no ripple); a value-type change (e.g. `ArtifactRecord.surfaces` → `RecordedSurface`) ripples mechanically and is re-audited.
- **THE KEY SIMPLIFICATION (user-driven, applies to S8):** anything **cross-artifact** is a guard in `compute_sync_plan` (S8) that *downgrades* a per-artifact intent — NOT logic inside `reconcile_known`/`adopt_candidates`. This is how collision, glitch, two-tool, and absorb_into_managed were all deferred to S8. S8 is where they all land.
- **Shared winner rule:** `domain_model/plan/winner_selection.freshest` (highest mtime, alphabetical tiebreak) is the one home for US-06 AC-4 / US-03 AC-7; both reconcile_known and adopt_candidates call it.

## 3. Active task

### 3.1 Goal

Rebuild `agents_sync` as the thin, clean, spec-compliant architecture in the proposal, in small independently-shippable gated steps, then cut over from the old `src/`.

### 3.2 Constraints specific to this task

- Hard: conformance suite green at every step; each step passes the full `incremental_step` gate to spotless (≤3 loops or escalate); governance artifacts (description/stories/AC/requirements) only change with explicit user approval of exact text.
- Soft: greenfield-parallel; PATCH bumps; additive YAGNI growth; cross-artifact logic → S8 guards.
- Out-of-scope (deferred): cross-identity slug merge/retire (US-12 AC-7) → S23 portable_library; the daemon-internal GC has no user-facing `prune`.

### 3.3 Status — what is done

**Phase A (pure domain core)** ✓ and **Phase B (the planner)** ✓ except S8:
- **S1–S3b** ✓ canonical_document, artifact_identity, artifact_naming, tool_surface (commits `26e3fae`…`5ab57e3`).
- **S4** ✓ sync_plan vocabulary — `IntentKind` enum + `SyncResult` (`b6fefa2`, 0.7.4).
- **S5** ✓ `plan/recover_identity` — managed-vs-candidate partition (`73df4e4`, 0.7.5). + `observation.SurfaceObservation`, `sync_state.SyncState`/`ArtifactRecord`.
- **S6a** ✓ `plan/reconcile_known` content rule + freeze (`c4e3e9e`, 0.7.6). Unified absorb/conflict/unchanged rule.
- **S6b** ✓ reconcile_known rename + remove (`9ff7a25`, 0.7.7).
- **S6c** ✓ reconcile_known canonical authority — rebuild + reproject (`2b59eda`, 0.7.8). reconcile_known **complete**: pipeline `freeze → rebuild → remove → content(absorb+rename|project) → reproject`.
- **S7** ✓ `plan/adopt_candidates` + `plan/winner_selection` (`8a27e3a`, 0.7.9). HEAD.
- All intent payloads emitted so far live in `sync_plan.py` (each tags its `IntentKind` via a `ClassVar`); `SyncIntent` is their union. Built: Freeze, AbsorbToolEdit, ProjectToTools, RenameArtifact, RemoveArtifact, ReprojectCanonical, RebuildCorruptCanonical, AdoptNewArtifact, ReportUnadoptable. **Not yet built: AbsorbIntoManaged, RejectCollision** (S8 emits them).

### 3.4 Status — what is in progress

Nothing mid-edit. S7 fully shipped at HEAD `8a27e3a`. The only uncommitted paths are the untracked `docs/audits/` review artifacts (8 files incl. `raw_audits_results/`) — intentionally not tracked. The restart-save commit stages ONLY `restart.md`.

### 3.5 Next concrete step

Run `/incremental_step` for **S8 — `compute_sync_plan` + cross-artifact guards** (`plan/compute_sync_plan`). It is the planner's capstone: (a) assemble the whole `SyncPlan` by calling recover_identity → reconcile_known (per managed artifact) → adopt_candidates; (b) implement EVERY deferred cross-artifact guard as a *downgrade* over the assembled intents: **two-tool guard** (US-07 AC-5: <2 available tools → drop destructive intents), **slug-clash / two-managed-same-key → `reject_collision`** (US-04 AC-5, US-03 AC-8), **candidate (kind,slug) matches a managed key → `absorb_into_managed`** (US-03 AC-6), **glitch (≥2 of a tool's recorded artifacts vanished) → `reproject_canonical`** instead of remove (US-11 AC-9), **private/framework predicates → no projection** (US-13/15). Grows `sync_plan` with `AbsorbIntoManaged` + `RejectCollision` payloads, and adds the `SyncPlan` container. **At the detail step, expect a scope/split discussion like S6** — S8 is large; consider splitting (e.g. S8a assembly + two-tool guard; S8b collision/absorb_into_managed; S8c glitch + private/framework). Confirm the split with the user.

### 3.6 Open questions / decisions awaiting the user

None blocking. The S8 split granularity is a detail-step decision (ask then).

## 4. Other tasks queued behind the active one

Per `docs/architecture_implementation_plan.md`, after S8:
- **S9–S13** — translation core + dialects (markdown, keyed-map, structured-text, global-rules, mcp). medium.
- **S14–S16** — gateways (atomic_file_writer, canonical/state stores, archive+GC). medium.
- **S17–S19** — read phase, secret_policy, execute_sync_plan. medium. (S17 read phase finally CONSTRUCTS the SurfaceObservation/StoredCanonical inputs the planner consumes; S8's `stored_canonical=None` default gets wired here.)
- **S20–S23** — tools-as-data + registry, runtime_config, daemon/CLI, portable_library (cross-identity retire lands in S23). medium.
- **S24–S25** — cutover (wire daemon to read→plan→execute; full conformance green) + retire old `src/` (directory rename, LOC measurement). large.

## 5. Files touched this session (skim list)

Rebuild source (created/edited this session, all under `src_new/agents_sync/domain_model/`):
- `sync_plan.py` [edited — grew from enum+result to 9 intent payloads + SyncIntent union]
- `observation.py` [edited — +content_digest/modified_time/parsed + ParseFailure]
- `sync_state.py` [edited — +RecordedSurface, ArtifactRecord +name +canonical_digest]
- `canonical_document.py` [edited — +CorruptCanonical marker]
- `plan/__init__.py` `plan/recover_identity.py` `plan/reconcile_known.py` `plan/adopt_candidates.py` `plan/winner_selection.py` [created]
Rebuild tests (`tests_new/`): test_sync_plan, test_observation, test_sync_state, test_canonical_document, test_recover_identity, test_reconcile_known, test_adopt_candidates, test_winner_selection [created/grown].
Docs: `docs/architecture_implementation_plan.md` (S5–S8 rows), `docs/architecture_simplification_proposal.md` (§7.2/§7.3/§7.4 reframed to the simplified model) [edited].
Memory: `project_uvlock_version_bump.md` [created].

## 6. Anything else the next session needs to know

- **Reference (do NOT modify) the old code** when building rebuild modules: `src/agents_sync/sync.py` (conflict winner = `sorted(key=(-mtime, tool_name))[0]`, glitch_tools, canonical_changed_out_of_band), `state.py`, `agentic_tool_spec.py`. The conformance suite encodes the behaviour S8 must preserve.
- **Commit gate is `bash scripts/ci.sh`** (ruff + mypy src + mypy src_new + pytest tests/ + pytest -c pytest_new.ini). The pre-push hook also runs it.
- **`docs/audits/` review-artifact handling is settled:** write the per-run JSON+report there, update `.last_code_review.json`, but NEVER stage them. The manual orchestration of `/code_and_tests_quality_review` (two auditor subagents in parallel → combined → report) is what each step has used; the marker's `git_head` was last set to `2b59eda` (pre-S7); update it during S8's review.
- **INFO-only review findings the auditor marks "no fix recommended" do NOT block spotless** — record the disposition and ship (established on S6c). Genuine coverage-gap INFO (like S6a's) DO get closed.
- 2026-06-08 (restart `save` note): user chose to save and stop after six spotless increments (S4→S7) this session; S8 is the clean next step in a fresh context window.
