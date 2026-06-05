# agents_sync — Thin, Clean Architecture (Proposal)

- **Status:** proposal (for review), rev 4 — hardened against three
  architecture-critique passes. A target design derived from the requirements —
  not from the current code. No code implied.
- **Date:** 2026-06-05
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

1. **Separate the decision from the execution.** A **read phase** gathers and
   *parses* everything the decision needs (the on-disk text, the prior canonical,
   resolved rules `@import`s, target prior-text) into in-memory inputs; then one
   **pure** function, `compute_sync_plan`, decides *what should change* from those
   inputs alone — no I/O, no clock, no randomness during the decision; a thin
   `execute_sync_plan` carries it out. The decision is unit-tested without a
   filesystem. (Purity is *over the gathered inputs* — all reading/parsing happens
   in the read phase, never inside the planner; see §4, §7.)
2. **Two centralized translation functions.** `file_to_canonical` and
   `canonical_to_file` are the *only* places bytes become a canonical document or
   vice versa. Each interprets a declarative `SurfaceFormat`; the common dialects
   are declarations, the genuinely-different ones (rules `@import`, MCP dialects)
   are shared dialect modules — never per-tool parse/render copies.
3. **One home per concern.** One identity mint site, one persistence gateway
   (archive-before-write by construction), one secret-policy enforcer.

Result: a hexagonal design with a small, fully unit-testable core, ~24 modules,
materially smaller than a conventionally-layered build (target ~6–7k LOC, to be
*measured* as it is built, not assumed). By construction the bug-602c6d re-mint
failure class has no code path: identity is minted only after a successful parse
(AD-2), and a malformed *managed* artifact is *frozen*, not re-identified (§7).

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
3. **Sync is a pure decision over gathered inputs.** The truth for every managed
   artifact is its **stored canonical**, loaded cheaply from `canonical_store` —
   that is what the planner reasons over (secrets, `private`, projection, heals
   all read it, so they work even when no source surface changed). The read phase
   adds: the cheap `content_digest` + recovered id of every surface; a **fresh
   re-parse** of a tool file (`file_to_canonical` + `@import` resolution) **only
   for a surface whose digest changed** — the one expensive case, needed to
   *absorb* an edit; and, for any target the planner will **write**
   (project/extend/heal/rename), an inspection of that target's current bytes to
   honour the framework-specific / privacy / secret guards on the target. So an
   idle poll is digest-only and cost scales with *changes + writes*, not the whole
   tree (NFR-05/08/09). Given those inputs and the recorded `SyncState`, a pure
   function yields a `SyncPlan`; the planner does no I/O. Executing it is a
   separate, thin step.

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
SurfaceObservation    # what the read phase gathered for one surface this poll:
                      #   tool_surface, embedded_id|None, content_digest, modified_time,
                      #   parsed: CanonicalDocument | ParseFailure,   # parsed in the read phase
                      #   resolved_context                            # @imports, target prior-text
SyncState             # what we recorded last poll: artifact_id -> ArtifactRecord
ArtifactRecord        # kind, canonical_digest, surfaces: {tool: (location, digest)}
SyncPlan              # ordered list of SyncIntent; each intent is one per-artifact unit
SyncResult            # changed / failed / blocked / frozen / diagnosed counts
```

`SyncIntent` — the vocabulary the planner emits and the executor performs. Each
intent is a **transaction over the artifact(s) it touches**: the executor applies
it all-or-nothing (see §8) — one artifact for most intents; the two records an
`adopt_new_artifact`-with-retire spans, or the colliding set a `reject_collision`
brackets. A flat list still gives atomic-across-losers behaviour because the
transaction boundary is the intent, not the list.

| Intent | Meaning |
|---|---|
| `adopt_new_artifact` | id-less candidate group → mint + record + project (reusing a local id on a cross-identity slug merge, retiring the other — US-12 AC-7) |
| `absorb_tool_edit` | one tool changed (by digest) → fold its bytes into the canonical |
| `absorb_into_managed` | a new (id-less) artifact at a *managed* artifact's key → managed wins: archive the new bytes under the existing id, project the managed canonical over it, add its tool to the entry; no mint (US-03 AC-6) |
| `project_to_tools` | write the canonical onto these tool surfaces (skipping a target whose name is reserved on that tool — US-13 AC-8) |
| `rename_artifact` | name changed → rename projections (archive-old first) |
| `remove_artifact` | authored deletion → archive-then-remove survivors |
| `reproject_canonical` | canonical changed out of band (import) → re-project |
| `freeze_artifact` | managed artifact whose content won't parse → blocked, not synced, not removed, not re-identified (FR-11) |
| `rebuild_corrupt_canonical` | canonical-store entry truncated/unparseable → archive it, rebuild from the newest-mtime tool (US-09 AC-4) |
| `reject_collision` | a slug would collide with another managed artifact → no destructive op, structured error (US-04 AC-5, US-03 AC-8) |
| `report_unadoptable` | id-less candidate that won't parse → one structured warning, never minted |

---

## 7. `compute_sync_plan` — the sync brain (pure)

`compute_sync_plan(observations, sync_state, canonical_digests, now, policy) -> SyncPlan`

A pure function over the gathered observations and recorded state:

1. **Recover identity, never mint.** Group observations by embedded id, then by
   the state that owns the location; the remainder are **candidates**.
2. **Per known (already-managed) artifact:**
   - **Content won't parse** (the read phase returned `ParseFailure`) → `freeze_artifact`:
     the id was recovered, so it stays managed — not synced, not removed, not
     re-identified (FR-11).
   - **Change detection is by digest** — a surface changed iff its `content_digest`
     differs from the recorded digest. None changed → unchanged (plus extend to
     newly-available tools). One changed → `absorb_tool_edit` + `project_to_tools`.
     Two or more changed → conflict: winner is argmax `modified_time`; on a tie,
     a deterministic tiebreak by tool `name` (Unicode-normalised, case-folded) with
     a `WARN tied-mtime` line (US-06 AC-4; the same tiebreak governs an
     adoption-time tie, US-03 AC-7); then `absorb_tool_edit(winner)` +
     `project_to_tools(rest)`. (Digest, not mtime, is the change *detector*; mtime
     is only the conflict tiebreaker.)
   - **`name` changed** → `rename_artifact`; if the new slug collides with another
     managed artifact → `reject_collision` instead (no destructive op).
   - **Two managed artifacts resolve to the same key** (different ids) →
     `reject_collision` for both, untouched, structured error (US-03 AC-8).
   - **Surface missing from an available tool** → `remove_artifact`, unless this is
     a *glitch* — **≥2 of that tool's recorded artifacts vanished in this poll on an
     available tool** (US-11 AC-9) — in which case `reproject_canonical`.
   - **Canonical changed out of band** (its store digest moved, no tool changed) →
     `reproject_canonical`. **Canonical-store entry corrupt** → `rebuild_corrupt_canonical`.
   - **Pure `mv`** (same digest, new location) → record the new location, no rewrite.
3. **Per candidate group** (same kind + slug across tools): the winner already
   parsed in the read phase → `adopt_new_artifact` (merging a cross-identity slug
   match onto the local id, retiring the other — US-12 AC-7); if it failed to parse
   → `report_unadoptable` (no id minted). A candidate whose slug matches an
   *already-managed* artifact is **not** a collision — managed wins:
   `absorb_into_managed` (archive the new bytes under the existing id, no mint —
   US-03 AC-6).
4. **Guards:** fewer than two available tools → no destructive intents — none of
   `adopt_new_artifact`, `absorb_into_managed`, `project_to_tools`,
   `rename_artifact`, `remove_artifact` (US-07 AC-5); private / framework-specific
   content → no projection (US-13/15).

Pure-over-gathered-inputs ⇒ the hardest part runs with in-memory inputs, no
`tmp_path`, no clock, no mocks. Every behavioural acceptance criterion is a
`compute_sync_plan` assertion. It is a small package of cohesive pure functions
(`plan/recover_identity`, `plan/reconcile_known`, `plan/adopt_candidates`), not
one long function.

---

## 8. `execute_sync_plan` — the hands (thin I/O)

`execute_sync_plan(plan, gateways, now) -> SyncResult`

Walks the plan and performs I/O in the one order that preserves data. **Each
intent is applied as a per-artifact transaction** — all-or-nothing:

- **Atomic across losers** (`rename_artifact`, conflict `absorb_tool_edit`,
  `remove_artifact`, and `reproject_canonical` — which preserves displaced bytes
  per FR-14): archive *every* affected file first; only if all archives succeed
  are any overwrites/deletes performed and state mutated. If any archive fails,
  the intent is abandoned with no overwrite and no state change, and is retried
  next poll (US-06 AC-6, US-03 AC-9). The transaction scope is the artifact(s) the
  intent touches — one for most intents; the two records an
  `adopt_new_artifact`-with-retire spans; the colliding set for `reject_collision`
  — so the boundary is the intent, not the whole plan.
- **Mint** an `artifact_id` for each `adopt_new_artifact` — the *single* mint
  site. The canonical is written before the state entry; an interruption between
  the two leaves a canonical with no state entry, which the next poll heals
  (orphan-canonical adoption, NFR-04) — so the mint is effectively atomic with
  recording (AD-2).
- **Archive before write** — every overwrite/delete/rename goes through
  `artifact_archive` first (NFR-01). The only place destructive I/O happens, so
  the invariant holds by construction.
- **Atomic visibility** — single files via temp+rename; skill folders via a
  staged swap, so a reader sees the whole prior or whole new folder, never a
  partial one (NFR-03).
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
| `artifact_archive` | archive-before-write + tiered retention GC (low-frequency daemon tick; no user-facing command) | NFR-01/07/08 |
| `atomic_file_writer` | temp+rename, staged folder swap, OS-quirk retry (no on-disk lock — concurrency is handled by atomic writes + recompute, not locking) | NFR-03 |

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
) -> CanonicalDocument: ...        # the single full-parse path; pure; raises on malformed; never mints

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

A `SurfaceFormat` is a **recipe**, never code: the `dialect`, the `known_fields`,
the `tool_only_fields`, the reserved customization names for that surface (the
tool's built-in command names — e.g. opencode's `build`/`plan` — that a user
artifact must not shadow; US-13 AC-8), and — for whole-file rules — the ordered
standard filenames with their precedence (prefer `AGENTS.md`, refuse names not on
the list; FR-10). The two core functions dispatch on `dialect` and apply the
recipe; the agentic-tool files supply recipes only and perform no translation.

Honest scope of "tools are data": a tool that fits an existing dialect is a pure
declaration — most are. Tools whose *wire behaviour* genuinely differs (Codex's
whole-TOML agents, Cursor's HTML-comment command id, the per-tool MCP transport/
auth field names, rules `@import`) are handled by **shared dialect modules**, not
by per-tool `parse`/`render` copies. So the duplication NFR-18 targets is gone
(no N parallel codecs), even though dialect *code* exists; what's "data" is the
per-tool field maps and quirks, not the wire mechanics.

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

`file_to_canonical` *raises* on malformed content; the read phase catches that
and records a `ParseFailure` in the observation (so the planner sees
`CanonicalDocument | ParseFailure` and routes to `freeze_artifact` /
`report_unadoptable` — it never sees a raise). `extract_artifact_id` is a
lightweight id-probe, not a second full parse: it reads only the id in isolation
(FR-11) and never raises. Both functions stay pure: the render-egress secret
check is the executor calling `secret_policy` before it writes a target, never
inside `canonical_to_file`.

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
tool. A tool file contributes only `SurfaceFormat` recipes; it contains **no
translation code** — `file_to_canonical` / `canonical_to_file` (and the shared
dialect modules they call) perform every translation, in both directions.

---

## 12. Cross-cutting concerns, each with one home

| Concern | Home | Spec |
|---|---|---|
| Secret policy at all four egress points | the planner refuses to **adopt/propagate** a secret-bearing canonical under `secrets_refused` (reading the stored/absorbed canonical, so it holds even for an unchanged artifact being projected — US-13 AC-5, file left untouched); the executor re-checks at each **write/render** egress before writing a target; `portable_library` checks on **export** and **import** and sets the manifest's `contains_secret_literals` flag. Under `secrets_accepted`, one structured warning per affected artifact per poll. | NFR-15, US-13 |
| Rules `@import` + framework-specific hold-back | `dialects/global_rules` (resolved in the read phase) | US-15 |
| Privacy (`private: true`) | a `compute_sync_plan` predicate | US-13 |
| Bounded archive | `artifact_archive` tiered GC on a low-frequency daemon tick (internal; no user-facing command) | NFR-07/08 |
| Daemon resilience | `poll_daemon` counts only *systemic* failures | FR-02, NFR-04 |
| Library export/import | `portable_library` **previews** a dry-run plan (the same `compute_sync_plan` over the imported canonicals vs local) **before any write**, requiring `--force` if a local artifact would be displaced (US-12 AC-18); a cross-identity slug match reconciles onto the local id and retires the other, the later `last_modified` winning (ties favour the local artifact, else a deterministic total order — FR-12); accepted canonicals are then written and the next poll adopts them | US-12, FR-12/15 |
| Bounded/stable resources | idle polls are digest-only + cheap canonical loads; a tool-file re-parse runs only to absorb a changed surface, and target inspection only for surfaces being written; cost is linear in *changes + writes* (NFR-09), idle polls flat (NFR-05/08); the planner accumulates nothing; the GC bounds the archive | NFR-08, NFR-09 |
| Logging | transition-only; one diagnostic per bad surface | NFR-12/13 |

---

## 13. Module map (thin target)

```
agents_sync/
  __main__.py
  poll_daemon.py            poll loop; systemic-only failure budget; GC tick
  command_line_interface.py argparse + export / import / run
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
  sync_state_store.py       state.json I/O (atomic; single intended writer)
  artifact_archive.py       archive-before-write + tiered GC
  atomic_file_writer.py     atomic write, staged folder swap, OS-quirk retry (no lock)
  secret_policy.py          secret detection + egress enforcement
  portable_library.py       export / import: preview-then-write, last-modified-wins merge
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
| Resource bounds (NFR-08,09) | pure planner is O(artifacts × tools) with no cross-poll accumulation; `artifact_archive` GC bounds disk |
| Clean code (NFR-14) | pure core + small modules + clear names |

Out of scope: **US-16**. One governance wording fix flagged (§17).

---

## 15. Quality outcomes

| Property | Target |
|---|---|
| Total size | target ~6–7k LOC, *measured as built* (no baseline asserted) |
| Module size | ≤300 lines (≤200 typical) |
| Function size | ≤40 lines |
| Full-parse / render paths | exactly 2 (`file_to_canonical`, `canonical_to_file`); plus one lightweight `extract_artifact_id` id-probe |
| Identity mint sites | 1 |
| Persistence touch points | the 4 named gateways only |
| The sync decision | one pure function, tested without a filesystem |
| bug-602c6d re-mint class | no code path (parse precedes mint; malformed managed artifact is frozen, not re-identified) |
| Per-tool parse/render *copies* | none — field maps are data; wire mechanics live in shared dialect modules |

---

## 16. Key decisions (ADRs)

- **AD-1 Separate decision from execution; the planner is pure over gathered
  inputs.** A read phase parses and resolves everything; pure `compute_sync_plan`
  → `SyncPlan`; thin `execute_sync_plan` performs I/O, applying each intent as a
  per-artifact transaction. *Serves:* NFR-14, NFR-01 (atomic-across-losers), every
  behavioural AC.
- **AD-2 Identity minted once, in `execute_sync_plan`, after a successful parse;
  a malformed *managed* artifact is frozen, not re-identified.** *Serves:* FR-11;
  removes the bug-602c6d re-mint class.
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
- **The read phase must gather *every* decision input** (parsed canonical,
  resolved `@import`s, target prior-text, prior canonical). If one is missed the
  decision is silently wrong. Mitigation: `SurfaceObservation` makes the required
  inputs explicit fields — a planner branch that needs an absent input is a type
  error, not hidden I/O; and the planner is forbidden from importing any gateway.
- **Governance:** resolved — US-09 AC-4 now says a corrupt canonical is
  *quarantined* (amendment 018), matching the shipped behaviour and the
  state.json convention; archive GC is daemon-internal (no user-facing `prune`
  command), so NFR-07 needs no new story. No open governance items remain.

> Revised against **two** architecture-critique passes. Rev 2 closed the first
> set (planner purity framing, atomic-across-losers, FR-11 freeze, import
> preview/`--force`, reserved names, corrupt-canonical rebuild, cross-identity
> retire, NFR-08/09, glitch threshold, digest-vs-mtime, filename precedence, lock
> contradiction). Rev 3 closed the verification pass's residuals: the **parse**
> secret egress (the missing fourth point), gating the read-phase enrichment to
> *changed* surfaces (NFR-05/08/09), intent transactions scoped to the artifact
> *set* (multi-artifact adopt-with-retire / collision), `reproject_canonical`
> archiving displaced bytes (FR-14), the new `absorb_into_managed` intent
> (US-03 AC-6), the mtime-tie tiebreaker (US-06 AC-4), the FR-12 import tie rule,
> and the `ParseFailure`/`extract_artifact_id` contract, and removed the
> user-facing `prune` command (archive GC is daemon-internal). Rev 4 corrected an
> over-aggressive rev-3 optimisation (gating *all* enrichment to changed
> surfaces, which had starved the secret/privacy/framework-target and US-11
> AC-8/AC-9 heal decisions): the planner now reasons over the **stored canonical**
> for every artifact, tool-file re-parse runs only to absorb a changed surface,
> write-targets are inspected on write, and the render-egress secret check is an
> executor `secret_policy` call (the renderer stays pure). The US-09 AC-4 wording
> is resolved (amendment 018, "quarantined"); no open governance items remain.

---

## 18. Build order (if accepted)

The detailed, gated, step-by-step build plan is in
`docs/architecture_implementation_plan.md`: small independently-testable steps
(pure core → translation → gateways → read/execute → tools/drivers → cutover),
each executed through the **`incremental_step`** skill (detail → docs →
tests + `/audit-tests` → code → run → `/code_and_tests_quality_review` →
spotless → `/bcp`). The behavioural conformance suite holds throughout.

---

*A target design. On acceptance, it supersedes `docs/architecture.md`.*
