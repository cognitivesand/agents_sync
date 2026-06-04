# Amendment 014 — No destructive ops until two tools are available (US-07 AC-5)

- status: applied
- branch: fix/size-explosion-hardening
- date: 2026-06-04
- relates to: US-07 AC-5, US-11 AC-1, NFR-01; plan `elegant-bubbling-token` P4.

## Motivation

US-07 AC-5 requires: when fewer than two registered+enabled agentic_tools have
status `available`, the daemon logs each tool's status (US-11 AC-1), does not
exit, and performs **no destructive operations** (no adoption, propagation, or
removal) until at least two are available — sync needs a source and at least one
destination. The code had no such guard: with one available tool, `sync_once`
still adopted a new artifact (minting an id, injecting it into the user's file,
archiving), a destructive write the AC forbids.

## Principle / decision

`sync_once` performs destructive work only when at least two agentic_tools are
`available`. Below that threshold it returns a no-op result immediately after
the per-tool status refresh (which already logs transitions, US-11 AC-1), so the
daemon polls quietly and waits. The threshold is global (tool-level
`available`), matching the AC's "two ... agentic_tools have status available".

## Proposed governance edits (require user validation)

**None.** US-07 AC-5 already specifies this behavior; the change implements it.

## Design edits (architecture — applied after validation)

None beyond honoring the existing §6 control-flow; noted in `sync_once`.

## Implementation plan

`sync.py`: add `_destructive_ops_permitted()` (count of `available` tools >= 2,
with a one-shot INFO on entering the waiting state) and an early no-op return in
`sync_once` when it is false.

## Test plan

`tests/test_two_tool_guard.py`: with one available tool and a new artifact, a
poll adopts nothing (no canonical, file's bytes untouched); once a second tool
is available the same artifact is adopted.

## Verification

`bash scripts/ci.sh` green.
