# Amendment 008 — Single-writer state: import is canonical-only, daemon adopts orphan canonicals (resolves finding A)

- status: applied 2026-06-01 — canonical metadata model (C1–C4) landed in Stream 1
  (456e586 canonical metadata helpers, 3f36252 runtime metadata into canonicals);
  import/export accessors wired in Stream 2 (91a8265); full suite green on merge.
- branch: feat/v0.5-cross-machine-merge
- date: 2026-05-31
- supersedes / relates to: FR-15 (amendment 003), amendment 004 (import archive),
  US-12 AC-5, the v0.6 safety audit finding A (state.json lost-update race)

## Motivation

Finding A — confirmed by deterministic reproduction (`tmp/repro_A_lost_update.py`):
`Syncer.sync_once` and `portable_archive.import_from_zip` both do an unlocked
`load_state → mutate → save_state`. `atomic_write_text` prevents a torn file but
not a lost update; a daemon poll racing an import clobbers the import's committed
`state.json` mutation, leaving imported canonicals on disk but absent from state —
never projected, never cleaned, silently. FR-15's "identical to sequential"
guarantee has no enforcing mechanism.

Two facts in the code make a single-writer fix clean:
- A **dropped** pair archives its canonical (`removal_propagator` → `archive_canonical`),
  so a canonical with no state entry can only be a fresh import — safe to auto-adopt.
- Every field of the import's state stub (`kind`, `last_modified`, `generation`;
  `agentic_tools={}`; `canonical_digest`) is derivable from the canonical — the
  import's state write is **redundant** with what the daemon can reconstruct.

## Principle / decision

`state.json` is written **solely by the daemon**; it is a projection of the
canonical store (NFR-16). `import` writes the canonical store only. The daemon
**adopts** any canonical present in the store but absent from state. With one
writer to `state.json`, the lost-update race is eliminated by construction.

## Proposed governance edits (require user validation)

### User stories — US-12 AC-5 (reword)

Original:
> AC-5 … Then every canonical document in the zip is written to the local state
> directory and `state.json` is updated with a state stub per imported
> customization_artifact; **import does not write to any agentic_tool root** — the
> next `sync_once` renders each imported customization_artifact onto every locally
> enabled, supporting, and `available` agentic_tool via the unchanged adoption
> pipeline. The command returns after the canonical store and `state.json` are
> durably written. That first `sync_once` performs the projection …

Proposed:
> AC-5 … Then every canonical document in the zip is written to the local state
> directory; **`import` does not write `state.json` and does not write to any
> agentic_tool root** — the next `sync_once` adopts each imported canonical (one
> present in the store with no `state.json` entry), creates its state, and projects
> it onto every locally enabled, supporting, and `available` agentic_tool via the
> unchanged adoption pipeline. The command returns after the canonical store is
> durably written. That first `sync_once` performs the adoption and projection (it
> is not a no-op); every `sync_once` thereafter is a no-op per NFR-05, and no
> archive entries are created on a fresh install (no existing user-authored bytes
> were displaced).

### Requirements — new FR-16

> - **FR-16** (Canonical adoption): The daemon **shall** adopt a customization_artifact
>   whose canonical record is present in the store but absent from `state.json` — a
>   freshly imported canonical — by creating its state entry and projecting it onto
>   every supporting `available` agentic_tool. `state.json` is written solely by the
>   daemon and is reconstructable from the canonical store.

FR-15 is unchanged: with a single state writer its "identical to sequential"
guarantee now holds by construction.

## Design edits (architecture + story notes — applied after validation)

- `docs/architecture.md §6.1`: import writes canonical-only (no state stub); the
  daemon adopts orphan canonicals; remove the now-unnecessary stale-`canonical_digest`
  hack from the overwrite description (a natural digest mismatch drives FR-14
  re-projection). Note the residual: same-`canonical/<id>.json` contention between a
  daemon re-mint and an import overwrite is per-artifact (FR-13), atomic, arbitrable.
- `US-12` design note ("writes canonicals and state stubs only") → "canonicals only".

## Implementation plan

- `portable_archive.import_from_zip`: drop the `state.json` mutation and `save_state`
  entirely; delete `_apply_import_to_state`; import writes canonical only (classify
  still reads state, read-only). The overwrite case no longer needs the deliberate
  stale-digest trick — leaving state untouched makes the recorded digest naturally
  mismatch the new canonical, so FR-14 re-projects.
- `canonical.py`: add `list_canonical_ids(state_dir)` (glob `canonical/*.json`).
- `sync.Syncer.sync_once`: add `_adopt_orphan_canonicals(state)` before the process
  loop — for each canonical id not in `state`, insert a stub (`kind` from the
  canonical, `agentic_tools={}`); the existing heal path projects it.

## Test plan

- The reproduction `tmp/repro_A_lost_update.py` is promoted to a regression test:
  with single-writer state, two interleaved sequences cannot lose an update because
  `import` no longer writes `state.json`.
- New: import writes canonical-only (no state entry) → next `sync_once` adopts +
  projects (one finding per AC-5 / FR-16).
- Overwrite case: import overwrites a managed canonical (no state write) → next
  `sync_once` re-projects via natural digest mismatch (FR-14), displaced tool bytes
  archived (NFR-01).
- Rebuild `test_import_while_daemon_active` to assert `import` performs zero
  `state.json` writes while the daemon polls (closes TQ-01).

## Canonical metadata model (resolved 2026-05-31, user-validated)

Implementing single-writer state surfaced that `import` (writing the canonical
only) had no channel to convey a winning artifact's `last_modified` to the daemon:
those values were state-owned, and the canonical round-trip test (US-12 AC-11)
forbade putting them in the canonical. Resolution, per the user:

- **`last_modified` / `generation` are canonical metadata**, in a **nested
  `metadata` object** on the canonical document, written consistently by BOTH
  adoption and import. NFR-06 (tool-side bytes) is unaffected; AC-11 needs no
  reword because a no-op round trip changes nothing (metadata included), so the
  canonical stays bit-identical — the earlier breakage was the adoption/import
  asymmetry, now removed.
- **`last_modified` is the user-data modification time, not the file/write time.**
  It changes **iff the user content changes**; a projection, heal, or reproject of
  *unchanged* content must NOT move it. (Today `update_state_n_way` bumps it on
  every render — that is the behaviour being corrected.)
- **FR-14 change-detection digest is over content only** (excludes the `metadata`
  block), so a metadata-only difference does not trigger reprojection or spurious
  archive entries (NFR-05 / NFR-07). `last_modified` propagates to state via a
  cheap per-poll metadata sync, not via reprojection.
- **No migration:** the daemon reads `last_modified`/`generation` from the
  canonical metadata when present, else from state; old canonicals gain metadata on
  their next content-driven write.
- **Future:** the `metadata` block is the home for the change-history and per-tool
  file timestamps the user proposed — deferred, not built in this pass.

### Governance edits (G1–G3 applied 2026-06-01; G4, G5, AC-3 superseded by amendments 009 and 010)

KISS: minimal, plain, INCOSE-style; no defensive cross-references. They are
**proposed**; apply only after user validation. Objectives/vision unchanged.

**G1 — `project_description.md` glossary: `Canonical` entry.**

Original:
> - **Canonical** — per-customization_artifact JSON document storing the union of
>   fields from every agentic_tool; the lossless intermediate that drives every renderer.

Proposed:
> - **Canonical** — per-customization_artifact JSON document storing the union of
>   fields from every agentic_tool; the lossless intermediate that drives every
>   renderer. It carries the canonical content itself as well as a nested `metadata`
>   block.

**G2 — `project_description.md` glossary: two new entries (after `Canonical`).**

> - **`last_modified`** — POSIX timestamp (float) of when a customization_artifact's
>   user content was last changed, not when its files were last written. Carried in
>   the canonical's `metadata` block.
> - **`generation`** — host-local monotonic counter, incremented on each content
>   change of a customization_artifact. Carried in the canonical's `metadata` block.

**G3 — `project_requirements.md` FR-14 (revise).**

Original:
> - **FR-14** (Canonical-change detection): The daemon **shall** detect when a
>   customization_artifact's canonical record has changed independently of its
>   tool-side files and **shall** re-project the canonical onto every supporting
>   available tool, preserving any displaced bytes.

Proposed:
> - **FR-14** (Canonical-change detection): The daemon **shall** detect when a
>   customization_artifact's canonical content has changed independently of its
>   tool-side files and **shall** re-project the canonical onto every supporting
>   available tool, preserving any displaced bytes. Change detection **shall** be
>   computed over canonical content only, not on the metadata.

**G4 — `US-12` AC-6 (revise the `mtime_wins` and `overwrite` bullets).**

Original (`mtime_wins` bullet):
> `mtime_wins` (default): … If the import wins, the local canonical is overwritten
> and every agentic_tool's tool-side file is archived (NFR-01) before re-projection
> on the next poll. If the local wins, the imported artifact is ignored.

Proposed (`mtime_wins` bullet):
> `mtime_wins` (default): … If the import wins and its content differs, the local
> canonical is overwritten and every agentic_tool's tool-side file is archived
> (NFR-01) before re-projection on the next poll. If the content is identical, only
> the metadata is updated. If the local wins, the imported artifact is ignored.

Original (`overwrite` bullet):
> `overwrite`: the imported canonical replaces the local one unconditionally; every
> local tool-side file is archived (NFR-01) before re-projection.

Proposed (`overwrite` bullet):
> `overwrite`: the imported canonical replaces the local one unconditionally; when
> its content differs, every local tool-side file is archived (NFR-01) before
> re-projection.

**G5 — `US-12` AC-11.** No change. The existing "bit-identical … no-op round trip"
already holds once metadata is written symmetrically; adding a parenthetical would
over-explain. Dropped per KISS.

**AC-3 — `US-12` (DRY: read `last_modified` from canonical metadata, not state).**

Per the single-source-of-truth refinement below, `last_modified` lives **only** in
the canonical `metadata` block; the export carries it from there, not from state.

Original:
> Then the in-archive copy carries a `last_modified` field whose value equals the
> artifact's `last_modified` stored in the local `state.json` (a floating-point POSIX
> timestamp set every time the canonical for that pair is updated by the daemon). The
> local canonical and `state.json` are not modified by the export.

Proposed:
> Then the in-archive canonical carries the `last_modified` value from its `metadata`
> block (a floating-point POSIX timestamp set every time that pair's content is
> changed by the daemon). The local canonical and `state.json` are not modified by
> the export.

### DRY refinement — `last_modified` / `generation` leave the state schema

Single source of truth: `last_modified` and `generation` live **only** in the
canonical `metadata` block, **not** in `state.json`. This supersedes the earlier
plan to mirror them into state and sync per poll — there is now nothing in state to
sync. Confirmed feasible: `engine.py` (runtime US-06 conflict resolution) does not
read them; the only readers are export, import-collision compare, and adoption,
each of which has the canonical on disk.

- `state.py` `PairState`: remove the `last_modified` and `generation` fields,
  `bump()`, and their (de)serialization. Backward-compatible — old `state.json`
  files simply have the fields ignored on load.
- `rendering.update_state_n_way`: the content-changed stamp writes the canonical
  `metadata` block (`last_modified=now`, `++generation`), not a state field.
- `portable_archive` export/import-collision: read `last_modified` from the
  canonical `metadata` block (local and imported sides) instead of `PairState`.
- `sync._adopt_orphan_canonicals`: keep reading from canonical metadata (just the
  nested block); do not write the values into state.

### Test impact
- `test_export_then_reimport_is_byte_identical_for_canonicals` (AC-11) passes once
  metadata is written symmetrically (no-op round trip unchanged).
- `test_import_pair_id_collision_mtime_wins_import_newer_overwrites` asserts an
  archive entry on an identical-content / newer-timestamp import; under
  content-only digest that is correctly a no-op (no content lost) — the assertion
  must be revised to check timestamp propagation, not needless archiving.

## Verification

Full `uv run pytest` + `mypy --strict` + `ruff` green. Governance applied only
after user validation of AC-5 and FR-16.
