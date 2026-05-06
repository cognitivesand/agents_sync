# US-09: Crash and concurrent-run resilience

## Persona

Both

## User Story

As a user running `agents-sync` as a long-lived daemon, I want any interruption (kill, crash, power loss, systemd restart) and any rare overlap with a manual `--once` invocation to leave my agents and skills in a recoverable state, without requiring stale-lock recovery or operator action so that the tool stays out of my way even on bad days.

## Priority

Must Have

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given a sync operation is interrupted at any point (during a file write, a state-index write, or a canonical write), When the tool restarts, Then no file is observed in a half-written state by external readers (atomic-rename semantics).
- [ ] AC-2 [Normal]: Given a sync was interrupted before completing, When the tool's next poll runs, Then any pair whose digests no longer match the recorded last-synced state is re-synced from the canonical and the digests are reconciled.
- [ ] AC-3 [Normal]: Given the watcher and a manual `--once` invocation overlap in time, When both write to `state.json`, Then `rename(2)`-based atomic writes guarantee one update wins entirely; the loser's intent (any digest change it intended to record) is observed by the next poll and re-applied.
- [ ] AC-4 [Failure]: Given the canonical for a pair is detected as truncated or unparseable on read, When the tool reads it, Then the canonical is treated as missing for this pair, a structured error is logged, and on the next poll the canonical is rebuilt from the side whose `mtime` is more recent (with the truncated canonical archived first).

## Notes

This story replaces a previously considered "exclusive on-disk lock" mechanism. For a single-user, single-workstation tool, the cost of a lock outweighs the benefit:

- Stale-lock recovery (process died uncleanly) is itself a source of bugs and an additional failure mode.
- Lock acquisition adds error paths (lock-dir missing, no write permission, NFS quirks).
- Aborting a manual `--once` because the watcher holds a lock is a UX footgun: the user typed the command deliberately and got nothing.

Concurrency safety is achieved instead by:

1. **Atomic writes** (write to `.tmp`, `rename(2)`) — no reader ever sees a partial file.
2. **Self-healing polls** — any digest discrepancy is detected and resolved on the next cycle; a "lost update" race lasts at most one poll interval before reconciliation.
3. **Idempotent operations** — the same canonical applied twice produces the same result; redundant work is harmless.

Related requirements: REQ-R-01, REQ-R-03, REQ-R-04, REQ-R-06.
