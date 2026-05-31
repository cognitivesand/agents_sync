# Amendment 007 — Structural refactor: decompose the adoption God-module and long functions

- status: in-progress
- branch: feat/v0.5-cross-machine-merge
- date: 2026-05-31
- relates to: v0.6 code-quality audit (findings CQ-01..CQ-05)

## Motivation

The code-quality audit found the project's own size caps (functions ≤40 lines,
modules ≤300) breached in the highest-blast-radius code:

- **CQ-01** `adoption/engine.py` — 650-line God module, ~5 responsibility clusters.
- **CQ-03** three near-identical render-loop functions (extend / project / reproject).
- **CQ-02** `sync.Syncer.sync_once` — ~52 executable lines, fuses four phases.
- **CQ-04** `portable_archive.import_from_zip` — ~62 executable lines, five concerns.
- **CQ-05** `portable_archive.py` — 516-line module.

Security and correctness scored 1.0; these are structural-maintainability defects.

## Principle / decision

Behaviour-preserving decomposition only. No contract, behaviour, or governance
change — the full suite must be identical-green before and after each step. Extract
along the existing composed-mixin / helper-function patterns already in the code.

## Proposed governance edits

None — pure refactor.

## Implementation plan (incremental, one commit per step)

1. **CQ-01/CQ-03** — extract the canonical-projection trio (`_extend_to_new_tools`,
   `project_from_canonical`, `reproject_canonical`) into a `CanonicalProjectionMixin`
   (`adoption/canonical_projection.py`), with a shared `_render_canonical_one` helper
   that dedups the reserved-check + render call while preserving each method's exact
   behaviour (notably `reproject` keeps its no-reserved-check path via
   `check_reserved=False`). Extend the `_AdoptionHost` typing Protocol accordingly.
2. **CQ-02** — extract `sync_once`'s phases into named helper methods.
3. **CQ-04** — extract `import_from_zip`'s secret-filter and staging-promote concerns
   into helpers.
4. Re-tabulate the architecture §4 module map (doc-debt from amendment 005).

## Test plan

No new behaviour ⇒ no new tests; the existing suite (516) is the safety net, run
identical-green after every step.

## Verification

Full `uv run pytest` + `mypy --strict` + `ruff` green after each step.

## Progress

- Step 1 (CQ-01/CQ-03) applied: engine.py 650 → 544 lines; new
  `canonical_projection.py` (196). Suite 516 green, mypy/ruff clean.
- Step 2 (CQ-02) applied: `sync_once` split into `_process_discovered_pairs`,
  `_reconcile_deleted_pairs`, `_record_canonical_baselines` (each ≤40 lines);
  orchestrator ~28 lines. Suite 516 green, mypy/ruff clean.
- Step 3 (CQ-04) applied: `import_from_zip` split into
  `_filter_secret_bearing_decisions`, `_stage_and_promote_canonicals`,
  `_apply_import_to_state`; orchestrator now ~20 lines. Suite 516 green,
  mypy/ruff clean. (Observation, not changed per the surgical rule: the
  `tool_status = ToolStatusTracker(...).refresh()` in `import_from_zip` is
  pre-existing dead code in the canonical-only path — flagged, not removed.)
