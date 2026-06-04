# Amendment 016 — Simplify the full code (behaviour-preserving)

- status: in-progress
- branch: fix/size-explosion-hardening
- date: 2026-06-04
- relates to: NFR-14 (Clean Code), AGENTS.md §3 size limits; plan P7. Umbrella
  record for the structural-simplification pass.

## Motivation

The codebase carries avoidable complexity: a dead duplicated state field
(`last_seen`), ~14 dead adapter mint branches (RC-6 leftover), duplicated
privacy-gate and secret-filter logic, and several modules far over the 300-line
limit (`portable_archive` 633, `engine` 631, `sync` 517, `config` 472,
`mcp_secret_policy` 423). The goal is to make the full code smaller and cleaner
with **no behaviour change** — the test suite is the conformance net.

## Principle / decision

Delete duplication and dead code; route repeated logic through one shared
mechanism; split god-modules into focused ≤300-line modules; keep every public
behaviour identical (suite green at each step). No governance artifact changes.

## Proposed governance edits (require user validation)

**None.** Pure internal refactor; behaviour, requirements, and stories unchanged.

## Implementation plan (each step a commit, suite green)

1. Delete dead duplication: collapse `last_seen`/`last_written` → one `digest`;
   remove `new_pair_id` + the dead adapter mint branches; consolidate the
   duplicated privacy-gate and secret-filter.
2. Thin adapters: shared markdown parse/render helper for the repeated per-tool
   partition/render epilogues; split `copilot_io` (504) into a package.
3. Decompose god-modules into focused ≤300-line modules.
4. Fix deviation D-1: split `state`/`canonical` into entities + gateways.

## Test plan

No new behaviour to test; `bash scripts/ci.sh` (ruff + mypy --strict + full
pytest) stays green at every step, with LOC trending down.

## Verification

`bash scripts/ci.sh` green; `find src -name '*.py' | xargs wc -l` total decreases.
