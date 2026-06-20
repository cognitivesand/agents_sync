# Restart — 2026-06-20

> Last updated by Claude at 2026-06-20T03:04:27+0200. This file is a session-handoff
> snapshot. A fresh session reading this should be able to resume work without
> further explanation.

## 0. Git pin (do not edit by hand)

- `head_sha`: f66386d31655f534f76fe7175b17ddba95234661
- `head_short`: f66386d
- `branch`: fix/size-explosion-hardening
- `dirty`: false (no tracked changes)
- `dirty_summary`: clean (tracked); 36 untracked files — all `docs/audits/**` audit
  artifacts + `graphify-out/` (left untracked by project convention; NOT pending work)
- `remote_head`: f66386d (pushed; upstream = origin/fix/size-explosion-hardening)
- `saved_at`: 2026-06-20T03:04:27+0200

## 1. Read these first

- `~/.claude/AGENTS.md` — global engineering rules (POLA/KISS/YAGNI/DRY/SRP/SoC; functions
  ≤40 lines, modules ≤300; tools-as-data, NO tool-name branches; surgical; no bulk renames).
- `docs/architecture_implementation_plan.md` — **the spine.** Step-by-step rebuild plan; the
  "Progress (current state)" block at the top is the live status. Phase F (S20, S21, S22) done;
  **S23 (Portable library) in progress, split a–e** — see the S23 Progress bullet + build-order row.
- `docs/architecture_simplification_proposal.md` (rev 4) — the design the plan builds (§12
  cross-cutting concerns line ~430 = library export/import; §13 module map ~472 = `portable_library`).
- `docs/project_description.md` — **glossary defines `last_modified`/`generation`** (lines ~119-121:
  store-owned canonical metadata; `last_modified` = user-content-mod time, NOT file write time).
- `docs/project_requirements.md` — FR-12/13/14/15/16, NFR-01/07/13/15 (the S23 requirements).
- `docs/stories/US-12-portable-library-snapshot.md` — **the active story** (export/import ACs).
- `docs/amendment/008-single-writer-state-canonical-adoption.md` + `009-import-mtime-wins-only.md` —
  the user-validated import design: `last_modified_wins` (single rule), canonical metadata model.
- `docs/architecture.md` — describes the OLD `src/` tree; rebuild lives in `src_new/`; reconciled at
  cutover (S24–S25). Old reference impl of this feature: `src/agents_sync/portable_archive.py`.

## 2. Working context (non-obvious deltas)

- **Greenfield-parallel REBUILD.** New code in `src_new/agents_sync/`, tests in `tests_new/`. Old
  `src/agents_sync/` is REFERENCE ONLY (never edit). Cutover (S24–S25) is a `src_new → src` rename.
- **Test wiring:** rebuild suite runs via `uv run pytest -c pytest_new.ini`; default `pytest` runs the
  OLD conformance suite (`tests/`). Full gate = `bash scripts/ci.sh` (ruff + mypy src + mypy src_new +
  pytest tests/ + pytest -c pytest_new.ini); the pre-push hook runs it. Rebuild now at 666 tests.
- **Rebuild bumps are PATCH `feat(rebuild)`**; a bump must run `uv lock` and stage `uv.lock`. NO git
  tag for rebuild steps. Stage ONLY intended source/test/doc/version files — `docs/audits/**` +
  `graphify-out/` stay untracked (never `git add -A`). Each plan step driven via `incremental_step`.
- **Audit cadence (memory `feedback_audit_cadence`):** the heavyweight two-auditor
  `/code_and_tests_quality_review` runs ONCE per plan-step NUMBER, after ALL its sub-increments —
  the **end-of-S23 batched audit runs after S23e**, NOT per sub-increment. Sub-increments still get
  docs → red-first tests → `/audit-tests` → code → full CI → commit/`/bcp`.
- **THE central S23 design decision (resolved this session — see memory `feedback_verify_before_designing`):**
  the rebuild's `CanonicalDocument` deliberately DROPPED `last_modified` (pure content-only entity,
  FR-14 digest is structural). It was a **YAGNI deferral, not abolition** — the glossary + amendment 008
  mandate `last_modified`/`generation` as **store-owned canonical metadata** (= user-content-mod time,
  NOT file mtime). My first instinct (file mtime) was WRONG; the user's "Why?" caught it. Realised in
  S23a: the canonical-store envelope now carries `metadata{last_modified, generation}`, content-change-
  stamped (bump iff content digest changes; heal/reproject preserves), excluded from the digest.
- **`save_imported_canonical` preserves the GIVEN metadata** (not a fresh stamp) — this is why the
  import preserves the source's `last_modified` across machines, making cross-host `last_modified_wins`
  correct and a re-import of an unchanged library a no-op (FR-12 idempotency).
- **`portable_library` is now a PACKAGE** (`_shared.py` / `_export.py` / `_import.py` + re-exporting
  `__init__.py`) — split for the 300-line limit (the `dialects/mcp_server` precedent). Public import
  path `from agents_sync.portable_library import ...` unchanged; S23b export tests stayed green.
- **Export entry format** = the raw store envelope bytes (carries `last_modified`); export walks
  `list_canonical_ids` (the store, NOT state.json — host-specific); read-only (corrupt → skip, never
  quarantine); secret egress via `find_secret_literals` (skip-not-raise under refused).
- **GOTCHA:** a `cd src_new/agents_sync` inside one Bash call PERSISTED the shell working dir and broke
  a later `pytest -c pytest_new.ini` (config not found). Run git/pytest from the repo root; `cd` back if
  a prior call moved you.
- **Subagents occasionally returned `API Error: Overloaded`** on big fan-outs in prior sessions; re-launch.

## 3. Active task

### 3.1 Goal

Execute the thin-clean-architecture rebuild (`docs/architecture_implementation_plan.md`) one gated
increment at a time, until cutover replaces the old `src/` with `src_new/`.

### 3.2 Constraints specific to this task

- Hard: each plan step (and sub-increment) goes through the `incremental_step` gate (docs → red-first
  tests → `/audit-tests` → code → full CI → ship). Conformance suite (`tests/`) stays green at every
  step. Never edit `src/`. Governance edits need user approval of exact final text. last_modified is
  user-content-mod time NOT file mtime (glossary); import rule is the single `last_modified_wins`
  (amendment 009), ties favour local.
- Soft: rebuild bumps PATCH `feat(rebuild)`; heavyweight audit batched per plan-step-number (end-of-S23
  after S23e).
- Out of scope now: cutover (S24–S25); gemini `oauth` mcp auth spelling (deferred cleanup).

### 3.3 Status — what is done

- **S21 Runtime config COMPLETE** (0.7.44). **S22 Daemon + CLI COMPLETE** (0.7.48).
- **S23a — canonical-store metadata block COMPLETE** (0.7.49, `381ed6a`): envelope gains
  `metadata{last_modified, generation}`, stamped iff content digest changes, excluded from digest
  (FR-14); `load_canonical_metadata` accessor; executor's 4 `save_canonical` calls gain stamping
  transparently (clock injected). Glossary + amendment 008.
- **S23b — portable_library export COMPLETE** (0.7.50, `e0709b2`): `export_library` walks the canonical
  store, read-only point-in-time (AC-1/2), secret egress (AC-12/13/14), 7-field manifest (AC-1), atomic
  zip via temp + `move_file_atomic` (AC-4). Each entry ships the raw envelope (carries `last_modified`).
- **S23c — portable_library import core COMPLETE** (0.7.51, `f66386d`, current HEAD): `import_library`
  validates fully in memory (AC-9), same-id `last_modified_wins` (AC-6/FR-12), canonical-only atomic
  writes (AC-5/10, FR-13/16), receiver secret egress (AC-15/16), displaced-canonical archive on
  content-differ (NFR-01/07). Store gained `save_imported_canonical` + public `read_envelope_metadata`;
  `portable_library` became a package.
- Full `bash scripts/ci.sh` green at HEAD (conformance `tests/` + 666 rebuild tests).

### 3.4 Status — what is in progress

Nothing mid-edit — clean shipped checkpoint at `f66386d` (S23c). Working tree has only untracked
artifacts (`docs/audits/**`, `graphify-out/`). No background agents.

### 3.5 Next concrete step

Start **S23d — cross-identity merge + preview/`--force`** via the `incremental_step` skill:
(1) cross-identity slug merge (US-12 **AC-7**) — an imported canonical whose `(customization_type,
target_slug(name))` matches a *different* local `customization_artifact_id` reconciles onto the LOCAL id
(reused, not re-stamped) by `last_modified_wins`, retiring the other; (2) `preview_import` (read-only
dry-run, US-12 **AC-18**) enumerating every local artifact that would be displaced/merged BEFORE any
write, with `--force` required when a local artifact would be displaced. Build on the S23c `_import`
module (extend `_classify`/decisions with a slug index keyed on `list_canonical_ids`; see old reference
`src/agents_sync/portable_archive.py` `_build_slug_index`/`_classify`/`preview_import`). Find the
rebuild's slug function first (`domain_model/artifact_naming.py` — `slugify_name`/`candidate_key`).

### 3.6 Open questions / decisions awaiting the user

None blocking. (Last turn ended on "Want me to proceed with S23d?" — a go/no-go, not a design decision.)

## 4. Other tasks queued behind the active one

- **S23d cross-identity merge + preview/`--force`** (US-12 AC-7/AC-18). Medium. (= the active next step.)
- **S23e — CLI export/import wiring** — wire `command_line_interface.py` `export`/`import` subcommands
  (deferred from S22) onto `portable_library`; `--force` flag; exit-code matrix. Small–medium.
- **End-of-S23 batched audit** — the heavyweight two-auditor `/code_and_tests_quality_review` over all
  S23 sub-increments' modified files, then remediate. (Runs after S23e.) Medium.
- **Phase G cutover (S24)** — wire `poll_daemon`/CLI `sync_once = read→plan→execute` as the active
  pipeline; **gate: `parser_bounds` size-explosion hardening MUST land first**; point the full
  conformance suite at the new pipeline. Large.
- **Phase G S25** — retire old `src/` modules; `src_new → src` rename; update `docs/architecture.md` +
  `docs/agentic_tool_integration_protocol.md` to the new model. Large.
- **Cleanup: gemini mcp `oauth` auth-field spelling** — small data fix gemini still lacks. Small.

## 5. Files touched this session (skim list)

- `src_new/agents_sync/canonical_store.py` [edited] — `metadata` block, `save_imported_canonical`,
  public `read_envelope_metadata`, extracted `_write_envelope`, clock-injected `save_canonical`
- `src_new/agents_sync/portable_library/__init__.py` [created] — package re-exports
- `src_new/agents_sync/portable_library/_shared.py` [created] — `PortableLibraryError`, constants,
  `read_canonical_document` (lenient non-mutating parse)
- `src_new/agents_sync/portable_library/_export.py` [created — moved from `portable_library.py`] — export
- `src_new/agents_sync/portable_library/_import.py` [created] — import core (`import_library`,
  `ImportReport`, validate/classify/apply); cross-identity + preview land here in S23d
- `tests_new/test_canonical_metadata.py` [created S23a + edited S23c] · `tests_new/test_portable_library.py`
  [created S23b] · `tests_new/test_portable_library_import.py` [created S23c]
- `docs/architecture_implementation_plan.md` [edited] — S23 row + Progress (a–e split)
- `pyproject.toml` + `uv.lock` [edited] — 0.7.48 → 0.7.51
- `~/.claude/.../memory/feedback_verify_before_designing.md` [created] + `MEMORY.md` [edited]
- READ: `src/agents_sync/portable_archive.py` (OLD reference impl — has slug-index/cross-identity/preview
  to mirror for S23d), `src_new/agents_sync/{secret_policy,artifact_archive,atomic_file_writer,sync_once,
  command_line_interface}.py`, `domain_model/{canonical_document,plan/winner_selection}.py`.

## 6. Anything else the next session needs to know

- Memory already covers: no-bulk-renames, releases=tag+gh-release, AC-authoring style, governance
  final-text approval, uv.lock-tracks-bump, spec/code alignment, audit cadence, tools-as-data-no-hardcoding,
  **verify-before-designing** (new this session).
- The plan's "Progress (current state)" block (top of `architecture_implementation_plan.md`) has the full
  per-step ledger and the S23 a–e split; trust it as the live status.
- For S23d cross-identity: the rebuild slug helper is in `domain_model/artifact_naming.py`; the candidate
  grouping key is `(kind, slug)`. The merge reuses the LOCAL id (files not re-stamped) and retires the
  other — mirror old `portable_archive._classify` but in the new content-only/store-metadata model.
- `2026-06-20`: /restart invoked with no argument after shipping S23c (0.7.51). Clean checkpoint; next
  session begins S23d.
