# agents_sync — Thin, Clean Architecture (Proposal)

- **Status:** proposal (for review). A target design derived from the
  requirements — not from the current code. No code implied.
- **Date:** 2026-06-04
- **Scope:** the production daemon. Installers, CI, packaging are out of scope.
- **Inputs (only):** `docs/project_description.md`, `docs/project_requirements.md`
  (FR-01…16, NFR-01…18), `docs/stories/US-*.md`.

> Designs the system the requirements ask for, in the fewest, clearest parts.
> Names follow AGENTS.md §4: every name is a purpose-describing 2–4 word pair;
> no bare `Codec` / `Store` / `Handler` / `Manager`.

---

## 1. Executive summary

`agents_sync` keeps user-authored customization artifacts (agents, skills,
rules, slash commands, MCP servers) in agreement across AI tools, with a
per-artifact **canonical document** as the single source of truth.

Three moves make it thin and clean:

1. **Separate the decision from the execution.** One pure function,
   `compute_sync_plan`, decides *what should change*; a thin `execute_sync_plan`
   carries it out. The hard logic is a pure function tested without a filesystem.
2. **Two centralized translation functions.** `file_to_canonical` and
   `canonical_to_file` are the *only* places bytes become a canonical document or
   vice versa. Each interprets a declarative `SurfaceFormat`; per-tool knowledge
   is **data**, not code.
3. **One home per concern.** One identity mint site, one persistence gateway
   (archive-before-write by construction), one secret-policy enforcer.

Result: a hexagonal design with a small, fully unit-testable core, ~24 modules,
and roughly half the code of a conventionally-layered build. The 602c6d failure
class has no code path.

---

## 2. Goals and non-goals

**Goals** — meet every FR/NFR/AC with one home and one test; a pure decision
core; small single-responsibility modules (≤200 lines typical, ≤300 hard,
≤40-line functions); zero duplication; failures designed out; canonical-as-truth.

**Non-goals** — no features beyond the spec; no change to project intent; US-16
(rules section decomposition) stays a future spike.

---

## 3. Principles

1. Meet the spec. 2. Simplicity (KISS/DRY/SRP/SoC). 3. Minimal size. Plus:
dependencies point inward; pure logic is separated from I/O; **names state
purpose** (AGENTS.md §4).

---

## 4. The domain model

Three ideas carry the system:

1. **Canonical document is truth.** Each artifact has one `CanonicalDocument`
   (`artifact_id`, `kind`, `name`, content, per-tool extras). Every tool-side
   file is a projection of it; reading a tool file folds changes back losslessly
   (NFR-16/06). (`artifact_id` is the glossary's `customization_artifact_id`.)
2. **A tool is a set of surfaces.** A `ToolSurface` is a `(tool, kind, location,
   surface_format)`; `location` is a file path or a keyed-map slot. The core sees
   surfaces and formats — never a tool name (NFR-11).
3. **Sync is a pure decision.** Given the `SurfaceObservation`s read this poll
   and the `SyncState` recorded last poll, a pure function yields a `SyncPlan`.
   Executing it is a separate, thin step.

```
   read_tool_surfaces        compute_sync_plan (pure)      execute_sync_plan (I/O)
   surfaces on disk  ─────▶  SurfaceObservations  ─────▶  SyncPlan  ─────▶  writes + state
        ▲                         (+ recorded SyncState, now)                    │
        └────────────────────────────── next poll ◀──────────────────────────────┘
```

---

## 5. The shape: pure core, named seams, adapters, drivers

```
   drivers      poll_daemon · command_line_interface
                          │ call
   pure core    compute_sync_plan  —  the sync brain (no I/O)
                domain_model        —  canonical, identity, slug, surfaces
                          │ expressed as a SyncPlan, carried out via the seams
   seams        file_to_canonical / canonical_to_file   (centralized translation)
                canonical_store · sync_state_store · artifact_archive   (persistence)
   adapters     dialect mechanisms (markdown/keyed-map/structured-text)
                tool definitions (data) · filesystem gateway
```

The **pure core** (`domain_model`, `compute_sync_plan`) imports no I/O. The
**seams** are a handful of named functions and gateways. **Adapters** are dialect
mechanisms plus per-tool *data*. **Drivers** are the daemon and the CLI.

---

## 6. Core types (names state what they are)

```
CanonicalDocument     # the lossless per-artifact truth
artifact_id           # canonical UUIDv4; mint_artifact_id() / validate_artifact_id()
ToolSurface           # (tool, kind, location: Path | KeyedMapSlot, surface_format)
SurfaceFormat         # declarative: dialect + known_fields + tool_only_fields + quirks
SurfaceObservation    # what one surface showed this poll:
                      #   tool_surface, embedded_id|None, content_digest, modified_time
SyncState             # what we recorded last poll: artifact_id -> ArtifactRecord
ArtifactRecord        # kind, canonical_digest, surfaces: {tool: (location, digest)}
SyncPlan              # an ordered list of SyncIntent
SyncResult            # changed / failed / blocked / diagnosed counts
```

`SyncIntent` — the vocabulary the planner emits and the executor performs:

| Intent | Meaning |
|---|---|
| `adopt_new_artifact` | id-less candidate group → mint + record + project |
| `absorb_tool_edit` | one tool changed → fold its bytes into the canonical |
| `project_to_tools` | write the canonical onto these tool surfaces |
| `rename_artifact` | name changed → rename projections (archive-old first) |
| `remove_artifact` | authored deletion → archive-then-remove survivors |
| `reproject_canonical` | canonical changed out of band (import) → re-project |
| `report_unadoptable` | unparseable surface → one structured warning |

---

## 7. `compute_sync_plan` — the sync brain (pure)

`compute_sync_plan(observations, sync_state, canonical_digests, now, policy) -> SyncPlan`

A pure function that does the whole decision and nothing else:

1. **Recover identity, never mint.** Group observations by embedded id, then by
   the state that owns the location; the remainder are **candidates**.
2. **Per known artifact**, compare observed vs recorded surfaces → one of:
   unchanged · one-changed (`absorb_tool_edit` + `project_to_tools`) · many-changed
   (conflict: argmax `modified_time`, deterministic tiebreak) · name-changed
   (`rename_artifact`) · surface-missing-from-an-available-tool (`remove_artifact`,
   unless a bulk *glitch* → `reproject_canonical`) · canonical-changed-out-of-band
   (`reproject_canonical`) · pure `mv` (record new location only).
3. **Per candidate group** (same kind + slug): if the winner parses →
   `adopt_new_artifact`; else `report_unadoptable` (no id, never adopted).
4. **Guards:** fewer than two available tools → no destructive intents
   (US-07 AC-5); private / framework-specific content → no projection.

Pure ⇒ the hardest part runs with in-memory inputs, no `tmp_path`, no clock, no
mocks. Every behavioural acceptance criterion is a `compute_sync_plan` assertion.
It is a small package of cohesive pure functions (`plan/recover_identity`,
`plan/reconcile_known`, `plan/adopt_candidates`), not one long function.

---

## 8. `execute_sync_plan` — the hands (thin I/O)

`execute_sync_plan(plan, gateways, now) -> SyncResult`

Walks the plan and performs I/O in the one order that preserves data:

- **Mint** an `artifact_id` for each `adopt_new_artifact` — the *single* mint
  site, atomic with recording the canonical and state (AD-2).
- **Archive before write** — every overwrite/delete/rename goes through
  `artifact_archive` first (NFR-01). The only place destructive I/O happens, so
  the invariant holds by construction.
- **Atomic writes** — single files via temp+rename; skill folders via staged
  swap (NFR-03).
- **Persist** through `canonical_store` and `sync_state_store` (the single
  *intended* writer; two overlapping daemons are a tolerated failure mode —
  atomic writes + recompute-from-disk converge regardless of order, US-09 AC-3).

All translation goes through the two centralized functions in §10; the executor
never knows a dialect.

---

## 9. Persistence gateways (named, specific)

Instead of one vague "store", three named gateways with single responsibilities,
plus a low-level file gateway:

| Gateway | Responsibility | Spec |
|---|---|---|
| `canonical_store` | read/write the canonical document store | NFR-16 |
| `sync_state_store` | read/write `state.json` (atomic; single intended writer, survives an overlapping-daemon race by recompute-from-disk per US-09 AC-3) | FR-15 |
| `artifact_archive` | archive-before-write + tiered retention GC + `prune` | NFR-01/07/08 |
| `atomic_file_writer` | temp+rename, staged folder swap, lock, OS retry | NFR-03 |

These are the only modules that touch the filesystem for persistence.

---

## 10. Centralized translation: two functions, declarative tools

**All conversion between on-disk bytes and the canonical document happens in two
high-level functions, in one module (`translation`):**

```python
def file_to_canonical(
    text: str,
    surface_format: SurfaceFormat,
    prior_canonical: CanonicalDocument | None,
) -> CanonicalDocument: ...        # the single parse path; pure; raises on malformed; never mints

def canonical_to_file(
    canonical: CanonicalDocument,
    surface_format: SurfaceFormat,
    prior_text: str | None,
) -> str: ...                      # the single render path; pure; preserves user formatting

def extract_artifact_id(
    text: str,
    surface_format: SurfaceFormat,
) -> str | None: ...               # id in isolation; never raises
```

Per-tool knowledge is **data**, not code: a `SurfaceFormat` declares the
`dialect`, the `known_fields`, the `tool_only_fields`, and any quirk. The two
functions dispatch on `surface_format.dialect` and apply the declared field map.
There is no per-tool `parse`/`render` to drift; adding a tool adds a declaration.

The **dialect mechanisms** the two functions call (the only place a wire format
is understood):

- `dialects/markdown_frontmatter` — YAML front-matter + Markdown body: split →
  map `known_fields` → keep unknowns in `per_tool_extra` → reassemble.
- `dialects/keyed_map_slot` — one slot inside a shared JSON/TOML file (MCP
  servers); `location` is `(file, slot)`.
- `dialects/structured_text` — JSON/JSONC/TOML round-trip preserving comments and
  key order.
- `dialects/global_rules` — whole-file rules with `@import` resolution and
  framework-specific hold-back (US-15).
- `dialects/mcp_server` — the per-tool MCP dialect differences.

Identity is **not** a translation concern: `file_to_canonical` carries an
embedded id through if present but never mints (AD-2).

---

## 11. Tools as data

```python
@dataclass(frozen=True)
class ToolDefinition:
    name: str
    surfaces: dict[str, ToolSurface]   # kind -> surface (root key, SurfaceFormat, location kind)
    enabled_key: str | None

def agentic_tools_registry(config) -> dict[str, ToolDefinition]: ...
```

Adding a tool is one `ToolDefinition` reusing existing `SurfaceFormat`s — no core
edit (NFR-11). The core iterates the `agentic_tools_registry` and never names a
tool.

---

## 12. Cross-cutting concerns, each with one home

| Concern | Home | Spec |
|---|---|---|
| Secret policy at every egress | `secret_policy` (`find_secret_literals`, `enforce_secret_policy`) | NFR-15, US-13 |
| Rules `@import` + framework-specific hold-back | `dialects/global_rules` | US-15 |
| Privacy (`private: true`) | a `compute_sync_plan` predicate | US-13 |
| Bounded archive + `prune` | `artifact_archive` + a CLI command | NFR-07/08 |
| Daemon resilience | `poll_daemon` counts only *systemic* failures | FR-02, NFR-04 |
| Library export/import (+ cross-machine merge) | `portable_library` (writes canonicals; next plan adopts) | US-12, FR-12/15 |
| Logging | transition-only; one diagnostic per bad surface | NFR-12/13 |

---

## 13. Module map (thin target)

```
agents_sync/
  __main__.py
  poll_daemon.py            poll loop; systemic-only failure budget; GC tick
  command_line_interface.py argparse + export / import / prune / run
  runtime_config.py         load · validate · platform paths

  domain_model/             PURE CORE — entities + the planner
    canonical_document.py   schema, normalise, content-digest
    artifact_identity.py    mint_artifact_id (sole minter) + validate_artifact_id
    tool_surface.py         ToolSurface, SurfaceFormat, slug, candidate key
    sync_plan.py            SyncIntent types + SyncResult
    plan/                   the brain (pure)
      compute_sync_plan.py  entry: observations + state + now -> SyncPlan
      recover_identity.py   embedded/recorded id; candidates
      reconcile_known.py    per-known-artifact decisions
      adopt_candidates.py   candidate grouping -> adopt / report_unadoptable

  read_tool_surfaces.py     surfaces on disk -> SurfaceObservations
  execute_sync_plan.py      perform a SyncPlan via the gateways (the hands)

  translation.py            file_to_canonical · canonical_to_file · extract_artifact_id
  dialects/                 the only place a wire format is understood
    markdown_frontmatter.py  keyed_map_slot.py  structured_text.py
    global_rules.py          mcp_server.py
  tools/                    tool definitions (DATA) + registry
    claude.py codex.py cursor.py copilot.py gemini.py opencode.py antigravity.py
    agentic_tools_registry.py

  canonical_store.py        canonical document I/O
  sync_state_store.py       state.json I/O (atomic, single writer)
  artifact_archive.py       archive-before-write + tiered GC
  atomic_file_writer.py     atomic write, staged folder swap, lock, OS retry
  secret_policy.py          secret detection + egress enforcement
  portable_library.py       export / import (+ last-modified-wins merge)
  parser_bounds.py          parse-size caps (security)
```

~24 modules. `domain_model/` has no I/O imports; `translation` + `dialects/` are
the only places a format is known; the four `*_store` / `*_archive` / `*_writer`
modules are the only places persistence touches disk; tools are data.

---

## 14. Compliance traceability (condensed)

| Cluster | Home |
|---|---|
| Sync matrix, change types, conflict, extend (FR-01,03–10,14; US-01,06,13) | `compute_sync_plan` decides; `execute_sync_plan` + `translation` carry out |
| Identity, adoption, rename (FR-11,12,16; US-03,04) | `artifact_identity`, `plan/recover_identity`, `plan/adopt_candidates`, `execute_sync_plan` (sole mint) |
| Availability, removal, two-tool guard (FR-02,04; US-07,11) | `compute_sync_plan` guards/glitch; `poll_daemon` |
| Import/export, cross-machine (FR-12,13,15; US-12) | `portable_library` → `canonical_store` → plan |
| Data preservation, bounded archive (NFR-01,07,08; US-05) | `artifact_archive` |
| Canonical authority/fidelity/atomicity (NFR-03,06,16) | `canonical_document`, `translation`, `atomic_file_writer` |
| Secrets (NFR-15; US-13) | `secret_policy` |
| Extensibility (NFR-11,18) | `SurfaceFormat` + `ToolDefinition` + `translation` |
| Logging, exit codes (NFR-10,12,13) | `poll_daemon`, `command_line_interface` |
| Clean code (NFR-14) | pure core + small modules + clear names |

Out of scope: **US-16**. One governance wording fix flagged (§17).

---

## 15. Quality outcomes

| Property | Target |
|---|---|
| Total size | ~6–7k LOC (≈ half a conventionally-layered build) |
| Module size | ≤300 lines (≤200 typical) |
| Function size | ≤40 lines |
| Translation paths | exactly 2 (`file_to_canonical`, `canonical_to_file`) |
| Identity mint sites | 1 |
| Persistence touch points | the 4 named gateways only |
| The sync decision | one pure function, tested without a filesystem |
| 602c6d failure class | no code path |
| Per-tool parse/render code | none — tools are data |

---

## 16. Key decisions (ADRs)

- **AD-1 Separate decision from execution.** Pure `compute_sync_plan` →
  `SyncPlan`; thin `execute_sync_plan` performs I/O. *Serves:* NFR-14, every
  behavioural AC.
- **AD-2 Identity minted once, in `execute_sync_plan`, after a successful parse.**
  *Serves:* FR-11; removes the 602c6d class.
- **AD-3 Centralized translation, declarative tools.** Two functions
  (`file_to_canonical` / `canonical_to_file`) over `SurfaceFormat` data; no
  per-tool parse/render. *Serves:* NFR-18, NFR-11, NFR-06/16.
- **AD-4 Named persistence gateways; archive-before-write by construction.**
  *Serves:* NFR-01/03/07/08.
- **AD-5 Canonical is truth; import is not a parallel writer.** *Serves:* NFR-16,
  FR-15.
- **AD-6 Purpose-stating names (AGENTS.md §4).** No bare `Codec`/`Store`/`Clock`;
  every module/function/type names its job in 2–4 words. *Serves:* NFR-14.

---

## 17. Risks, open questions

- **Round-trip fidelity** (NFR-06/16): the only risk surface is the dialects;
  each has a `file_to_canonical`∘`canonical_to_file` round-trip + no-foreign-leak
  test as its contract.
- **The planner growing large**: it is a package of cohesive pure functions; each
  branch is small and independently tested.
- **Governance:** US-09 AC-4 ("archived" vs the safer "quarantined") — recommend
  amending the AC text (needs approval). `agents-sync prune` is a mechanism for
  NFR-07 with no owning story — decide if one is wanted.

---

## 18. Build order (if accepted)

(1) `domain_model/` + `compute_sync_plan` with its pure test suite; (2) the
gateways + `execute_sync_plan` + `translation`; (3) `dialects/` then `tools/`
one tool at a time behind the round-trip contract; (4) `poll_daemon` /
`command_line_interface` / `portable_library`. The behavioural acceptance suite
is written against `compute_sync_plan` first and holds throughout.

---

*A target design. On acceptance, it supersedes `docs/architecture.md`.*
