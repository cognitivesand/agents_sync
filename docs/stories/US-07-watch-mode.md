# US-07: Continuous watch mode

## Persona

Both

## User Story

As a developer, I want a watch mode that continuously monitors both sides and syncs in near-real-time so that my edits propagate without me invoking any command.

## Priority

Must Have

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given the tool is started with `--watch`, When an edit occurs on either side, Then it is detected and propagated within at most `2 × poll_interval_seconds` (default 4 seconds).
- [ ] AC-2 [Normal]: Given watch mode is running, When `SIGINT` or `SIGTERM` is received, Then the current poll completes if in progress and the process exits cleanly with code 0.
- [ ] AC-3 [Normal]: Given watch mode catches a transient exception during a poll (e.g., a temporary I/O error on one pair), When the next poll occurs, Then the tool resumes normally without operator intervention; the exception is logged at WARN level.
- [ ] AC-4 [Normal]: Given watch mode is running, When systemd restarts the unit, Then on next start the tool reads existing state and continues syncing without re-translating unchanged pairs.
- [ ] AC-5 [Failure]: Given a configured Claude or Codex directory does not exist on startup, When watch mode starts, Then it logs a structured error naming the missing path and exits non-zero with code 2 (configuration error).

## Notes

The 2-second default poll interval is configurable. The propagation latency includes one poll to detect the change and one poll cycle's worth of writes; under nominal load both fit within the same poll, but the worst-case bound is two intervals.

Related requirements: REQ-I-01, REQ-I-04, REQ-Q-01, REQ-Q-03.
