# US-07: Continuous background sync

## Persona

Both

## User Story

As a developer using both Claude Code and Codex, I want `agents_sync` to run as a long-lived background daemon that continuously keeps both sides in sync so that my edits propagate without me invoking any command.

## Priority

Must Have

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given the daemon is running, When an edit occurs on either side, Then it is detected and propagated within at most twice the configured polling interval.
- [ ] AC-2 [Normal]: Given the daemon is running, When `SIGINT` or `SIGTERM` is received, Then the current poll completes if in progress and the process exits cleanly with code 0.
- [ ] AC-3 [Normal]: Given the daemon catches a transient exception during a poll (e.g., a temporary I/O error on one pair), When the next poll occurs, Then the daemon resumes normally without operator intervention; the exception is logged.
- [ ] AC-4 [Normal]: Given the daemon is supervised by a user-level service manager, When the daemon is restarted, Then on next start it reads existing state and continues syncing without re-translating unchanged pairs.
- [ ] AC-5 [Failure]: Given a configured Claude or Codex directory does not exist on startup, When the daemon starts, Then it logs a structured error naming the missing path and exits with a non-zero code distinct from a runtime sync failure.

## Notes

The daemon is the only execution mode; there is no separate one-shot CLI invocation. The polling interval is configurable; the propagation latency under nominal conditions includes one poll to detect a change and one poll to write the result. Distinct exit codes (per NFR-10) let the service manager apply the right restart policy on configuration vs runtime failure.

Related requirements: FR-02, NFR-02, NFR-04, NFR-10.
