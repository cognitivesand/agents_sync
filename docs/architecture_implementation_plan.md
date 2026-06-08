# agents_sync — Implementation Plan (thin clean architecture)

- **Status:** plan (for execution). Builds the design in
  `docs/architecture_simplification_proposal.md` (rev 4) in small, independently
  testable steps.
- **Date:** 2026-06-05
- **Governing artifacts:** `docs/project_requirements.md`, `docs/stories/US-*.md`,
  `docs/project_description.md`, and the proposal above. Each step traces to them.

> Every step is small, shippable, and reversible, and passes the **per-step gate**
> below before the next begins. No step is "done" until it is *spotless*.

---

## The per-step gate

Every step is executed through the **`incremental_step` skill**, which defines the
fixed gate (its single source of truth):

> detail the step → update docs → write/adjust tests then **`/audit-tests`** (the
> only point tests may change) → code → run the full tests → **`/code_and_tests_quality_review`**
> on the modified files against three targets (1 spec compliance, 2 clean code:
> POLA/DRY/KISS/YAGNI/SRP/SoC, no antipatterns, 3 efficiency/sparsity/no bloat) →
> **spotless** gate (max **3** audit→fix loops, else stop and escalate) →
> commit + **`/bcp`**.

Order is fixed; tests change only at the `/audit-tests` substep; a step ships
independently and is "done" only when spotless. See the skill for the full rules.

---

## Build location: a parallel tree (`src_new/` + `tests_new/`)

The greenfield build lives in **`src_new/`** (package name unchanged: `agents_sync`),
with its unit tests in **`tests_new/`**. The existing `src/agents_sync/` keeps
running untouched, so the conformance suite stays green throughout. Isolation:
the default `pytest` run is pinned to `tests/` (`testpaths`), and `tests_new/` runs
as its own stage whose `conftest.py` puts `src_new/` first on `sys.path` (the
editable install is a plain `.pth`, so this wins cleanly). `scripts/ci.sh` runs
both scopes plus `mypy --strict` over `src_new/`.

**Cutover (S24–S25) is a directory rename**, not a code rename: delete the old
`src/agents_sync/`, move `src_new/agents_sync/` → `src/agents_sync/`, fold
`tests_new/` into `tests/`. Because the package name never changes, no internal
import is rewritten (honouring the no-bulk-rename rule).

## Safety net: the conformance suite

The existing behavioural tests (`test_e2e_sync`, `test_round_trip`,
`test_cross_adapter_adoption_matrix`, `test_antigravity_three_way`,
`test_first_boot_reconciliation`, the per-tool `test_*_io`, the size-explosion
regressions, …) are the **conformance suite**. They encode the user-visible
behaviour and must stay green through every step and across the cutover. New
per-step unit tests are additive; the conformance suite is the invariant.

---

## Build order (dependency-first; each row is one gated step)

The new modules are built and unit-tested in isolation (pure core → translation →
gateways → read/execute → tools/drivers), then the daemon is cut over to them and
the superseded modules retired. The conformance suite holds throughout.

### Phase A — Pure domain core (no I/O)
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S1 | Canonical document | `domain_model/canonical_document` | schema, normalise (idempotent), content-digest excludes metadata (FR-14), dict round-trip |
| S2 | Artifact identity | `domain_model/artifact_identity` | `mint_artifact_id` is the sole minter; `validate_artifact_id` (UUIDv4); single-caller static guard |
| S3a | Artifact naming & candidate key | `domain_model/artifact_naming` | slug rule (Windows-reserved guard) + `candidate_key` (kind+slug); the identity grouping for id-less candidates (US-03) |
| S3b | Tool surface & format (minimal) | `domain_model/tool_surface` | `KeyedMapSlot`, `ToolSurface` (tool, kind, location, surface_format), minimal `SurfaceFormat` (dialect) — immutable hashable value objects the planner consumes. The recipe fields (known/tool-only fields, reserved names, filename precedence) grow with their consumers in S9 (translation) / S17 (read phase), per YAGNI |
| S4 | Sync plan vocabulary | `domain_model/sync_plan` | closed `IntentKind` vocabulary (the 11 intents the planner S5–S8 emits and the executor S19 performs, named per proposal §6) + immutable `SyncResult` (changed / failed / blocked / frozen / diagnosed); value semantics. The per-intent payload dataclasses grow with their emitter in S5–S8 (planner) / S19 (executor), per YAGNI — same call as S3b |

### Phase B — The planner (pure, the brain)
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S5 | Recover identity | `plan/recover_identity` (+ minimal `observation`, `sync_state` inputs) | managed vs candidate; recover by well-formed embedded id (precedence) then recorded location ownership; never mint (FR-11). Introduces the minimal `SurfaceObservation` (tool_surface + embedded_id) and `SyncState`/`ArtifactRecord` (recorded surface locations) that this step reads; their other fields (digest, mtime, parsed canonical) grow with their consumers in S6–S8 / S17, per YAGNI |
| S6a | Reconcile known — content rule + freeze | `plan/reconcile_known` (+ grows `observation`, `sync_state`, `sync_plan` intents) | the **unified content rule**: freeze if the artifact won't parse (FR-11); else digest-detect the changed surfaces, absorb the freshest (highest `modified_time`, alphabetical tiebreak — US-06 AC-4) and project the canonical onto the other surfaces; else unchanged (US-01). Grows `SurfaceObservation` (+content_digest/modified_time/parsed+`ParseFailure`), `ArtifactRecord.surfaces` (→`RecordedSurface` location+digest), and `sync_plan` (the `FreezeArtifact`/`AbsorbToolEdit`/`ProjectToTools` payloads). Extend-to-newly-available and the tied-mtime WARN are deferred (registry → S8/S20; logging → S22) |
| S6b | Reconcile known — surface-shape (rename + remove) | `plan/reconcile_known` (+ grows `sync_state`, `sync_plan`) | the per-artifact shape diff: canonical slug ≠ recorded slug → `rename_artifact` (US-04, replaces the projection); a recorded tool with no observation this poll → `remove_artifact`, short-circuiting content (US-11). `mv` needs no intent (a moved tool still has an observation → not a vanish; recompute records the new location). Grows `ArtifactRecord` (+recorded `name` for slug compare) and `sync_plan` (`RenameArtifact`/`RemoveArtifact`). The cross-artifact downgrades — `reject_collision` (slug clash) and glitch → `reproject_canonical` — are deferred to S8 |
| S6c | Reconcile known — canonical authority | `plan/reconcile_known` (+ grows `sync_state`, `sync_plan`, `canonical_document`) | the stored canonical (read-phase input) is corrupt → `rebuild_corrupt_canonical`; or it changed out of band (its digest moved with no surface change → an import) → `reproject_canonical` (US-09). Adds the `stored_canonical: CanonicalDocument \| CorruptCanonical \| None` input (None until S8 wires it), the `CorruptCanonical` marker (parallels `ParseFailure`), `ArtifactRecord.canonical_digest`, and the `ReprojectCanonical`/`RebuildCorruptCanonical` payloads. Pipeline: freeze → rebuild → remove → content → reproject |
| S7 | Adopt candidates | `plan/adopt_candidates` (+ `plan/winner_selection`, grows `sync_plan`) | the per-candidate-local fates: group the parsed id-less candidates by (kind,slug) → `adopt_new_artifact` (winner by the shared mtime tiebreak, US-03 AC-7); each unparseable candidate (no slug to group by) → `report_unadoptable` (US-03, never minted). Extracts the shared `freshest` winner-selection (US-06 AC-4 / US-03 AC-7) into `plan/winner_selection`, reused by `reconcile_known`. Grows `sync_plan` (`AdoptNewArtifact`/`ReportUnadoptable`). The managed-match → `absorb_into_managed` downgrade is cross-artifact (S8); cross-identity retire is import (S23) |
| S8a | compute_sync_plan — assembly + two-tool guard | `plan/compute_sync_plan` (+ `sync_plan` `SyncPlan` container) | whole-plan assembly: `recover_identity` → `reconcile_known` per managed artifact (threading each `stored_canonical`) → `adopt_candidates`, collected into the new `SyncPlan` container. Plus the **two-tool guard** (the simplest, most global downgrade): fewer than two available tools → drop every destructive intent (`adopt_new_artifact`, `absorb_into_managed`, `project_to_tools`, `rename_artifact`, `remove_artifact`) (US-07 AC-5). Adds the `available_tool_count` input. Pure, no FS. The key-conflict and glitch downgrades are S8b/S8c |
| S8b | compute_sync_plan — collision guard | `plan/compute_sync_plan` (+ `sync_plan` `RejectCollision`) | the whole-poll **managed-key index**: each managed artifact's *effective* `(kind, slug)` — kind from its observations, name from `record.name` with any pending `rename_artifact` new name applied. A key shared by ≥2 managed ids → drop all their intents and emit `reject_collision` (untouched, structured error naming the colliding ids + slug). One mechanism covers both US-03 AC-8 (two managed already at one key) and US-04 AC-5 (a rename *creating* the clash). Adds the `RejectCollision` payload. Pure, no FS |
| S8c | compute_sync_plan — absorb-into-managed guard | `plan/compute_sync_plan` (+ `sync_plan` `AbsorbIntoManaged`) | reuses S8b's managed-key index (after rejection, so only *non-colliding* keys remain): an `adopt_new_artifact` whose candidate group's `(kind, slug)` matches a managed key → `absorb_into_managed` instead (managed wins, no mint — US-03 AC-6). Adds the `AbsorbIntoManaged` payload and adds `ABSORB_INTO_MANAGED` to the two-tool destructive set. Pure, no FS |
| S8d | compute_sync_plan — glitch guard | `plan/compute_sync_plan` | the per-tool whole-poll vanish count: a `remove_artifact` on a tool that suffered a *glitch* — ≥2 of its recorded artifacts vanished this poll → `reproject_canonical` instead (restore from canonical, no removal propagated — US-11 AC-9); exactly one vanished recorded artifact stays a deliberate deletion. Redirects existing intents (no new payload). Pure, no FS. (Framework-specific projection hold-back is US-15, at S12 with its read-phase flag; the `private` flag was retired — amendment 019.) |

### Phase C — Translation (centralized; dialects are the only wire-format code)
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S9 | Translation core + markdown dialect | `translation`, `dialects/markdown_frontmatter` | `file_to_canonical`/`canonical_to_file`/`extract_artifact_id` (each takes the whole `ToolSurface` — the seam keys per-tool bags and stamps `kind`); round-trip, no-foreign-leak (NFR-06/16), malformed→raise, id-in-isolation. **Size-explosion hardening is out of scope here** (own concern → `parser_bounds`, §13); see the S24 gate |
| S10 | Keyed-map dialect | `dialects/keyed_map_slot`, `dialects/field_mapping` | one slot in a shared file (mcp); round-trip, sibling preservation, no-foreign-leak, id-in-isolation. Extracts the shared recipe-application (`field_mapping`) that `markdown_frontmatter` and `keyed_map_slot` both use. `SurfaceFormat` grows `map_key_path` + `file_format`. **JSON format only**; TOML (codex mcp) + JSONC land with the structured-text codec at S11 (an unimplemented format fails loud) |
| S11a | Structured-text codec + keyed-map wiring | `dialects/structured_text`, `dialects/keyed_map_slot` | the shared `json`+`toml` codec (`deserialize`/`serialize`): key-order + data round-trip, **comments not preserved**, stdlib only (`tomllib` read + hand-rolled TOML writer; no new dependency). `keyed_map_slot` switches to it, removing the S10 toml fail-loud stub — **unblocks codex mcp (toml)**. JSONC deferred (no tool declares it; a correct comment strip must be string-aware) |
| S11b | Structured-text whole-file dialect | `dialects/structured_text` | the whole-file `parse`/`render`/`extract_id` for a structured-text artifact (codex's whole-`.toml` agent), using the S11a codec + `field_mapping` with body-field handling |
| S12 | Global-rules dialect | `dialects/global_rules` | `@import` resolution (cycle/escape fail-closed) + framework-specific hold-back (US-15) |
| S13 | MCP dialect specifics | `dialects/mcp_server` | per-tool transport/auth field maps; secret-field shapes |

### Phase D — Gateways (the only filesystem touch points)
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S14 | Atomic file writer | `atomic_file_writer` | temp+rename, staged folder swap (NFR-03 atomic visibility), OS-quirk retry, no lock |
| S15 | Canonical & state stores | `canonical_store`, `sync_state_store` | round-trip; corrupt → quarantine (US-09 AC-4); schema/versioning |
| S16 | Archive + GC | `artifact_archive` | archive-before-write (NFR-01); tiered retention GC tier-boundaries (NFR-07); unparseable-safe |

### Phase E — Read phase, secrets, executor
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S17 | Read tool surfaces | `read_tool_surfaces` | cheap digests for all; re-parse only changed surfaces; inspect write-targets; FR-10 filename precedence |
| S18 | Secret policy | `secret_policy` | detection heuristics + egress enforcement at adopt/render/export/import (NFR-15); refuse vs accept-warn |
| S19 | Execute sync plan | `execute_sync_plan` | per-intent transactions (atomic-across-losers, US-06 AC-6); sole mint; archive-before-write; secret egress |

### Phase F — Tools as data, drivers, library
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S20 | Tool definitions + registry | `tools/*`, `tools/agentic_tools_registry` | one `ToolDefinition` (recipe) per tool; per-tool round-trip + cross-adapter matrix (NFR-11/18); reserved names |
| S21 | Runtime config | `runtime_config` | load/validate/platform paths; fail-closed config errors + distinct exit code (NFR-10, US-07 AC-7) |
| S22 | Daemon + CLI | `poll_daemon`, `command_line_interface` | systemic-only failure budget (FR-02), GC tick, latency (NFR-02); export/import/run; exit-code matrix (NFR-10) |
| S23 | Portable library | `portable_library` | export; import preview-then-write + `--force`; last-modified-wins / cross-identity retire (US-12, FR-12/15) |

### Phase G — Cutover & retirement
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S24 | Cut the daemon over | `poll_daemon` `sync_once` = read → plan → execute | the **full conformance suite** stays green against the new pipeline. **Gate:** `parser_bounds` size-explosion hardening (deferred from S9 — bounded YAML composer, front-matter scan window, text-size cap) MUST be in place; the size-explosion regression tests in the conformance suite enforce it |
| S25 | Retire superseded modules | delete old discovery/adoption/sync/etc. | full suite green; measure LOC vs target (~6–7k); architecture.md reflects the final map |

Steps may be split further if any one cannot pass the gate as a single increment;
they may not be merged (each must remain independently shippable).

---

## Definitions

- **Spotless** = full CI green + `/audit-tests` clean on the step's tests +
  `/code_and_tests_quality_review` clean on all three targets for the step's
  modified files, with zero outstanding findings.
- **Audit→fix loop** = one (review → remediate) cycle. Max 3 per step; on the
  third still-not-spotless, stop and escalate rather than proceed or weaken a
  test/criterion.
- **Cutover discipline:** the conformance suite is never red at a step boundary;
  a step that would leave it red is not done.

---

## Relationship to prior work

This plan supersedes the earlier phased plan (`elegant-bubbling-token`). The
602c6d remediation and the dedup/simplification already on
`fix/size-explosion-hardening` realise pieces of the target (single mint site,
archive GC, daemon failure policy, collapsed dead fields); where a step's outcome
already exists and is spotless, the step's gate is satisfied by verifying it, not
rebuilding it.
