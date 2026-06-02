# Restart — 2026-06-01 — Canonical metadata model (008) + mtime_wins-only (009): governance validated, ready to apply

> Session-handoff snapshot, written for a machine switch mid-`code_change`. A fresh
> session reading this + the docs in §1 can apply the governance in §3.4 and execute
> the code plan in §5 without re-deriving anything. **§3.4 is AUTHORITATIVE** — it
> holds the final agreed text and supersedes the older draft wording still sitting in
> the amendment records (008/009 governance-edit sections). Reconcile the amendments
> to §3.4 when applying.
>
> User's standing instruction this session — the mandated order:
> **0 define (US/CS, REQS, objectives) → 1 plan → 2 align arch+README+all docs/ →
> 3 build/adapt tests → 4 code → 5 verify.** Governance is validated; do NOT widen it
> without asking. Two principles drove every edit: **DRY** (one fact, one home) and
> **KISS** (no restating what another AC/FR/glossary entry already governs).

## 0. Git pin (do not edit by hand)

- `head_sha`: 5f28bf5 (branch `feat/v0.5-cross-machine-merge`, pushed)
- `branch`: feat/v0.5-cross-machine-merge
- `dirty`: true — only `?? tmp/` (untracked scratch, NOT gitignored — see §6) and this
  `restart.md` (committed separately by the save). Tracked tree is otherwise clean.
- The amendment proposals 008 (edited) + 009 (new) are COMMITTED at `5f28bf5`
  ("docs(amendment): metadata model (008) + mtime_wins-only (009) governance proposals").
- Earlier this session: `bd11a0a` archived the prior restart; `5f28bf5` added the
  amendment proposals. Version is still 0.5.7.

## 1. Read first (in order)

- `docs/amendment/008-single-writer-state-canonical-adoption.md` — the metadata-model
  design. Read "Canonical metadata model" + "DRY refinement" sections. (Its
  "Governance edits" section holds OLDER draft text — §3.4 here supersedes it.)
- `docs/amendment/009-import-mtime-wins-only.md` — remove configurable collision
  strategy; mtime_wins is the single fixed rule. (Same caveat: §3.4 here is final.)
- `docs/stories/US-12-portable-library-snapshot.md` — the story being edited.
- `docs/project_requirements.md` — FR-12, FR-14, FR-15, FR-16, NFR-01/05/06/07.
- `docs/project_description.md` — Glossary (Canonical entry ~line 119); objectives
  live here too (no objectives file). Vision/objectives unchanged.

## 2. Working context (what the chat established, not in the docs)

- The metadata model (008) resolves finding A's leftover: single-writer state left
  `import` no channel to convey `last_modified`. Fix: `last_modified`/`generation`
  become a **nested `metadata` block on the canonical**; FR-14 change-detection digest
  is computed over **content only** (a metadata-only diff → no reproject, no archive).
- **DRY decision (user, this session):** `last_modified`/`generation` live **only** in
  the canonical metadata — they LEAVE the `state.json` schema entirely. Confirmed safe:
  `engine.py` (runtime US-06 conflict) does NOT read them; only export, import-collision
  compare, and adoption do, and each has the canonical on disk. This SUPERSEDES the prior
  restart's "sync state from canonical metadata each poll" step (nothing in state to sync).
- **mtime_wins-only decision (user, this session):** the 3-way `import_collision_strategy`
  (skip/mtime_wins/overwrite) + `--collision-strategy` CLI flag were ORIGINAL to US-12
  (git-traced to commit 69449a4 — not a silent creep), so removing them is a real new
  decision → amendment 009. mtime_wins becomes the single hardcoded rule.
- **KISS/DRY pruning of US-12:** removed redundant ACs rather than reword them. Each
  removed AC's behavior re-homes to a requirement/NFR (see §3.4). Numbers are RETIRED
  (gaps left) — renumbering would break AC-17/18/19 + code/test references.
- The user said "ok for now will need a bit more refinement" — treat §3.4 as validated
  but offer ONE more refinement pass before applying if anything in §3.6 lands.

## 3. Active task

### 3.1 Goal
Close finding A's residue cleanly: make the canonical self-contained (metadata block,
content-only change detection, DRY — values only in the canonical), and simplify US-12
import to a single non-configurable `mtime_wins` rule. Ship governance → docs → tests →
code → verify, in that order.

### 3.2 Constraints
- Hard: the mandated order (§ top). Governance (US/REQS/description) only with user
  validation — already given for §3.4, provisionally. DRY + KISS. Never delete files
  (§6); never `git add -A`. Surgical changes; ≤40-line funcs, ≤300-line files.
- Soft: prefer removing a redundant AC over rewording it; reference the canonical home
  (FR-12, NFR-01, glossary) instead of restating.
- Out of scope: change-history / per-tool file timestamps in the metadata block
  (deferred per 008); any architecture rewrite beyond what §3.4/§5 name.

### 3.3 Done (committed)
- Finding A core fix (single-writer state, import canonical-only, daemon adopts orphans)
  — committed earlier (`aded7b5`); US-12 AC-5 reworded + FR-16 added + validated.
- Amendment proposals 008 (metadata model + DRY) and 009 (mtime_wins-only) — committed
  `5f28bf5`.
- Governance disposition negotiated to final (§3.4), provisionally validated by user.

### 3.4 AUTHORITATIVE final governance disposition (apply verbatim)

**LOCKED by user** — G1, G2, G3. **Validated (provisional)** — the US-12 edits.

**G1 — `project_description.md` glossary, replace the `Canonical` entry with:**
> - **Canonical** — per-customization_artifact JSON document storing the union of fields from every agentic_tool; the lossless intermediate that drives every renderer. It carries the canonical content itself as well as a nested `metadata` block.

**G2 — `project_description.md` glossary, add two entries after `Canonical`:**
> - **`last_modified`** — POSIX timestamp (float) of when a customization_artifact's user content was last changed, not when its files were last written. Carried in the canonical's `metadata` block.
> - **`generation`** — host-local monotonic counter, incremented on each content change of a customization_artifact. Carried in the canonical's `metadata` block.

**G3 — `project_requirements.md`, replace FR-14 with:**
> - **FR-14** (Canonical-change detection): The daemon **shall** detect when a customization_artifact's canonical content has changed independently of its tool-side files and **shall** re-project the canonical onto every supporting available tool, preserving any displaced bytes. Change detection **shall** be computed over canonical content only, not on the metadata.

**US-12 edits** (`docs/stories/US-12-portable-library-snapshot.md`):

- **AC-3 — REMOVE** (current line 25). Number retired (leave a gap, no stub). Covered by
  AC-1 (one canonical entry per artifact + "source state directory unchanged") plus the
  metadata-in-canonical model (the exported canonical carries its own `last_modified`).
- **AC-6 — replace with:**
  > - [ ] AC-6 [Normal]: Given the import zip carries a customization_artifact with the same `customization_artifact_id` as a locally-managed one, When `import` runs, Then the candidate that prevails is the one with the higher `last_modified` value stored in the metadata.
- **AC-7 — replace with** (drop the trailing NFR-01 archive sentence; NFR-01 is universal):
  > - [ ] AC-7 [Normal]: Given the import zip carries a customization_artifact whose `target_slug(name)` collides with a *different* locally-managed artifact under the same `customization_type`, When `import` runs, Then the same `mtime_wins` reconciliation is applied (treating the slug collision identically to a `customization_artifact_id` collision).
- **AC-8 — REMOVE entirely** (current line 36, the `--collision-strategy` CLI flag AC).
  Number retired (gap, no stub).
- **AC-11 — REMOVE entirely** (current line 42, the round-trip no-op). Number retired
  (gap). Covered by FR-12 ("Re-importing a library exported from an unchanged state shall
  produce no change").
- **AC-17 — replace with** (stripped to the cross-identity merge + which-id-survives;
  everything else points to its home):
  > - [ ] AC-17 [Normal — cross-identity merge]: Given an import zip in which two or more canonicals share the same `(customization_type, target_slug(name))` but carry **different** `customization_artifact_id`s (e.g. the same skill created independently on two machines), When `import` runs, Then they are reconciled into a **single** managed customization_artifact by the `mtime_wins` rule (FR-12); the surviving content is written under the locally-present `customization_artifact_id` when one exists at that slug — reusing the local id so on-disk files are not re-stamped — otherwise under the winning candidate's id, and every other candidate's id is retired. This reconciliation applies both within the imported set and against the local library.
- **AC-18 — replace with** (drop the "under `overwrite`/`mtime_wins`" qualifier):
  > - [ ] AC-18 [Normal — preview honesty]: Given an import that would merge or displace any local customization_artifact, When the user runs `agents-sync import`, Then a preview enumerates, **before any disk write**, every imported `customization_artifact_id` that will merge-by-slug or overwrite a local pair, including intra-import slug merges; the run requires `--force` if any local pair would be displaced.
- **US-12 Notes (current line 70) — replace the `import_collision_strategy` paragraph with:**
  > Import reconciliation is fixed at `mtime_wins`, mirroring the daemon's runtime conflict-resolution rule (US-06): the most recently modified content prevails, ties favouring the locally-present artifact. It is not configurable — there is no config key or CLI flag.

**Requirements need NO change** beyond G3: FR-12 already mandates mtime_wins + ties-to-local
+ "deterministic total order" for cross-host ties; the `import_collision_strategy` key was
never a requirement.

**Relocations to `architecture.md`** (step 2 — design, not governance; nothing lost):
- The **lexicographic-by-`customization_artifact_id`** cross-host tiebreaker (the concrete
  realization of FR-12's "deterministic total order") moves OUT of AC-17 INTO architecture.
- Note as design rationale that `generation` is host-local and not a cross-host discriminator.

**When applying: also reconcile amendments 008 + 009** governance-edit sections to this
final text (they still show earlier drafts), then set 008/009 status appropriately.

### 3.5 Next concrete step
Apply G1, G2, G3 to `project_description.md` / `project_requirements.md`, and the US-12
edits to `docs/stories/US-12-portable-library-snapshot.md`, exactly as in §3.4. Then
reconcile amendments 008/009 to match. (Per the mandated order this is step "0 define"
completing → then step 2 align arch/README/docs.) Optionally do the §3.6 refinement pass
with the user first.

### 3.6 Open — the "bit more refinement" the user flagged
Provisionally validated, but the user wants one more look. Likely candidates:
- **AC-19** still says "under `mtime_wins` (with `--force` …)"; with mtime_wins the only
  mode, "under mtime_wins" is now redundant — consider trimming to "(with `--force` where
  AC-18 requires it)".
- Whether **AC-6** is even needed given FR-12 already states winner selection (AC vs FR
  level — currently keeping AC-6 as the story-level statement of the same-id case).
- Any further DRY sweep of US-12 ACs the user spots.
Offer this pass before applying, then apply.

## 4. Queued behind governance (code) — ordered
1. **Step 2 align** — `architecture.md` (§6.1 import: canonical-only, mtime_wins fixed,
   content-only FR-14 digest, metadata block; relocate the lexicographic tiebreaker),
   `README.md` (remove `--collision-strategy` / `import_collision_strategy` from import +
   config sections), other `docs/`. (medium)
2. **Step 3 tests** then **Step 4 code** per §5. (large)
3. **Step 5 verify** + finalize (§5 step 7). (small)

## 5. Implementation plan (code — after governance + arch/docs)

Each step: full `uv run pytest`, `mypy --strict`, `ruff check` green; commit per step;
surgical. **Tests before code** (user's order: 3 then 4).

**C1 — `canonical.py`: metadata block + content-only digest**
- Convention `canonical["metadata"] = {"last_modified": float, "generation": int}`.
- Add `canonical_content(c)` (doc minus `metadata`) and `canonical_metadata(c)`.
- `canonical_digest` hashes `canonical_content` ONLY (the crux — metadata-only change must
  not move the digest). Confirm `canonicalize` preserves `metadata` (deep-copy → it does).

**C2 — DRY: remove `last_modified`/`generation` from `state.py`**
- `PairState`: delete the two fields, `bump()`, and their (de)serialization (state.py
  ~106-181). Backward-compatible: old `state.json` just has the fields ignored on load.
- This SUPERSEDES the prior restart's "daemon syncs state from canonical metadata" step —
  there is nothing in state to sync.

**C3 — content-driven `last_modified` on the canonical metadata**
- The content-changed stamp (was `rendering.update_state_n_way` `bump=True` →
  `ps.bump()` at rendering.py:344) now writes the CANONICAL `metadata` block
  (`last_modified=now`, `++generation`) and ONLY when content actually changed.
- Audit callers (engine.py adoption/conflict/extend; canonical_projection
  project_from_canonical/reproject): stamp metadata only for content-changing writes; a
  heal/reproject of UNCHANGED content must NOT move it.
- Import reproject: set `last_modified`/`generation` from the IMPORTED canonical metadata,
  not `now` (preserve the imported content's modification time for cross-host mtime_wins).

**C4 — adoption + import write canonical metadata; readers read it**
- Adoption (engine.py `save_canonical` sites): ensure the canonical carries `metadata`
  before save.
- Import (`portable_archive._stage_and_promote_canonicals`): write nested
  `canonical["metadata"] = {...}` before `save_canonical_to`.
- `sync._adopt_orphan_canonicals` (sync.py ~172): currently reads TOP-LEVEL
  `canonical.get("last_modified")` — change to the nested `metadata` block.
- Export + import-collision (`portable_archive.py:164, 280`): read `last_modified` from the
  canonical `metadata` block, not `PairState`.

**C5 — amendment 009 code: remove configurable collision strategy**
- `config.py`: remove `import_collision_strategy` field + default/validation.
- `cli.py`: remove `--collision-strategy` from the `import` subcommand.
- `portable_archive.py`: remove the strategy parameter + `skip`/`overwrite` branches;
  mtime_wins is unconditional.

**C6 — tests**
- Remove `@pytest.mark.xfail(strict=True)` on
  `test_import_pair_id_collision_mtime_wins_import_newer_overwrites`; revise: identical
  content (newer timestamp) import archives NOTHING; assert no archive entry.
- New regression: same content, newer `last_modified` → `sync_once` does NO tool write and
  NO archive (NFR-05/07) and the digest is unchanged (content-only).
- Re-point `test_export_then_reimport_is_byte_identical_for_canonicals` (was AC-11) to FR-12.
- Remove / re-point `skip` + `overwrite` tests (test_cli_export_import.py,
  test_portable_archive.py, test_portable_archive_secret_egress.py).
- Assert CLI `import` no longer accepts `--collision-strategy`; config ignores/rejects a
  stray `import_collision_strategy` per its unknown-key policy.
- Full v0.6 import suite: test_canonical_only_import, test_import_archive_and_quarantine,
  test_import_while_daemon_active, test_portable_archive*, test_heal_from_canonical,
  test_canonical_change_detection, test_bulk_glitch_guard.

**C7 — finalize**
- Amendments 008 + 009 → status applied; record landing commits.
- Bump 0.5.7 → 0.5.8; README changelog; remove `--collision-strategy` from README.
- Commit, push, confirm CI green (ubuntu + windows). Do NOT restart the live daemon onto
  WIP with the propagation gap (§6).

## 6. Gotchas (carry-over + new)

- **`tmp/` is NOT gitignored.** Never `git add -A` — stage explicit paths only.
- **Tests excluded from the mypy gate** (`pyproject [tool.mypy] files = ["src"]`). The
  PostToolUse hook runs `mypy --strict` on edited test files and shows no-untyped-def
  noise — EXPECTED for tests; match the loose test style, don't "fix" it.
- **PostToolUse ruff autofix removes an unused import between edits** — add an import and
  its first use in the same edit, or re-add after.
- **Bash discipline:** one action per call (no `&&` — there is a hard hook block), no `sed`,
  relative paths only (no absolute `/home/me/...`), `~/.claude` via Read/Write/Edit.
- **`canonicalize` preserves unknown fields** (deep-copy) — adding `metadata` is safe.
- **FR-14 reproject archives tool bytes BEFORE re-render** — so a metadata-only diff must
  never enter the reproject path (content-only digest is what guarantees this; the old
  xfail wrongly asserted an archive on identical content).
- **`engine.py` runtime conflict does NOT use `last_modified`/`generation`** (verified by
  grep) — that is what makes the DRY removal from state safe.
- **`sync.py:172` reads top-level `canonical.get("last_modified")`** today — must move to
  the nested `metadata` block in C4.
- **Live daemon runs the checked-out branch (editable install)** via `agents-sync.service`,
  not auto-restarted. Don't restart onto WIP that lacks the full metadata path.
- **§3.4 supersedes the amendment draft text** — reconcile 008/009 to it when applying.

## 7. Definition of done
Governance §3.4 applied to description/requirements/US-12 + amendments reconciled; arch +
README + docs aligned (lexicographic tiebreaker relocated); tests written then code made to
pass (C1–C6); xfail removed and its test green with the corrected archive assertion; the
metadata-only-diff regression green; full suite + mypy --strict + ruff green; CI green;
amendments 008 + 009 status=applied; version bumped 0.5.7 → 0.5.8. Finding A then fully
closed with single-writer state + a self-contained, DRY canonical, and a single
non-configurable mtime_wins import rule.
