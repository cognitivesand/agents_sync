# Amendment 012 — Per-artifact failures never down the daemon (RC-4 / FR-02)

- status: applied
- branch: fix/size-explosion-hardening
- date: 2026-06-04
- relates to: docs/bugs/602c6d_State_dir_size_explosion_crash_loop.md (RC-4, §5.3);
  amendment 011 (clean identity core); FR-02, US-07 AC-3, NFR-04.

## Motivation

Bug 602c6d, RC-4: `daemon.watch` exits after `max_consecutive_failures` (5) polls
whose `SyncResult.failed` is non-empty (`daemon.py:81-101`). A *single*
unresolvable artifact that fails to process on every poll therefore downs the
whole daemon within five polls; the supervisor restarts it and it fails again —
a crash loop. One bad artifact halting the entire daemon directly contradicts
FR-02 (fault isolation): the other artifacts and tools must keep syncing.

Amendment 011's clean identity core already removed the most common trigger (a
malformed, id-less skill is now an unadoptable *candidate* — dropped from
discovery, reported `blocked`, never `failed`). But a genuinely failing managed
artifact (e.g. a rules `@import` that fails closed, US-15 AC-4) still lands in
`SyncResult.failed` every poll and would still crash-loop the daemon.

## Principle / decision

**The daemon's consecutive-failure exit budget counts only *systemic* failures —
a `sync_once` that itself raises — never per-artifact failures.** A poll that
returns is a healthy poll of the loop mechanism, even if some artifacts failed:
those faults are isolated (FR-02), surfaced, and retried next poll, but they do
not advance the exit budget. Persistent per-artifact failures are logged on
*transition* (NFR-12), not on every poll, so a stuck artifact is visible without
re-spamming. Exit code 1 (runtime failure, NFR-10) still occurs when `sync_once`
raises on `max_consecutive_failures` consecutive polls (a real systemic fault:
unreadable state dir, broken config surfaced at runtime, etc.).

## Proposed governance edits (require user validation)

**None.** FR-02 (fault isolation), US-07 AC-3 (transient-exception recovery), and
NFR-04 (self-healing) already require this; the change makes the daemon comply.
NFR-10's runtime exit code is preserved (systemic-exception path). No
requirement, story, or AC text changes.

## Design edits (architecture — applied after validation)

`docs/architecture.md` §6 / the daemon notes: the consecutive-failure budget is
a *systemic*-failure circuit-breaker, not a per-artifact one.

## Implementation plan

`daemon.py::watch`:
- whole-poll exception → `consecutive_failures += 1` (unchanged; systemic).
- `sync_once` returned → reset `consecutive_failures = 0`. If `result.failed`
  changed since the previous poll, log it once at WARNING (transition); do not
  advance the budget.
- Update the module docstring and `DEFAULT_MAX_CONSECUTIVE_FAILURES` doc to say
  "consecutive whole-poll exceptions".

## Test plan

`tests/test_daemon_signals.py`:
- per-artifact failures across many polls then stop → exit 0 (daemon stays up).
- consecutive whole-poll exceptions reaching the budget → exit 1.
- a clean (or merely failed-pair) poll resets the systemic-exception counter.
- persistent identical `failed` set logs once (transition), not per poll.

## Verification

`bash scripts/ci.sh` green. A persistently failing artifact no longer exits the
daemon; a persistently raising `sync_once` still does.
