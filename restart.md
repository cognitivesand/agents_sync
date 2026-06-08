# Restart — 2026-06-08

> Last updated by Claude at 2026-06-08T14:30:00Z. Session-handoff snapshot. A fresh
> session reading this should be able to resume without further explanation.

## 0. Git pin (do not edit by hand)

- `head_sha`: f49d284323d7aca9078f858fca0ae485d282061a
- `head_short`: f49d284
- `branch`: fix/size-explosion-hardening
- `dirty`: true
- `dirty_summary`: 13 untracked (all under `docs/audits/` — review artifacts, intentionally NOT tracked)
- `remote_head`: f49d284323d7aca9078f858fca0ae485d282061a (pushed, up to date)
- `saved_at`: 2026-06-08T14:30:00Z

## 1. Read these first

Order matters:

- `AGENTS.md` (via `~/.claude/CLAUDE.md`) — global rules (POLA/KISS/YAGNI/DRY/SRP/SoC; §3 size limits; §8 fail-fast; §11 commits; §13 bash discipline).
- `docs/architecture_implementation_plan.md` — **the active plan**: greenfield rebuild as gated steps S1–S25. Phase B (planner) is **done through S8**; the S8 row is now split into **S8a/b/c/d**. Next is **Phase C, S9**.
- `docs/architecture_simplification_proposal.md` — rev 4 target design. §7 = the planner (now fully built); §10 = the **two centralized translation functions** (`file_to_canonical`/`canonical_to_file`/`extract_artifact_id`) which S9 begins; §12 cross-cutting homes.
- `docs/project_description.md`, `docs/project_requirements.md` (FR/NFR), `docs/stories/US-*.md` — governing spec.
- The `incremental_step` skill (`~/.claude/skills/incremental_step/SKILL.md`) — the per-step gate this work follows.
- `docs/amendment/019-us13-ac4-retire-private-flag.md` — this session's governance amendment (see §2).

## 2. Working context (deltas not in the docs)

- **We execute the rebuild one gated step per `/incremental_step`.** User drives with "next"/"continue". Each step ships via `/bcp`.
- **Per-step gate:** detail (+confirm scope/split) → docs → tests + `/audit-tests` (only point tests change) → code → full CI (`bash scripts/ci.sh`) → `/code_and_tests_quality_review` on the diff (3 targets) → spotless (≤3 audit→fix loops) → commit + `/bcp`.
- **Greenfield-parallel:** new code in `src_new/agents_sync/`, tests in `tests_new/`. Old `src/` untouched; conformance suite (`tests/`, **579 green**) must stay green every step. Rebuild suite now **179 green** (`uv run pytest -c pytest_new.ini`). Cutover (S24–S25) is a directory rename.
- **Versioning:** each rebuild step is a **PATCH** `feat(rebuild)` (nothing shipped changes until cutover). Now at **0.7.15**. **Always `uv lock` + stage `uv.lock` with the bump** — see [[project_uvlock_version_bump]].
- **`docs/audits/` is deliberately UNTRACKED** — never stage it; every `/bcp` excludes it. The `code_and_tests_quality_review`/`audit-tests` artifacts live there; `.last_code_review.json` marker is at `2026_06_08__13_56` / `full` mode.
- **THE KEY SIMPLIFICATION (applies through the planner):** anything **cross-artifact** is a guard in `compute_sync_plan` that *downgrades* a per-artifact intent — never logic inside `reconcile_known`/`adopt_candidates`. All four guards now live in S8.
- **Established lightweight review practice:** the per-step `/code_and_tests_quality_review` is run by hand-orchestrating the auditor subagents (code-quality + test-quality in parallel → combine → markdown report under `docs/audits/` → remediate inline). The heavy resolver+deputy Phase B is NOT run per increment; INFO no-fix findings don't block.
- **This session's two big side-quests (both DONE):**
  1. **Amendment 019 — retired the user-facing `private` flag (YAGNI).** US-13 AC-4 retired; US-15 de-referenced (framework-specific behaviour UNCHANGED — it stays, lands at S12); integration-protocol contract + proposal §4/§7/§12/§17 aligned; `private` field removed from `src_new` canonical. An architecture-critic audit + deputy adjudication confirmed coherence. **Feedback memory written: [[feedback_spec_code_alignment]]** (removing behaviour requires updating the spec in the same change; grep the whole repo for dangling refs).
  2. **Full Phase-A+B audit + "everything" remediation.** `intent_kind` discriminator rename (was `kind`); `ArtifactRecord`/`SyncState` content `__hash__`; `ReconciliationKey` type alias (`artifact_naming.py`); `freshest([])` fail-loud; +27 coverage tests. Kept (justified, do NOT re-open): `AbsorbIntoManaged.sources` flat tuple (absorb has no winner). Skipped (judgment): the data-clumps context object (no defect) + 3 INFO no-defect notes.

## 3. Active task

### 3.1 Goal

Rebuild `agents_sync` as the thin, clean, spec-compliant architecture in the proposal, in small independently-shippable gated steps, then cut over from the old `src/`.

### 3.2 Constraints

- Hard: conformance suite green every step; full `incremental_step` gate to spotless (≤3 loops or escalate); governance artifacts (description/stories/AC/requirements) change only with explicit user approval of exact text ([[feedback_governance_approval]]) — and if behaviour is removed, the spec is updated in the same change ([[feedback_spec_code_alignment]]).
- Soft: greenfield-parallel; PATCH bumps; additive YAGNI growth.

### 3.3 Status — what is done

**Phase A (domain core) ✓ and Phase B (the planner) ✓ — the pure planner is complete.**
- S1–S7 ✓ (canonical_document, artifact_identity, artifact_naming, tool_surface, sync_plan vocab, recover_identity, reconcile_known, adopt_candidates, winner_selection).
- **S8 ✓ (all four sub-steps):** S8a assembly + two-tool guard (`8d…`/0.7.11→`4722c50`), S8b collision→reject_collision (`a57f76d`, 0.7.12), S8c absorb_into_managed (`fd0597d`, 0.7.13), S8d glitch→reproject (`10b5731`, 0.7.14).
- **Amendment 019** (private retirement): `dc819e0`, `ba947b3`, `a1d860d`, shipped 0.7.10 `8d46010`.
- **Full-audit remediation:** `0ab7780` (code), `b92f1e9` (tests), `f49d284` (release 0.7.15, HEAD). Both former AUDIT_WEAK units re-audited to PASS.

### 3.4 Status — what is in progress

Nothing mid-edit. HEAD `f49d284` is clean and pushed. Only untracked `docs/audits/` artifacts remain (13 files — intentionally not tracked). This restart-save commit stages ONLY `restart.md`.

### 3.5 Next concrete step

Run `/incremental_step` for **S9 — translation core + markdown_frontmatter dialect** (Phase C, `translation` + `dialects/markdown_frontmatter`). Build `file_to_canonical` / `canonical_to_file` / `extract_artifact_id` dispatching on `SurfaceFormat.dialect`, with the markdown front-matter dialect (YAML front-matter + Markdown body: split → map known_fields → keep unknowns in per_tool_extra → reassemble). Spec/test focus: round-trip (`parse(render(c)) == c`), no-foreign-leak (NFR-06/16), malformed→raise (read phase catches → ParseFailure), id-in-isolation (`extract_artifact_id` never raises). At the detail step, expect to grow `SurfaceFormat` with the recipe fields it needs (known_fields/tool_only_fields — additive YAGNI growth) and confirm scope. Note: this is the first step that touches **bytes**, so it is no longer pure-domain — still no I/O (operates on `text: str`), the read phase (S17) supplies the bytes.

### 3.6 Open questions / decisions awaiting the user

None blocking. S9's `SurfaceFormat` recipe-field growth is a detail-step decision (decide then).

## 4. Other tasks queued behind the active one

Per `docs/architecture_implementation_plan.md`, after S9:
- **S10–S13** — dialects (keyed-map/mcp, structured-text, global-rules incl. framework-specific hold-back US-15, mcp specifics). medium.
- **S14–S16** — gateways (atomic_file_writer, canonical/state stores, archive+GC). medium.
- **S17–S19** — read phase, secret_policy, execute_sync_plan. S17 constructs the SurfaceObservation/StoredCanonical inputs the planner consumes (wires the `stored_canonicals` map + `available_tool_count`); the private/framework projection predicate consuming a read-phase flag lands around S12/S17. medium.
- **S20–S23** — tools-as-data + registry, runtime_config, daemon/CLI, portable_library. medium.
- **S24–S25** — cutover (wire daemon to read→plan→execute; full conformance green) + retire old `src/` (directory rename, LOC measurement). large.

## 5. Files touched this session (skim list)

Rebuild source (all under `src_new/agents_sync/domain_model/`): `plan/compute_sync_plan.py` [created — the S8 capstone: assembly + 4 guards], `sync_plan.py` [grew — SyncPlan container, AbsorbIntoManaged + RejectCollision payloads, intent_kind rename, ReconciliationKey], `plan/reconcile_known.py` [grew — exposed `vanished_tools`], `sync_state.py` [grew — `__hash__`], `artifact_naming.py` [grew — `ReconciliationKey` alias], `plan/winner_selection.py` [grew — fail-loud], `canonical_document.py` [edited — removed `private`, `__hash__` docstring].
Rebuild tests (`tests_new/`): test_compute_sync_plan [created + grown to 179-suite's largest], test_sync_plan, test_reconcile_known, test_winner_selection, test_observation, test_artifact_identity, test_canonical_document, test_adopt_candidates [grown].
Governance/design: `docs/stories/US-13*.md`, `docs/stories/US-15*.md`, `docs/agentic_tool_integration_protocol.md`, `docs/architecture_simplification_proposal.md`, `docs/architecture_implementation_plan.md` [edited]; `docs/amendment/019-*.md` [created].
Memory: `feedback_spec_code_alignment.md` [created].

## 6. Anything else the next session needs to know

- **Reference (do NOT modify) the old code** when building rebuild modules: `src/agents_sync/markdown_io.py`/`rules_io.py`/`*_io.py` (the per-tool parse/render the new centralized `translation` replaces), `canonical.py`. The conformance suite encodes the round-trip behaviour S9+ must preserve.
- **Commit gate is `bash scripts/ci.sh`** (ruff + mypy src + mypy src_new + pytest tests/ + pytest -c pytest_new.ini). The pre-push hook also runs it.
- **`docs/audits/` review-artifact handling is settled:** write per-run JSON+report there, update `.last_code_review.json`, NEVER stage them.
- **Ruff prefers PEP 695 `type X = ...`** over `TypeAlias` (bit me on `ReconciliationKey`); and wraps long lines via `uv run ruff format <file>`.
- 2026-06-08 (restart `save` note): user asked to restart after completing all of Phase B (S8a–d), amendment 019, and the full-audit "everything" remediation this session (shipped 0.7.10→0.7.15). S9 (Phase C translation) is the clean next step in a fresh context window.
