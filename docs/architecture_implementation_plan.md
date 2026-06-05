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
| S3 | Tool surface & candidate model | `domain_model/tool_surface` | `ToolSurface`/`SurfaceFormat`, slug rule (Windows-reserved guard), candidate key stability |
| S4 | Sync plan vocabulary | `domain_model/sync_plan` | `SyncIntent` types + `SyncResult`; value semantics |

### Phase B — The planner (pure, the brain)
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S5 | Recover identity | `plan/recover_identity` | managed vs candidate; embedded/recorded id; id-in-isolation (FR-11) |
| S6 | Reconcile known | `plan/reconcile_known` | unchanged / absorb / conflict+mtime-tiebreak / rename / remove / glitch(≥2) / freeze / reproject / mv (US-01/04/06/09/11; digest-detect) |
| S7 | Adopt candidates | `plan/adopt_candidates` | group by (kind,slug); adopt / `absorb_into_managed` / `reject_collision` / `report_unadoptable`; cross-identity retire (US-03/12) |
| S8 | compute_sync_plan + guards | `plan/compute_sync_plan` | two-tool guard (US-07 AC-5); private/framework predicates (US-13/15); whole-plan assembly — all pure, no FS |

### Phase C — Translation (centralized; dialects are the only wire-format code)
| # | Step | Touches | Spec / test focus |
|---|---|---|---|
| S9 | Translation core + markdown dialect | `translation`, `dialects/markdown_frontmatter` | `file_to_canonical`/`canonical_to_file`/`extract_artifact_id`; round-trip, no-foreign-leak (NFR-06/16), malformed→raise, id-in-isolation |
| S10 | Keyed-map dialect | `dialects/keyed_map_slot` | one slot in a shared file (mcp); round-trip, sibling preservation |
| S11 | Structured-text dialect | `dialects/structured_text` | JSON/JSONC/TOML round-trip, comment/order preservation |
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
| S24 | Cut the daemon over | `poll_daemon` `sync_once` = read → plan → execute | the **full conformance suite** stays green against the new pipeline |
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
