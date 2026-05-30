# Amendment 002 — Cross-machine config merge: slug-reconciling, atomic import

- status: reqs-validated (all governance applied; code deferred to a focused pass)
- governance applied: US-12 AC-5/17/18, FR-12, FR-13, NFR-16, US-11 AC-8, US-05 AC-5;
  architecture §6.1 marked planned-not-built

## Validated decisions (2026-05-30)

- **Decision A → canonical-only import.** AC-5 rewritten: import writes canonicals +
  state stubs only, atomically; the next `sync_once` renders. No tool-root writes.
- **AC-17 / AC-18 approved as drafted** (cross-identity slug merge; preview honesty).
- **FR-12 / FR-13 approved**, reworded as clean self-contained high-level rules (no
  US/AC/NFR cross-refs, no implementation terms). FR-13 is **per-artifact** atomicity
  (fault-isolated), not whole-import all-or-nothing.
- **Data preservation**: the *tool-side* bytes are already covered by NFR-01 ("no loss
  of user-authored content under any operation") + NFR-07, and AC-17 keeps the explicit
  loser-archiving clause. The *canonical store* was **not** previously an archived
  surface — the Expansion below adds US-05 AC-5 to extend the no-`rm` rule to a dropped
  canonical (with a defined `_canonical` archive path). No new top-level requirement is
  needed; NFR-01/NFR-07 already mandate it, US-05 AC-5 makes the canonical path concrete.

## Re-audit fixes (2026-05-30, architecture-critic round 2)

A second architecture audit closed 8/10 issues and found 2 more; all now fixed
(user-validated):
- **AC-17 tie fallback**: the pure cross-host merge (two imported candidates,
  neither local, `last_modified` tie) had no resolver — "ties favour local"
  selects nobody. Added a lexicographic-by-`customization_artifact_id` last resort.
- **AC-8 digest source**: the recorded digest is now stated to be the on-disk
  post-write (post-normalisation) bytes, closing an NFR-05 phantom-delta loop.
- **US-11 AC-9 (new, framework-removal safety)**: an uninstalled framework that
  leaves a present-but-empty root keeps the tool `available` (root reachability is
  content-blind), so today its emptiness reads as a mass user deletion and
  propagates removal. AC-9 freezes a bulk all-gone-at-once disappearance on an
  available tool (no removal, no re-projection); partial disappearance still
  propagates. Verified the gap against `tool_status.refresh` and
  `removal_propagator` ("every entry dropped ⇒ pair_id dropped" — no prior guard).

- branch: feat/v0.5-cross-machine-merge
- date: 2026-05-30
- supersedes / relates to: US-12 (AC-5, AC-7, AC-10, AC-11), US-03 (AC-3 reconciliation),
  US-06 (mtime conflict policy), NFR-03 (atomic visibility)

## Motivation

Goal: **"same config everywhere"** — a user running agents_sync on two
workstations (e.g. `laptop` and `big`) wants both to converge to the same
library. Each machine mints its own random `customization_artifact_id` for
locally-created artifacts, so the *same logical* skill (`user-questions`) has a
*different identity* on each machine. Merging the two libraries means reconciling
across that identity boundary, keyed by `(customization_type, target_slug(name))`
— the same key US-03 AC-3 uses within a machine.

A sandbox probe (tmp/dup_test.py) of the current import against a snapshot whose
artifacts are duplicated under fresh pair_ids found three gaps:

1. **`_classify` only dedups against pre-import local state**, never within the
   imported set: two imported artifacts with the same `(kind, slug)` are both
   classified "accept."
2. **`preview_import` is blind to it** — reports `would_overwrite=0`, false
   confidence before a run that aborts.
3. **Import is non-atomic** — it renders tool-side files one tool at a time, then
   writes `state.json` once at the end. The second same-slug render trips
   `assert_target_available` → `FileExistsError`; the run aborts having written
   orphan **tool-side** files (12 in the probe) with **no** state backing them,
   which the next daemon poll then adopts as fresh pairs.

## Pre-existing governance defect found

US-12 contradicts itself on whether import touches tool roots:

- **AC-5** (and the implementation): import "is rendered onto every … agentic_tool
  … returns only after every projection is on disk."
- **Notes (¶ line 62)**: "import **never** writes to an agentic_tool root directly.
  It writes canonicals and state stubs only; the next polling cycle … adopts them."

The two cannot both hold. The render-on-import reading (AC-5) is what makes gap #3
non-atomic. This must be resolved before the feature is built.

## Principle / decision

**Import is a merge, not an overwrite: it reconciles every candidate — imported
*and* local — by `(customization_type, target_slug(name))`, collapsing same-slug
candidates to a single winner by wall-clock `last_modified` (US-06 semantics; the
host-local `generation` counter is not a cross-host discriminator), archiving the
losers, and it is **per-artifact atomic** — each artifact lands completely or not
at all, a failure on one not affecting the rest (FR-13).**

## Proposed governance edits (require user validation)

### Decision A — resolve the AC-5 / Notes contradiction (US-12)

**Recommended: canonical-only import (adopt the Notes; amend AC-5).** Import writes
**canonicals + state stubs only**, atomically; the next poll renders via the
unchanged adoption pipeline. This makes atomicity trivial (only the small
canonical store + `state.json` are written, never N tool dirs), removes the
orphan-tool-file failure mode, and matches the Notes' stated rationale.
*Alternative:* keep render-on-import (AC-5) and add staged-render-with-rollback —
more code, harder atomicity. **Validation needed: which direction.**

Proposed AC-5 rewrite (canonical-only):
> AC-5 [Normal]: … Then every canonical document in the zip is written to the
> local state directory and `state.json` is updated with a state stub per imported
> artifact; **import does not write to any agentic_tool root** — the next
> `sync_once` renders each imported artifact onto every enabled, supporting,
> available agentic_tool via the unchanged adoption pipeline. The command returns
> after the canonical store and `state.json` are durably written.

### Decision B — add intra-import slug reconciliation (US-12, new AC)

> AC-17 [Normal — cross-identity merge]: Given an import zip in which two or more
> canonicals share the same `(customization_type, target_slug(name))` but carry
> **different** `customization_artifact_id`s (e.g. the same skill independently
> created on two machines), When `import` runs, Then they are reconciled into a
> **single** managed artifact: the candidate with the higher wall-clock
> `last_modified` wins, ties favouring the local artifact (host-local `generation`
> is not a cross-host discriminator, per US-06); the winner keeps its
> `customization_artifact_id`, every **losing candidate's id is retired** (not
> written to canonical or `state`), its bytes archived (NFR-01) under the winner's
> id; no two managed artifacts share a slug after import (US-03 AC-8 never
> provoked); re-import is a no-op. This reconciliation applies across the imported
> set and against local state uniformly.

### Decision C — preview reports merges (US-12, amend AC + add)

> AC-18 [Normal — preview honesty]: Given an import that would merge or displace
> any local artifact, When the user runs the import, Then a preview enumerates
> every imported `customization_artifact_id` that will merge-by-slug or overwrite a
> local pair **before** any disk write, including intra-import slug merges.

### Requirements (US-12 realises; add to project_requirements.md)

_(Final validated text, as applied to `project_requirements.md` — these supersede
the earlier drafts; reworded as clean self-contained high-level rules.)_

> - **FR-12** (Import convergence): The daemon **shall** import a customization
>   library idempotently: candidate customization_artifacts that resolve to the
>   same customization_type and name **shall** be reconciled into a single managed
>   customization_artifact, the most recently modified candidate prevailing and
>   ties resolved in favour of the locally-present artifact. Re-importing a library
>   exported from an unchanged state **shall** produce no change.
> - **FR-13** (Per-artifact atomic import): The daemon **shall** import each
>   customization_artifact atomically and in isolation: a customization_artifact
>   **shall** be either fully imported or not imported at all, and a failure to
>   import one customization_artifact **shall not** affect customization_artifacts
>   that have already imported successfully.

## Expansion (2026-05-30) — canonical store is the source of truth

Implementing canonical-only import revealed that the daemon projects only from
**on-disk tool files**; a canonical with no disk presence is inert (never
rendered, never removed). Rather than work around it, the project inverts the
arrow: **the canonical store is the authoritative source of truth; tool-side
files are projections derived from it.** Decisions:

1. **Canonical authority + round-trip losslessness** (not byte-identical): parsing
   a tool file into canonical loses no user-authored information; a fresh
   projection reproduces every declared field and value (formatting may normalise).
   New requirement **NFR-16**.
2. **Project disk-absent canonicals**: `sync_once` gains a step that projects any
   managed artifact present in state+canonical but on zero tool disks (freshly
   imported, or a newly-available tool) onto every enabled/supporting/available
   tool via the adoption pipeline.
3. **Heal vs delete (state-based)**: absence of a tool file that state **never
   recorded** for that tool ⇒ project/heal from canonical; absence of a file state
   **did record** ⇒ authored deletion ⇒ propagate removal (unchanged FR-04). The
   import case is purely the heal kind (new to this host, zero tools).
4. **Archive canonical on drop**: when a canonical record is dropped (e.g. deletion
   propagation), it is archived first — data preservation extended from tool-side
   bytes to the canonical store (NFR-01 / NFR-07).

With (2), canonical-only import (AC-5, Decision A) is sound: import writes
canonical + state stub atomically; the next `sync_once` projects it. The
cross-machine merge (AC-17) then sits on top unchanged.

### Additional governance edits (require validation)

- **NFR-16 (Canonical authority & fidelity)** — new requirement (text below).
- **US-11** (removal) / **US-03** (adoption): an AC for project-disk-absent and the
  heal-vs-delete state rule.
- **US-05** (archive) or removal story: an AC for archiving a dropped canonical.

## Design edits (architecture — applied after validation)

`docs/architecture.md` §6 / portable_archive section: document that `_classify`
folds an incremental slug index (local + already-accepted) so cross-identity
duplicates reconcile to one pair; that import writes canonical + state only
(Decision A) and stages the write atomically; and that rendering is deferred to
`sync_once`.

## Implementation plan

1. `portable_archive._classify`: maintain a mutable slug index seeded from local
   state and updated as each candidate is accepted; on same-slug-different-id,
   run the US-06 decision, mark the loser archived-not-written.
2. `portable_archive.import_from_zip`: write canonicals + state stubs only
   (Decision A); stage to a temp dir and swap atomically; archive losers.
3. `portable_archive.preview_import`: report intra-import + local slug merges.
4. Remove the in-import `render_to_agentic_tool` call (Decision A) — rendering
   moves to the next `sync_once`.

## Test plan

- Cross-identity merge: two canonicals, same slug, different ids → one managed pair,
  loser archived, no AC-8 block on the next poll (FR-12 / AC-17).
- Idempotent round-trip with duplicates: export→import→import is stable (AC-11).
- Atomic failure: induce a mid-import error → state unchanged, no orphan tool files
  (FR-13 / AC-10).
- Preview honesty: preview lists the merges before disk writes (AC-18).
- The tmp/dup_test.py scenario now succeeds (merges to 5, no crash).

## Verification

Full `uv run pytest`, `mypy --strict`, `ruff`. The synthetic 10→5 merge and the
live 19-pair round-trip both clean; daemon stays `blocked=0`.
