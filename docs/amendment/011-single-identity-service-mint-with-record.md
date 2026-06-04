# Amendment 011 — Identity is minted only inside the adoption transaction

- status: proposed
- branch: fix/size-explosion-hardening
- date: 2026-06-04
- supersedes / relates to: docs/bugs/602c6d_State_dir_size_explosion_crash_loop.md
  (RC-1, RC-6, FR-11); plan `elegant-bubbling-token`; validated by the
  exploratory prototype `archive/clean_core_prototype/clean_core.py` (AGENTS.md
  §1); relates to amendment 008 (single-writer state) and 001 (id-tag in isolation).

## Motivation

Bug 602c6d, RC-1: discovery mints a fresh random id for any id-less artifact on
every poll (`discovery/enumerator.py:140` keyed-map, `:241` per-file, via
`canonical.new_pair_id`) **before** anything has parsed or recorded it. For the
trigger — a skill whose YAML is malformed such that the id line is also
unrecoverable — each poll mints a *different* UUID, the pair later fails to parse
in adoption and is blocked, and the next poll repeats with a new UUID: unbounded
identity churn (CPU + the 6.08 M error lines) and, on 0.5.x, projection/archive
growth (the 56 GB explosion).

The defect is structural: **minting happens in a different place, and at a
different time, from recording.** RC-6 is the same root seen as duplication —
`new_pair_id` has ~16 call sites (both enumerator sites, `empty_canonical`, and a
dead `elif prior_canonical is None: new_pair_id()` fallback in ~14 adapter
`parse()` functions that the engine immediately overwrites at
`adoption/engine.py:228,346`).

The earlier draft of this amendment proposed detecting the bad artifact and
*freezing* it (a freeze register keyed by path). That is still a patch on a
mint-first flow. Per user direction, the fix is to remove the failure's code
path entirely, not to detect it.

## Principle / decision

**An id is born in exactly one place — the adoption transaction — and only after
the artifact has successfully parsed.** Concretely, validated by the prototype:

1. **Discovery never mints.** It classifies each observed artifact as either
   *managed* (its id is recovered from the bytes in isolation, or from the state
   that already owns its path) or a *candidate* (no id anywhere). Candidates
   carry no id.
2. **Adoption is the sole minter.** Candidates are grouped by
   `(customization_type, target_slug)` (first-boot reconciliation, FR-12 /
   US-03 AC-3); for each group the engine parses the winner, and only on a
   successful parse mints one id (the single `uuid.uuid4()` site) and, in the
   same transaction, records the canonical, injects the id into the source
   bytes, and projects to the other tools.
3. **A malformed candidate never enters the managed set.** Parse precedes mint,
   so a candidate that does not parse returns before any id exists: no mint, no
   record, no projection, one structured diagnostic (NFR-13), invisible to sync
   and removal. There is nothing to freeze because nothing was ever minted —
   this *is* FR-11's "freeze … emit a structured warning", achieved by absence.
4. A managed artifact whose *recovered-id* content later fails to parse (on-disk
   corruption after adoption) keeps the existing freeze-not-remove behavior
   (US-03 AC-11): it is reported blocked, never synced, never removed.

This makes RC-1 impossible by construction (no code path mints without recording,
none mints before parse) and resolves RC-6 (one mint site).

## Proposed governance edits (require user validation)

**None.** FR-11 already mandates id recovery, "shall not mint a new id", and
freeze/structured-warning on unparseable content; US-03 AC-11 and US-12/FR-12
(idempotent first-boot reconciliation) already specify the rest. This amendment
makes the code comply with, and structurally guarantee, the existing governance.
NFR-14 (Clean Code / DRY) is advanced by collapsing ~16 mint sites to one.

> No governance artifact (description, objectives, stories, AC, requirements) is
> edited. Recorded here per the code_change invariant.

## Design edits (architecture — applied after validation)

`docs/architecture.md`:
- §4 module map: `mint_pair_id` moves to `identity.py` (Layer 1, the sole
  `uuid.uuid4()` caller, beside `validate_pair_id`); `new_pair_id` removed from
  `canonical.py`; `empty_canonical(kind, pair_id)` requires `pair_id`.
- §6 `sync_once`: discovery returns *(managed pairs, candidates)*; the new-group
  reconciliation + mint moves into the adoption transaction; the per-pair loop
  processes managed pairs only.
- §8 invariant I-1: minting is owned by `identity`, atomic with recording.
- §5.1 / §7 and `docs/agentic_tool_integration_protocol.md`: adapter `parse()`
  does not assign `pair_id`; `extract_pair_id` is its only id surface.

## Implementation plan

Build the clean core; replace old paths rather than patch them (strangler).

1. `identity.py`: add `mint_pair_id()` — the only `uuid.uuid4()` call site.
2. Discovery (`discovery/`): classify observations into managed pairs (id
   recovered via `extract_pair_id` or `state_owner_for_path`) and a new
   **candidate** channel (id-less). No mint. `walker.discover()` returns the
   candidate list alongside the managed pairs and blocked set.
3. Adoption (`adoption/`): a candidate-adoption step that groups candidates by
   `(kind, target_slug)`, parses the winner, and — only on success — mints once
   via `identity.mint_pair_id()`, records, injects, and projects. Malformed
   candidate → one diagnostic, skip; never minted.
4. `sync.py`: route candidates to the new adoption step; the old
   `_reconcile_new_groups` (which assumed discovery-minted ids) is replaced by
   the candidate grouping above. The per-pair loop handles managed pairs only.
5. `canonical.py`: delete `new_pair_id`; `empty_canonical(kind, pair_id)` makes
   `pair_id` required.
6. Adapters: delete the `elif prior_canonical is None: new_pair_id()` branch and
   the `new_pair_id` import from each `*_io.py` and `mcp_server_io/parse`.

## Test plan

`tests/test_size_explosion_regression.py` (bug-doc §3, red first):
- malformed id-less artifact across N polls → no id ever minted, canonical store
  empty, daemon healthy, exactly one diagnostic;
- clean id-less artifact → minted once, stable across polls;
- managed artifact that becomes malformed → frozen, not removed (extends
  `test_malformed_metadata_freeze.py`).
`tests/test_identity_service.py`: `mint_pair_id` is the single `uuid.uuid4()`
caller (AST/import guard); adapters/discovery do not mint.
Behaviour suite (`test_e2e_sync.py`, `test_first_boot_reconciliation.py`,
`test_antigravity_three_way.py`, …) is the conformance suite and stays green;
unit tests asserting discovery-time minting are rewritten to the candidate model.

## Verification

`bash scripts/ci.sh` green. The 602c6d reproduction (drive a tmp Syncer over a
malformed skill across many polls) shows zero ids minted, an empty canonical
store, and the daemon staying up — matching the prototype.
