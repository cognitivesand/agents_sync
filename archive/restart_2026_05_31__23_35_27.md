# Restart — 2026-05-31 — Canonical metadata model (amendment 008, Task #1)

> Session-handoff. A fresh session reading this + the docs in §1 can execute the
> plan in §5 without further explanation. The design is validated; the metadata-model
> CODE is the work. Governance edits in §4 are proposed and awaiting user validation —
> validate them FIRST (the user's instruction: "finish governance first, then code").
> (The prior 2026-05-29 crash-fix restart is preserved at tmp/restart_fetched.md.)

## 0. Git pin (do not edit by hand)

- `head_sha`: 37def9b (branch `feat/v0.5-cross-machine-merge`, pushed, CI green)
- working tree: clean except in-repo `tmp/` (untracked scratch — NOT gitignored, see §6)
- The single-writer-state WIP is already committed at `aded7b5`; `37def9b` adds the
  uv.lock 0.5.7 sync. Version is 0.5.7.

## 1. Read first

- `docs/amendment/008-single-writer-state-canonical-adoption.md` — THE design record.
  Read the "Canonical metadata model" section in full; it is the spec for this work.
- `docs/amendment/003` (FR-15), `004` (import archive + quarantine fail-closed).
- `docs/project_requirements.md` — FR-12, FR-14, FR-15, FR-16, NFR-01/05/06/07.
- `docs/stories/US-12-portable-library-snapshot.md` — AC-5 (reworded), AC-6, AC-11, AC-17, AC-19.
- `tmp/repro_A_lost_update.py` — deterministic reproduction of finding A (the bug this closes).

## 2. What this is (one paragraph)

Finding A was a lost-update race: `sync_once` and `import_from_zip` both did unlocked
`load_state→mutate→save_state`. Resolution chosen = **single-writer state** (Option 3):
`import` writes canonical-only and never touches `state.json`; the daemon is the sole
state writer and **adopts** orphan canonicals (FR-16). That core is DONE and committed.
The remaining work: `last_modified`/`generation` were state-owned, so under single-writer
state the daemon had no channel to learn an imported `last_modified`. **Resolution
(validated):** make them **canonical metadata** in a **nested `metadata` object**,
written by BOTH adoption and import; `last_modified` is the **user-content modification
time, not the file/write time** (changes iff content changes); the FR-14 change-detection
digest is computed **over content only** so a metadata-only diff causes no reprojection or
archiving (NFR-05/07); the daemon syncs state from canonical metadata each poll.

## 3. Current state

DONE (committed):
- `import_from_zip` is canonical-only (no `state.json` write); `_classify` reconciles
  against the canonical STORE via `canonical.list_canonical_ids` (back-to-back imports dedup).
- `sync_once._adopt_orphan_canonicals` adopts canonicals present-but-unmanaged (FR-16).
- Governance applied + validated: US-12 AC-5 reworded, FR-16 added.
- Suite 515 passed, **1 xfail(strict)**: `tests/test_portable_archive.py::
  test_import_pair_id_collision_mtime_wins_import_newer_overwrites` — pending this work.

PENDING:
- Governance §4 (validate, then apply) — DO FIRST.
- Code §5 (the metadata model).

## 4. Governance edits — PROPOSED, awaiting user validation (apply before code)

Present these for explicit validation; apply only what the user approves.

1. **Glossary (`project_description.md`) — new entries:**
   - **`last_modified`** — wall-clock timestamp of when a customization_artifact's
     **user content** was last changed (not when files were last written). Changes only
     on content change; a projection/heal/re-projection of unchanged content does not
     move it. Discriminator for `mtime_wins` (FR-12); carried in canonical metadata.
   - **`generation`** — host-local monotonic counter incremented on each content change;
     bookkeeping in canonical metadata; not a cross-host discriminator (US-12 AC-17).
2. **Glossary "Canonical" entry** — append: carries a metadata block (`last_modified`,
   `generation`) distinct from user content; round-trip losslessness (AC-11) concerns
   the user content — metadata may differ.
3. **FR-14** — "canonical **content** has changed … A difference confined to canonical
   **metadata** (`last_modified`, `generation`) **shall not** by itself trigger re-projection."
4. **US-12 AC-6** (`mtime_wins`) — archive/overwrite tool bytes only when the winner's
   **content differs**; identical content with only a newer `last_modified` rewrites and
   archives nothing (NFR-05/07).
5. **US-12 AC-11** — clarify the no-op round trip is bit-identical (content + metadata,
   since nothing changed); losslessness concerns user content.

After applying: update amendment 008 status; commit governance separately.

## 5. Implementation plan (code — after governance)

Each step: full `uv run pytest`, `mypy --strict`, `ruff check` green before moving on.
Commit per logical step. Keep changes surgical.

**Step 1 — canonical.py: metadata + content-only digest**
- Adopt convention: `canonical["metadata"] = {"last_modified": float, "generation": int}`.
- Add `canonical_content(canonical) -> dict` (the doc minus `metadata`) and
  `canonical_metadata(canonical) -> dict`.
- Change `canonical_digest` to hash **`canonical_content` only** (exclude `metadata`).
  This is the crux: a metadata-only change must NOT change the digest.
- Confirm `canonicalize` preserves `metadata` (it deep-copies, so it does; optionally
  normalize key order inside it).
- The whole on-disk canonical (content + metadata) is still what `save_canonical` writes,
  so the AC-11 byte-identity test compares whole bytes (passes when metadata is symmetric).

**Step 2 — content-driven `last_modified` (rendering.update_state_n_way + callers)**
- `update_state_n_way` already has a `bump` param. Today nearly all callers bump=True →
  `last_modified` moves on EVERY render. Change the semantics: bump (set last_modified=now,
  ++generation) ONLY when the content changed.
- Audit callers (adoption `engine.py`: adopt, conflict, extend; `canonical_projection.py`:
  project_from_canonical, reproject_canonical): pass `bump=True` only for content-changing
  writes; `bump=False` for projecting/healing UNCHANGED content.
- For the import path specifically (reproject of an import-overwritten canonical): set
  `last_modified`/`generation` from the **canonical metadata** (the imported values),
  NOT `now` — the imported content's modification time must be preserved for cross-host
  mtime_wins. (i.e. a `bump`-from-canonical variant, or set ps fields from canonical metadata.)

**Step 3 — adoption + import write canonical metadata**
- Adoption (`engine.py` `save_canonical` sites ~202, ~313): ensure the canonical dict
  carries `metadata` (last_modified, generation) before save, sourced from the state's
  content-modification values. Result: live canonicals carry metadata → AC-11 symmetry.
- Import (`portable_archive._stage_and_promote_canonicals`): write nested
  `canonical["metadata"] = {"last_modified": decision.last_modified, "generation":
  decision.generation}` before `save_canonical_to`. (This is the reverted edit, now nested
  + symmetric with adoption.)

**Step 4 — daemon syncs state from canonical metadata (sync.py)**
- `_adopt_orphan_canonicals`: read `last_modified`/`generation` from `canonical["metadata"]`
  (currently reads top-level keys — update to the nested block).
- Add a per-poll metadata sync (e.g. inside `_record_canonical_baselines` or a sibling
  `_sync_canonical_metadata`): for each managed pair, set `ps.last_modified`/`generation`
  from the canonical's metadata when present. This is the propagation channel for an import
  that changed metadata (incl. the identical-content / newer-timestamp case — no reproject,
  but state's clock still advances).
- Migration-free: when a canonical lacks `metadata` (pre-existing), fall back to state's
  current values; it gains metadata on its next content-driven write.

**Step 5 — tests**
- Remove the `@pytest.mark.xfail(strict=True)` on
  `test_import_pair_id_collision_mtime_wins_import_newer_overwrites`; revise its archive
  assertion: identical-content import archives NOTHING; assert `last_modified` propagated to
  state after `sync_once` (it should change), and that no archive entry is created.
- Confirm `test_export_then_reimport_is_byte_identical_for_canonicals` (AC-11) passes.
- Add a regression test for the metadata-only diff: same content, newer `last_modified` →
  `sync_once` does NO tool write and NO archive (NFR-05/07) but state's `last_modified` advances.
- Run the full v0.6 import suite (`test_canonical_only_import`, `test_import_archive_and_quarantine`,
  `test_import_while_daemon_active`, `test_portable_archive*`, `test_heal_from_canonical`,
  `test_canonical_change_detection`, `test_bulk_glitch_guard`).

**Step 6 — finalize**
- Update amendment 008 status → applied; record landing commits.
- Bump version (0.5.7 → 0.5.8) + README changelog entry.
- Commit, push, confirm CI green (ubuntu + windows).
- Optionally restart the live daemon on the branch and observe `failed=0` (daemon runs the
  editable install; see §6).

## 6. Gotchas (learned this session — save yourself the pain)

- **`tmp/` is NOT gitignored.** Never `git add -A` (it stages all of `tmp/`, large scratch +
  sandboxes). Always `git add <explicit files>`.
- **Tests are excluded from the mypy gate** (`pyproject [tool.mypy] files = ["src"]`).
  The PostToolUse hook runs `mypy --strict` on edited test files and shows dozens of
  no-untyped-def errors — EXPECTED NOISE for tests; the real gate is src-only. Match the
  existing loose test style (no annotations); do not "fix" it.
- **The PostToolUse ruff autofix removes an unused import between edits.** If you add an
  import in one edit and its first use in a later edit, ruff deletes the import in between.
  Add the import and its usage together, or re-add after.
- **Bash hooks:** no `&&` chaining (one action per call); no `sed`; no absolute `/home/me/...`
  paths in Bash (use relative; for `~/.claude` use Read/Write/Edit tools). Shell cwd can
  drift if a `cd` partially runs — `pwd` to check.
- **`canonicalize` preserves unknown fields** (deep-copy, normalizes only specific fields),
  so adding `metadata` is safe; it won't be stripped.
- **`update_state_n_way(..., bump=...)`** is the lever for content-driven `last_modified`.
  `ps.bump(now=time.time())` sets last_modified=now and ++generation.
- **FR-14 reproject archives tool bytes BEFORE re-render.** That is why a content-only digest
  matters: a metadata-only diff must not enter the reproject path, or it archives identical
  bytes (NFR-07 violation — the exact thing the xfail test wrongly asserted).
- **Live daemon runs the checked-out branch (editable install)** via `agents-sync.service`,
  but is NOT auto-restarted. Do not restart it onto WIP that has the propagation gap.
- **Reproduction of A**: `uv run python tmp/repro_A_lost_update.py` prints the lost update
  (pre-fix). Post-fix it is impossible because import doesn't write state.

## 7. Definition of done

Governance §4 validated + applied; metadata-model code §5 landed; the xfail removed and its
test green with a corrected archive assertion; the new metadata-only-diff test green; full
suite + mypy + ruff green; CI green; amendment 008 status=applied; version bumped. Finding A
is then fully closed with single-writer state + a self-contained canonical.
