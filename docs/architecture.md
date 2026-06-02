# agents_sync — Architecture

This document describes the architecture of `agents_sync` as it stands at
v0.6, organised around the layers of *Clean Architecture* (Martin, 2017).
It is intended to be useful as both a reader's map of the code and a
governance artefact: any future change should leave this document either
true or amended.

- **Status**: current as of v0.6.0. The Layer-1 canonical store is the
  source of truth (NFR-16); import is canonical-only and per-artifact atomic
  (FR-12/13). The §4 module map predates the v0.6 package split — see the note there.
- **Sources of truth**: the code under `src/agents_sync/`,
  `docs/project_description.md`, `docs/project_requirements.md`, and the
  user stories under `docs/stories/`.
- **Scope**: the production daemon — the installers, CI pipeline, and
  packaging are out of scope here.

---

## Table of Contents

1. [Architectural goals](#1-architectural-goals)
2. [The four layers](#2-the-four-layers)
3. [The Dependency Rule](#3-the-dependency-rule)
4. [Module map](#4-module-map)
5. [Boundary contracts](#5-boundary-contracts)
6. [The principal use case: `sync_once`](#6-the-principal-use-case-sync_once)
7. [Ports and adapters](#7-ports-and-adapters)
8. [Cross-cutting invariants](#8-cross-cutting-invariants)
9. [Traceability to requirements and user stories](#9-traceability-to-requirements-and-user-stories)
10. [Testing strategy, per layer](#10-testing-strategy-per-layer)
11. [Known deviations and technical debt](#11-known-deviations-and-technical-debt)
12. [Worked example: adding a new agentic_tool](#12-worked-example-adding-a-new-agentic_tool)
13. [Glossary cross-reference](#13-glossary-cross-reference)

---

## 1. Architectural goals

The goals this architecture exists to make provably true — not
aspirationally true — are the project goals defined in
[`docs/project_description.md`](project_description.md) ("Goals", goals
1–6). They are the single source of truth; this section does not restate
their text, only the architectural consequence of each, keyed by goal
number so that adding or amending a goal cascades here without
duplication.

| Goal | Source | Architectural consequence |
|---|---|---|
| Goal 1 (propagation ≤ 2 polling intervals) | NFR-02 | A poll-driven use case (`sync_once`) that is a pure function of on-disk state + persisted state. |
| Goal 2 (rename/edit/reorganise preserves identity, never duplicates) | US-04, identity.py | The `customization_artifact_id` is the identity key; discovery groups by it, so a rename re-binds the same artifact rather than minting a new one. |
| Goal 3 (no user content destroyed) | NFR-01 | Every destructive operation goes through an **archive-before-write** gateway (`archive.py`). No alternative write path exists. |
| Goal 4 (unattended recovery from transient errors, as far as possible) | NFR-04, NFR-10 | Use-case code is idempotent and re-entrant; failures inside `process_pair` are caught and logged but do not crash the loop. |
| Goal 5 (new agentic_tool = one spec factory + config keys) | NFR-11, US-10 AC-2 | A frozen-dataclass port (`AgenticToolSpec` / `CustomizationTypeIO`) at the boundary of the use cases; adapters live one layer outside. The sync engine never references a concrete tool name. |
| Goal 6 (no secret silently propagated) | NFR-15 | The configured `secret_policy` is evaluated by the sync core at every egress boundary (parse, render, export, import), not per adapter; `secrets_refused` fails the artifact closed. |

Uncle Bob's "stable abstractions" rule applies directly: the names
`claude`, `codex`, `copilot`, `cursor`, `gemini_cli`, `antigravity`, and `opencode` appear in
adapter modules and in user-provided config keys — **and nowhere else**.
The use cases see only `agentic_tools.values()`.

---

## 2. The four layers

```
┌───────────────────────────────────────────────────────────────┐
│ 4. Frameworks & Drivers                                       │
│    daemon.py · cli.py · config.py · filesystem_windows_retry  │
│    (signals, argparse, TOML, OS retries, __main__)            │
│                                                               │
│   ┌─────────────────────────────────────────────────────────┐ │
│   │ 3. Interface Adapters                                   │ │
│   │    <tool>_io  (one gateway per registered agentic_tool) │ │
│   │    rendering · archive · state (I/O half)               │ │
│   │    agentic_tool_spec (the port that defines the seam)   │ │
│   │                                                         │ │
│   │   ┌───────────────────────────────────────────────────┐ │ │
│   │   │ 2. Use Cases                                      │ │ │
│   │   │    sync.Syncer        (orchestration)             │ │ │
│   │   │    adoption.AdoptionEngine                        │ │ │
│   │   │    discovery.DiscoveryWalker                      │ │ │
│   │   │    tool_status.ToolStatusTracker                  │ │ │
│   │   │                                                   │ │ │
│   │   │   ┌─────────────────────────────────────────────┐ │ │ │
│   │   │   │ 1. Entities                                 │ │ │ │
│   │   │   │    canonical document schema                │ │ │ │
│   │   │   │    pair_id (UUIDv4) — identity.py           │ │ │ │
│   │   │   │    target_slug — state.py (domain half)     │ │ │ │
│   │   │   │    CustomizationArtifactState dataclass     │ │ │ │
│   │   │   │    AgenticToolState dataclass               │ │ │ │
│   │   │   │    sync_types: ArtifactInfo, ToolInfo       │ │ │ │
│   │   │   └─────────────────────────────────────────────┘ │ │ │
│   │   └───────────────────────────────────────────────────┘ │ │
│   └─────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

### Layer 1 — Entities (enterprise business rules)

The objects that would exist even if the project shipped as a library with
no daemon, no CLI, and no filesystem:

- **The canonical document** — a JSON object with `pair_id`, `kind`,
  `name`, `description`, `body`, `tools`, `disallowed_tools`,
  `permission_mode`, `model`, `effort`, and the two passthrough bags
  `per_agentic_tool_only` and `per_agentic_tool_extra`. Runtime facts live
  under `metadata = {"last_modified": float, "generation": int}`. The
  content digest deliberately excludes `metadata`, so timestamp/generation
  stamping is not treated as a user-content edit. Schema constants, metadata
  helpers, the content-only digest, and the empty-document factory live in
  `canonical.py`.
- **`pair_id`** — a canonical UUIDv4 string, validated by
  `identity.validate_pair_id`. The artifact's identity across tools.
- **`target_slug(name)`** — the rule that turns an artifact name into a
  filesystem-friendly basename, including the Windows reserved-name
  guard. Pure function in `state.py`.
- **`CustomizationArtifactState` / `AgenticToolState`** — the in-memory
  shape of the cross-poll persisted view of one artifact: tool locations,
  per-tool digests, and the last projected content digest. It does not carry
  canonical metadata; `last_modified` / `generation` have a single source of
  truth in the canonical document.
- **`CustomizationArtifactInfo` / `AgenticToolInfo`** — the in-memory
  shape of the per-poll observation of one artifact (`sync_types.py`).

These types know nothing about disk, frameworks, tools, or time.

### Layer 2 — Use Cases (application business rules)

The "what the system does in response to inputs":

- **`Syncer`** (`sync.py`) — the top-level use case. Its only public
  method is `sync_once()`. It composes the other three use-case classes
  and runs one poll.
- **`DiscoveryWalker`** (`discovery.py`) — walks the registry, reads
  every artifact, validates `pair_id`s, groups by `pair_id`, and blocks
  any pair whose adoption target would collide with an existing path. Because
  the id is recovered in isolation (point 3 above), a *managed* artifact whose
  surrounding metadata is malformed still appears under its own id and is never
  mistaken for a deletion; the unparseable **content** is dealt with downstream
  by the orchestrator (US-03 AC-11, below).
- **`AdoptionEngine`** (`adoption.py`) — per-pair dispatcher. Decides
  whether to adopt, sync one-way, extend to newly-available tools,
  resolve a conflict by mtime, or propagate a removal.
- **`ToolStatusTracker`** (`tool_status.py`) — keeps each tool's
  `available` / `unavailable` / `disabled` status, logs transitions
  (NFR-12), gates participation per poll (US-11).

These classes accept a `dict[str, AgenticToolSpec]` registry and a
`config` dict and never touch a concrete tool name.

### Layer 3 — Interface Adapters

Two kinds of adapters live here.

**Tool-specific gateways** — one module per agentic_tool, each
implementing the `CustomizationTypeIO` triple `(parse, render,
extract_pair_id)` plus storage shape:

- `claude_io.py` - Claude Code agents, commands, skills, rules, and MCP servers.
- `codex_io.py` - Codex agents and skills; shared helpers cover Codex rules, commands, and MCP rendering.
- `copilot_io.py` - GitHub Copilot CLI agents/skills plus configured VS Code user-profile instructions and prompts.
- `cursor_io.py` - Cursor agents, skills, rules, commands, and MCP servers under user-level file surfaces.
- `gemini_cli_io.py` - Gemini CLI agents, skills, rules, commands, and MCP servers.
- `antigravity_io.py` - Antigravity skills under `~/.gemini/antigravity/skills/<name>/SKILL.md`.
- `opencode_io.py` - OpenCode agents and skills; shared helpers cover OpenCode rules, commands, and MCP rendering.

**Tool-agnostic gateways** that hide platform / filesystem concerns
from the use cases:

- `rendering.py` — projection of canonical onto a tool's storage shape;
  atomic write, atomic skill-directory swap, collision-aware target
  resolution, post-write state update.
- `archive.py` — the data-preservation gateway (NFR-01). Two operations:
  `archive_copy` (snapshot before overwrite) and `archive_move` (move
  into archive before removal).
- `state.py` (I/O half) — `load_state` / `save_state` /
  `atomic_write_text` and the `sha256_file` / `sha256_tree` digest
  helpers. The I/O half is one module away from the entity half above
  for historical reasons; see §11 deviation D-1.

**The port** — `agentic_tool_spec.py` — is the seam that lets adapters
plug into the use cases. The two frozen dataclasses `AgenticToolSpec`
and `CustomizationTypeIO` are the contract; everything else here is an
implementation detail.

### Layer 4 — Frameworks & Drivers

The thinnest possible shell:

- `daemon.py` — `watch(syncer, interval)`: the polling loop, signal
  handlers, error swallowing around `sync_once()`. 37 lines.
- `cli.py` — argparse, legacy-install detection, log configuration,
  `Syncer` construction, `watch()` call. 94 lines.
- `config.py` — platform defaults, TOML loading, structural validation,
  per-OS path conventions.
- `filesystem_windows_retry.py` — a `retry_fs(callable, operation)`
  helper that retries on Windows sharing-violation errors. Pure infra
  shim.
- `__main__.py` — three lines: `raise SystemExit(main())`.

If we ever swapped the polling daemon for a watchman-driven trigger, or
the CLI for a web admin UI, this layer is the only one that should change.

---

## 3. The Dependency Rule

Source code dependencies point inward only:

> Layer N may import from layer N-1, N-2, …, 1. Layer N may **not**
> import from layer N+1 or above.

Three concrete invariants the codebase upholds today:

1. **No use case imports an adapter directly.** `sync.py`, `adoption.py`,
   `discovery.py`, and `tool_status.py` import from `agentic_tool_spec`,
   `rendering`, `archive`, `canonical`, `state`, `identity`, and
   `sync_types`. They do **not** import concrete `*_io.py` adapters. The
   only place adapters are referenced by name is the spec factory layer,
   which is the registry wiring, not a use case.
2. **No entity imports a use case or an adapter.** `canonical.py`,
   `identity.py`, `sync_types.py`, and the dataclasses in `state.py`
   import only from the standard library and from each other. One
   exception, `canonical.py` → `state.atomic_write_text`, is flagged as
   D-1 in §11.
3. **No layer imports from layer 4.** Nothing under `src/agents_sync/`
   imports from `cli`, `daemon`, `__main__`, `config`, or
   `filesystem_windows_retry` except other framework modules. (Note:
   `expand_path` from `config.py` is imported by adapter and use-case
   modules; that is a path-handling utility, not configuration loading.
   See deviation D-2.)

The import graph (verified by `grep -RE "^(from|import) agents_sync" src/`)
forms a DAG with the layer-2 / layer-3 modules at the centre, the adapter modules on the rim, and the framework modules on the
outside.

---

## 4. Module map

### Layer 1 — Entities (pure domain types, no I/O)

| Module | Lines | Role |
|---|---:|---|
| `identity.py` | 19 | UUIDv4 invariant |
| `sync_types.py` | 25 | Per-poll observation types |
| `canonical.py` | 308 | Canonical schema + JSON I/O (D-1) |
| `state.py` | 434 | `CustomizationArtifactState`, `AgenticToolState`, `target_slug`, state JSON gateway, `atomic_write_text` |
| `artifact_names.py` | — | Artifact name helpers |
| `field_names.py` | — | Canonical field name constants |
| `identity.py` | 19 | UUIDv4 pair_id validation |

### Layer 3 — Adapters / ports (I/O boundary)

| Module | Lines | Role | Key inward deps |
|---|---:|---|---|
| `agentic_tool_spec.py` | 344 | `AgenticToolSpec`, `CustomizationTypeIO`, default registry | `tool_specs/` lazily |
| `tool_specs/*.py` | varies | Per-tool `AgenticToolSpec` factories (claude, codex, cursor, copilot, gemini_cli, opencode, antigravity) | concrete IO adapters |
| `claude_io.py` | 154 | Claude SKILL.md / agent / command parser+renderer | `canonical`, markdown helpers |
| `codex_io.py` | 343 | Codex TOML / YAML adapter | `canonical`, `formats/` |
| `cursor_io.py` | 400 | Cursor MDC adapter | `canonical`, markdown helpers |
| `copilot_io.py` | 504 | Copilot instructions adapter | `canonical` |
| `gemini_cli_io.py` | 360 | Gemini CLI adapter | `canonical`, markdown helpers |
| `opencode_io.py` | 333 | OpenCode adapter | `canonical`, `formats/` |
| `antigravity_io.py` | 144 | Antigravity adapter | `canonical` |
| `rules_io.py` | 296 | Global rules file adapter | `canonical`, markdown helpers |
| `slash_command_io.py` | 311 | Slash-command adapter | `canonical` |
| `shared_keyed_map_io.py` | 235 | Shared keyed-map layout (MCP servers in multi-tool files) | `canonical`, `shared_keyed_map_formats` |
| `mcp_server_io/` (8 files) | ~886 | MCP server parse/render pipeline, dialect detection, slot codec | `canonical`, `formats/` |
| `formats/` (4 files) | ~260 | JSON/JSONC/TOML round-trip parsers | — |
| `markdown_yaml_metadata_block.py` | 310 | YAML front-matter extraction, `extract_pair_id_from_md` (FR-11) | — |
| `archive.py` | 156 | `archive_copy` / `archive_move` / `archive_text` / `archive_canonical` gateway (NFR-01) | `filesystem_windows_retry`, `identity`, `state` |
| `rendering.py` | 407 | Canonical → on-disk projection, state update | `agentic_tool_spec`, `config`, `state`, `filesystem_windows_retry` |
| `mcp_secret_policy.py` | 423 | MCP secret literal detection + policy enforcement (NFR-15) | — |
| `parser_bounds.py` | 163 | Parse-buffer boundary helpers | — |
| `filesystem_lock.py` | — | File-based lock primitives | — |
| `filesystem_windows_retry.py` | ~60 | OS-quirk retry shim | — |

### Layer 2 — Use cases (application logic)

| Module | Lines | Role | Key inward deps |
|---|---:|---|---|
| `tool_status.py` | 225 | US-11 availability tracking (`ToolStatusTracker`) | `agentic_tool_spec`, `config` |
| `discovery/walker.py` | 125 | On-disk directory walk, file-event enumeration | `agentic_tool_spec`, `state` |
| `discovery/enumerator.py` | 322 | Per-tool artifact enumeration | `canonical`, `rendering`, `walker` |
| `discovery/collision_blocker.py` | 162 | Duplicate-pair blocking (identity collision) | `canonical`, `state` |
| `discovery/adoption_planner.py` | 163 | Per-poll adoption plan builder | `enumerator`, `state`, `sync_types` |
| `discovery/_host.py` | 41 | Discovery host Protocol | — |
| `adoption/canonical_projection.py` | 210 | `CanonicalProjectionMixin`: extend / project / reproject (CQ-01/CQ-03) | `archive`, `canonical`, `rendering`, `state` |
| `adoption/engine.py` | 631 | Per-pair adopt / sync / conflict / remove orchestrator | `canonical_projection`, `archive`, `rendering`, `state`, `sync_types`, `tool_status` |
| `adoption/removal_propagator.py` | 233 | Orphan-state removal + glitch-guard propagation (US-11 AC-9) | `archive`, `canonical`, `state`, `tool_status` |
| `adoption/privacy_gate.py` | 120 | Per-tool secret-field redaction at projection boundary | `canonical`, `mcp_secret_policy` |
| `adoption/_host.py` | 53 | Adoption host Protocol | — |
| `sync.py` | 517 | Top-level orchestrator: `sync_once`, `_process_discovered_pairs`, `_reconcile_deleted_pairs`, `_record_canonical_baselines`, `_adopt_orphan_canonicals` | `archive`, `adoption`, `agentic_tool_spec`, `config`, `discovery`, `rendering`, `state`, `sync_types`, `tool_status` |
| `portable_archive.py` | 633 | Customization library export/import (US-12 / FR-12/13): `export_to_zip`, `import_from_zip`, `preview_import`, canonical-only import, `last_modified_wins` cross-machine merge | `archive`, `canonical`, `mcp_secret_policy`, `state` |

### Layer 4 — Infrastructure / entry points

| Module | Lines | Role |
|---|---:|---|
| `daemon.py` | 37 | Polling loop (`watch`) |
| `cli.py` | 432 | argparse + entry point (import / export / sync / watch) |
| `config.py` | 472 | TOML config, platform defaults, validation |
| `__main__.py` | 3 | `python -m agents_sync` entry |
| `__init__.py` | 1 | Package version |

**Totals (v0.6 snapshot):** ~65 modules across 5 packages, ~10 600 lines.
Amendment 007 Step 4 completed: table re-tabulated to reflect `adoption/`, `discovery/`, and `portable_archive.py` added in v0.6.

---

## 5. Boundary contracts

Each boundary between layers is mediated by a small, stable contract.

### 5.1 Use case → adapter (the port)

Defined in `agentic_tool_spec.py`:

```python
@dataclass(frozen=True)
class CustomizationTypeIO:
    parse: ParseFn                  # (text, prior_canonical|None) -> canonical
    render: RenderFn                # (canonical, prior_text|None) -> text
    extract_pair_id: ExtractPairIdFn # (text) -> str|None
    storage: str                    # "single_file" | "directory_skill"
    file_suffix: str                # e.g. ".md", "" for skills

@dataclass(frozen=True)
class AgenticToolSpec:
    name: str
    config_dir_keys: dict[str, str]      # customization_type -> config key
    io: dict[str, CustomizationTypeIO]   # customization_type -> IO triple
    disable_config_key: str | None = None
```

Five rules every adapter must obey (US-10 AC-1, AC-4, AC-5, AC-6):

1. **`parse` is pure** and round-trip-stable:
   `parse(render(c, prior), prior) == c` over the
   agentic_tool-relevant subset of `c`.
2. **`render` is pure**. When `prior_text` is provided it preserves user
   formatting where the underlying syntax allows (ruamel round-trip in
   YAML; tomlkit-style in TOML).
3. **`extract_pair_id` never raises** on malformed input. It reads the
   `customization_artifact_id` tag **in isolation**, tolerating a malformed
   surrounding metadata block: it returns the id when the tag is present and
   well-formed (even if the rest of the block is unparseable), and `None` only
   when the tag itself is absent or unreadable (FR-11).
4. **Unknown fields are not dropped**; they live in
   `canonical["per_agentic_tool_extra"][tool_name]` and survive
   round-trips verbatim.
5. **Fields owned by other tools must not leak** into a rendered output
   (NFR-06).

### 5.2 Use case → state (the persistence gateway)

`state.load_state(state_dir) -> dict[pair_id, CustomizationArtifactState]`
and `state.save_state(state_dir, state) -> None` are the only entry
points. `state.json` is schema-versioned (`schema_version=4`). Schema-v3 files
are accepted and migrated in memory by deriving missing `canonical_digest`
baselines from the canonical store; older shapes are treated as missing (the
project is pre-1.0, hence the cutover policy — see `state.load_state`
docstring). Readers ignore legacy `last_modified` / `generation` fields because
the canonical metadata block is now authoritative.

### 5.3 Use case → archive (the preservation gateway)

`archive.archive_copy(state_dir, pair_id, side, source)` and
`archive.archive_move(state_dir, pair_id, side, source)` are the only
two operations that may precede a destructive write. NFR-01 holds iff
**no use-case code path mutates user files without going through one of
these two functions first.** Static auditing this is one test we should
add (see §10).

### 5.4 Use case → rendering (the projection gateway)

`rendering.render_to_agentic_tool(...)` is the only entry point for
writing canonical content out to a tool. It encapsulates:

- target-path computation (`existing_path` or
  `root / target_slug(canonical["name"])`);
- collision refusal (`assert_target_available`);
- single-file atomic-write vs directory-skill staged-then-renamed swap;
- digest recomputation and state-entry update via
  `update_state_n_way`.

`rendering.read_artifact_text` is the symmetric read-side helper used by
discovery and adoption.

`update_state_n_way` records projection paths and per-tool digests only.
It does not stamp content time. Adoption/sync code stamps
`canonical["metadata"]` only when parsed canonical content actually changes;
heal, extend, and unchanged reproject paths leave metadata stable.

### 5.5 CLI → use case

`cli.main(argv)` builds a `merged_config(args)` dict, calls
`validate_config(config)` (fails closed with a structured `ConfigError`,
exit code 2; cf. NFR-10), and hands the result to
`Syncer(config)` followed by `watch(syncer, interval)`.

---

## 6. The principal use case: `sync_once`

`sync_once` is one polling cycle. It is a pure function from
`(on-disk state, persisted state)` to `(new on-disk state, new
persisted state, log lines)`.

```
sync_once
├── validate_config(config)                 ─ fail-closed structural check
├── tool_status.refresh()                   ─ US-11 per-poll status probe
├── load_state(state_dir)                   ─ schema_version=4 envelope
├── discovery.discover(state)               ─ walk available tools, group by pair_id
├── _reconcile_new_groups(discovery, state) ─ v0.4 plan §5.5 multi-tool dedup
├── discovery.block_target_collisions(…)    ─ refuse to clobber unmanaged paths
│
├── for pair_id in discovery:
│       adoption.process_pair(pair_id, info, state)
│         ├── ps is None                     → _adopt_new_pair
│         ├── available tools missing in info → _propagate_removal
│         ├── exactly one changed tool       → _sync_from_agentic_tool
│         ├── ≥ 2 changed tools              → _resolve_conflict_n_way
│         └── no changes but new participants → _extend_to_new_tools
│       on AdapterParseError / YAMLError      → FREEZE: structured warning,
│         add to blocked, no sync, no removal (US-03 AC-11 / FR-11)
│
├── for pair_id in state \ discovery:
│       adoption.propagate_orphan_state(pair_id, state, glitch_tools)
│         (skips entries owned only by `unavailable` tools — US-11 AC-4)
│
└── save_state(state_dir, state)             ─ schema_version=4 envelope
```

Properties this control flow gives us:

Before discovery, `sync_once` adopts orphan canonical documents (canonical-only
imports) into empty state stubs. At the end of the poll it records a
content-only canonical digest baseline for each managed pair.

| Property | How |
|---|---|
| **NFR-01** data preservation | Every destructive branch — adoption pair-id injection, sync-onto-target, conflict-loser-overwrite, removal-of-survivors — goes through `archive_copy` or `archive_move` *first*. |
| **NFR-04** self-healing | Each branch is idempotent: re-running a half-finished cycle observes the same digests and re-derives the same plan. |
| **NFR-05** no-loop degradation | Discovery's digest comparison short-circuits when nothing changed. |
| **NFR-02** latency ≤ 2× interval | One poll catches a change; the next poll's discovery sees the digest delta on the now-projected counterparts and writes nothing further. |
| **FR-02** fault isolation | `sync_once` wraps each `process_pair` and each `propagate_orphan_state` in `try / except Exception` + `logging.exception(...)` — one bad artifact does not halt the loop. |
| **FR-04** trusted removal source | `_propagate_removal` only fires when an **available** tool's view is missing the artifact; entries owned only by **unavailable** tools are preserved (`propagate_orphan_state` short-circuit). |
| **FR-14** content-only canonical detection | `canonical_digest(canonical_content(...))` excludes `metadata`; imports or external canonical content edits reproject, while metadata-only stamps do not. |

### 6.1 Import as a merge — BUILT (v0.6.0)

> **Status: implemented and shipping.** The sections below describe running
> behaviour as of the v0.6 canonical-as-truth work (amendment 002 design;
> amendments 003–004 follow-ups), landed across commits P1–P5:
> NFR-16, FR-12/13/14/15, US-12 AC-5/17/18/19, US-11 AC-8/AC-9, US-05 AC-5. The
> canonical store is the source of truth; `import_from_zip` is canonical-only and
> per-artifact atomic. The importer never writes `state.json`, so the daemon is
> the single state writer while orphan canonicals are adopted on the next poll.

The inversion: **the canonical store becomes the source of truth** (NFR-16); every
tool-side file is a projection. `sync_once` gains a step that projects any managed
artifact present in canonical + `state` but absent from an agentic_tool that
`state` never recorded (freshly imported, or a newly-available tool) — heal, not
remove (US-11 AC-8); an authored deletion (absence of a *recorded* file) stays a
removal. Dropping a canonical archives it first (US-05 AC-5).

On that foundation, `portable_archive.import_from_zip` becomes a **second entry
point** that feeds `sync_once`, not a parallel state writer. It writes only the
**canonical store** — never `state.json` and never an agentic_tool root (US-12
AC-5, canonical-only); the next `sync_once` adopts orphan canonicals into state
and projects the imported artifacts through the unchanged adoption pipeline, so
all tool-side writes keep the archive-before-write discipline (NFR-01).

Import is a **merge keyed by `(customization_type, target_slug(name))`**, not a
blind restore. `_classify` seeds its slug index from the local canonical store
and folds same-slug import candidates before any write, so two canonicals with
the same slug but different `customization_artifact_id`s (the cross-machine case:
the same artifact independently minted on two hosts) reconcile to **one** winner
by the `last_modified_wins` rule: the candidate with the higher `last_modified`
timestamp in its canonical metadata wins; displaced local canonicals are archived
before overwrite (FR-12, AC-7). Ties against a locally-present artifact favour
the local artifact; ties within the imported set are resolved by stable
lexicographic `customization_artifact_id` order. Note: `generation` is a
host-local counter that tracks content changes on a single machine — it is not a
cross-host discriminator and is not used in the collision comparison. This makes
import idempotent and prevents it from manufacturing the slug collisions that
US-03 AC-8 would block.

Writes are **per-artifact atomic** (FR-13): each accepted canonical is staged and
then promoted with `os.replace`, so a failure leaves either the previous
canonical or the complete new canonical — never a partial canonical. Because
import never writes `state.json`, there is no state entry without its canonical.

Because import is a second entry point onto the same `sync_once` foundation rather
than a parallel state writer, it may run **while the daemon is active** (FR-15).
Every daemon `state.json` write goes through `state.atomic_write_text`, and import
does not write `state.json` at all. The daemon reconciles from the **canonical
store** (the heal foundation above, FR-14), so a poll that races an import
converges regardless of ordering: at worst it defers projection of a just-imported
canonical to a later poll, never corrupting state. The net managed state is
identical to running the import and the poll sequentially.

---

## 7. Ports and adapters

`AgenticToolSpec` is the **port**; each `*_io.py` module is an
**adapter** that satisfies it. The factory functions under
`src/agents_sync/tool_specs/` are the wiring; `default_agentic_tools()`
exposes the resulting registry as an ordered dict.

The registry is built explicitly from spec factories. US-10's load-bearing
property is that adding a tool changes the registry/factory layer and config
surface, not the sync algorithm.

### What flows across the port

```
read path (discovery / adoption from a source tool):
    on-disk text  --extract_pair_id-->  pair_id | None
    on-disk text  --parse--------->  canonical (dict)

write path (adoption / sync / extend / conflict resolution onto a target tool):
    canonical (dict)  --render-->  on-disk text
                                   (preserves formatting when given prior_text)
```

The canonical is the only currency that crosses the port; the use cases
never see a `.md`, `.toml`, or `SKILL.md`.

---

## 8. Cross-cutting invariants

Four invariants apply globally and are not the responsibility of any one
module:

| Invariant | Established by | Verified by |
|---|---|---|
| **I-1: pair_id is canonical UUIDv4** anywhere it appears | `canonical.new_pair_id` + `identity.validate_pair_id` | every state-read, every adapter `extract_pair_id`, every archive-path construction |
| **I-2: target paths use `target_slug(name)`** as basename | `state.target_slug` | discovery's `_planned_adoption_targets`; rendering's target computation |
| **I-3: no destructive write without prior archive** | `archive_copy` / `archive_move` | every branch of `adoption.AdoptionEngine` that overwrites or deletes |
| **I-4: every reported failure is structured** (`pair_id`, `tool`, cause) | NFR-13 | `logging.exception` and `logging.error` call sites everywhere |

I-3 is the load-bearing one for NFR-01. A future static-analysis test
should grep the use-case modules for `.write_text` / `.rename` / `.unlink`
/ `shutil.rmtree` calls that are not preceded by an `archive_*` call —
see §10.

---

## 9. Traceability to requirements and user stories

| Layer / module | Carries | Verified by |
|---|---|---|
| `canonical.py`, `identity.py`, `state.py` slug | I-1, I-2, US-04 (rename), schema version v2 | `tests/test_round_trip.py`, `tests/test_codex_round_trip.py`, `tests/test_antigravity_io.py` |
| `sync.Syncer` | description goal 1, NFR-02, FR-02, US-01 | `tests/test_e2e_sync.py`, `tests/test_antigravity_three_way.py` |
| `discovery.DiscoveryWalker` | US-03 (adoption), US-10 AC-3 (kind-restricted participation) | `tests/test_e2e_sync.py`, `tests/test_first_boot_reconciliation.py`, `tests/test_windows_slug_collision.py` |
| `adoption.AdoptionEngine._resolve_conflict_n_way` | US-06 (conflict by mtime), NFR-01 (archive losers) | `tests/test_e2e_sync.py`, `tests/test_antigravity_three_way.py` |
| `adoption.AdoptionEngine._propagate_removal` | description goal 3, FR-04, US-11 AC-4 | `tests/test_e2e_sync.py`, `tests/test_agentic_tool_status.py` |
| `adoption.AdoptionEngine._extend_to_new_tools` | v0.4 plan §5 first bullet (newly-available tool extension) | `tests/test_antigravity_three_way.py` |
| `tool_status.ToolStatusTracker` | US-11 (graceful absence), NFR-12 (log on transition) | `tests/test_agentic_tool_status.py` |
| `archive.py` | NFR-01, NFR-07, US-05 | `tests/test_round_trip.py`, `tests/test_e2e_sync.py` |
| `rendering.py` | NFR-03 (atomic visibility), NFR-06 (round-trip stability) | `tests/test_windows_filesystem_retries.py`, every adapter round-trip test |
| `agentic_tool_spec.py` | description goal 5, NFR-11, US-10 AC-1, AC-2 | `tests/test_agentic_tool_spec.py` |
| `claude_io.py`, `codex_io.py`, `antigravity_io.py` | US-01 per-tool, NFR-06 | `tests/test_round_trip.py`, `tests/test_codex_round_trip.py`, `tests/test_antigravity_io.py` |
| `daemon.py` | US-07 (watch-mode), FR-02 | `tests/test_daemon_signals.py` |
| `cli.py` | NFR-10 (distinct exit codes) | `tests/test_e2e_sync.py` |
| `config.py` | description constraints (per-OS paths), NFR-10 | `tests/test_config_platform_defaults.py`, `tests/test_macos_compat.py` |
| `filesystem_windows_retry.py` | description constraints (Windows operations) | `tests/test_windows_filesystem_retries.py` |

Every requirement in `project_requirements.md` and every story under
`docs/stories/` has at least one module carrying it. Any future
requirement that has no carrying module is a defect in either the
requirement or the architecture.

---

## 10. Testing strategy, per layer

| Layer | What unit tests cover | What integration tests cover |
|---|---|---|
| 1 — Entities | UUID validity, slugify rules, `to_dict`/`from_dict` round-trip, schema constants | n/a |
| 2 — Use cases | per-method behaviour with hand-built spec registries (`tests/test_agentic_tool_status.py`) | the full poll: `tests/test_e2e_sync.py`, `tests/test_first_boot_reconciliation.py`, `tests/test_antigravity_three_way.py` |
| 3 — Adapters | parse/render round-trip per tool, BOM/CRLF tolerance, unknown-field passthrough, malformed-input handling | covered by Layer-2 e2e tests on real `tmp_path` filesystems |
| 4 — Frameworks | signal handling (`tests/test_daemon_signals.py`), CLI exit codes (in e2e), config defaults per OS (`tests/test_config_platform_defaults.py`, `tests/test_macos_compat.py`), Windows retries (`tests/test_windows_filesystem_retries.py`) | n/a |

**Tests we should add** (gaps in current coverage):

- A grep-style guard in `tests/test_no_destructive_writes.py` that
  scans `adoption.py` and `sync.py` for `.unlink`, `.write_text`,
  `shutil.move`, `shutil.rmtree` and asserts each call site is
  textually preceded by an `archive_` call or an explanatory comment.
  Backs I-3 by static inspection.
- A property-based test (Hypothesis) that drives random sequences of
  artifact create / edit / rename / delete operations on each tool and
  asserts NFR-01 (every loss path archived) and NFR-05 (eventual
  quiescence).

---

## 11. Known deviations and technical debt

These are honest gaps between the architecture as drawn and the code as
written. Each is small enough to fix incrementally and large enough to
deserve a name.

### D-1 — `state.py` straddles Layer 1 and Layer 3

`state.py` contains both **domain types** (`CustomizationArtifactState`,
`AgenticToolState`, `target_slug`, `slugify`) and **I/O gateways**
(`load_state`, `save_state`, `atomic_write_text`, `sha256_file`,
`sha256_tree`). The Dependency Rule still holds — both halves only
import inward — but the file mixes layers.

`canonical.py` (Layer 1) imports `state.atomic_write_text` (Layer 3),
which is a strict-Clean violation: an entity reaching out to a gateway.
Refactor: split `state.py` into `entities/artifact_state.py` (dataclasses
+ slugify) and `gateways/state_store.py` (load/save/atomic/digest), and
move `atomic_write_text` into the gateway layer so `canonical.py` either
returns serialised bytes for a gateway to write, or gets its own
gateway.

### D-2 — `config.expand_path` is used as a utility, not a configuration concern

`config.py` exposes `expand_path` which is imported by `discovery.py`,
`rendering.py`, and `tool_status.py`. It is a thin
`Path(value).expanduser().resolve()` wrapper. Either move it into a
neutral `paths.py` (Layer 1 utility) or accept that `expand_path` is
the architectural escape hatch and document it as such. Today it is the
single Layer-4 symbol any use case imports — a real (if narrow)
violation.

### D-3 - The registry is explicit rather than plugin-discovered

`agentic_tool_spec.default_agentic_tools` calls concrete factory functions from
`src/agents_sync/tool_specs/`. This is intentional for the built-in tool set:
it keeps startup deterministic and keeps validation at `AgenticToolSpec`
construction time. A future external-plugin registry would need its own
discovery and fail-closed validation layer.

### D-4 — Codex's two IO modes coexist

`codex_io.py` contains both the `parse_codex_skill_md` /
`render_codex_skill_md` path and the `parse_codex_agent_toml` /
`render_codex_agent_toml` path. Both are active in v0.4.1. The remaining
tradeoff is that TOML rendering is deterministic but does not preserve
comments or original ordering the way the YAML renderers can.

### D-5 — Built-in defaults remain centralised in `config.py`

The sync use cases now resolve roots through `AgenticToolSpec.config_dir_keys`
and the generic `Syncer.tool_root()` helper. Built-in platform defaults,
installer samples, and CLI flags are still centralised in `config.py` and
the installers. That is acceptable for shipped built-ins, but a future
third-party plugin story would need config defaults to move closer to the
adapter metadata.

### D-6 — No static check for I-3 (no-destructive-write-without-archive)

I-3 is the load-bearing invariant for NFR-01 and is currently only
covered transitively by integration tests. A grep-style guard test
(see §10) is the cheapest fix.

---

## 12. Worked example: adding a new agentic_tool

This is the expected path for the next built-in agentic_tool, stated against
the current v0.5 architecture:

| Step | File | Layer | Why |
|---|---|---|---|
| 1 | `src/agents_sync/<tool>_io.py` (new) | 3 | One adapter module implementing `parse`, `render`, `extract_pair_id`, and any tool-specific slugging needed by `CustomizationTypeIO`. |
| 2 | `src/agents_sync/tool_specs/<tool>.py` plus `tool_specs/__init__.py` and registry wiring in `agentic_tool_spec.py` | 3 (port) | Add `build_<tool>_spec` and include it in `default_agentic_tools`. |
| 3 | `src/agents_sync/config.py` | 4 | Add the tool's default roots and enable flag, if it is optional. |
| 4 | `src/agents_sync/cli.py` | 4 | Add explicit override flags for the tool's roots and enable flag. |
| 5 | `tests/test_<tool>_io.py` (new) | tests | Round-trip, BOM/line-ending tolerance, unknown-field passthrough, and no leak of foreign fields. |
| 6 | `tests/test_<tool>_matrix.py` (new or extended) | tests | The US-01 / US-03 / US-06 / US-11 matrix with the new tool in the participating set. |
| 7 | `README.md`, `docs/architecture.md` | docs | One-line entry in the "Module map" table; one-row entry in the README "What It Syncs" table. |

**No tool-specific edits** to `sync.py`, `adoption.py`, `discovery.py`,
`tool_status.py`, `canonical.py`, `rendering.py`, `archive.py`, `state.py`,
`identity.py`, `sync_types.py`, or `daemon.py`. If a new tool needs a new
storage concern, add it to the port (`CustomizationTypeIO`) as a generic
capability rather than branching on the tool name inside the use cases.

---

## 13. Glossary cross-reference

This document uses the terminology defined in
`docs/project_description.md` and
`docs/agentic_tool_integration_protocol.md`. Five terms appear most
often:

- **`agentic_tool`** — an external application that consumes
  user-authored, reusable files (Claude Code, Codex, Antigravity, …); in
  the codebase, the integration module for one such application.
- **`customization_artifact`** — a specific managed instance: identified
  by `pair_id`, present on N agentic_tools. The technical unit of
  synchronisation. Legacy code still uses `pair` and `pair_id`; new code
  uses `customization_artifact` and `customization_artifact_id` where it
  has been refactored.
- **`customization_type`** — the category of a customization_artifact;
  each agentic_tool declares which types it supports. The registered set
  and each type's `file_layout` are defined once in the
  [`docs/project_description.md`](project_description.md) glossary — not
  restated here, so the list does not drift per release.
- **Canonical** — per-artifact JSON document storing the union of fields
  from every agentic_tool; the lossless intermediate that drives every
  renderer.
- **Available / unavailable / disabled** — per-tool status per poll;
  managed by `ToolStatusTracker`. Only `available` tools can be removal
  sources (FR-04).

---

## References

- Martin, Robert C. *Clean Architecture: A Craftsman's Guide to Software
  Structure and Design*. Prentice Hall, 2017.
- `docs/project_description.md` — purpose, scope, goals, glossary.
- `docs/project_requirements.md` — the FR and NFR requirement set.
- `docs/agentic_tool_integration_protocol.md` — the port contract.
- `docs/stories/US-*.md` — user-visible behaviour.
- `docs/v0.4_implementation_plan.md` — Antigravity / N-tool engineering plan.
- `docs/v0.4.1_implementation_plan.md` — opencode and Codex custom-agent follow-up plan.
- `docs/opencode_integration_research.md` — opencode adapter research.
