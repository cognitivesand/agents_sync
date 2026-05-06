# US-08: One-shot sync

## Persona

Alice

## User Story

As a power user, I want a one-shot mode that runs a single sync pass and exits so that I can manually trigger a sync from scripts or for verification.

## Priority

Should Have

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given the tool is invoked with `--once`, When it completes successfully, Then it has run exactly one sync cycle, logged the number of changed pairs, and exited with code 0.
- [ ] AC-2 [Normal]: Given the tool is invoked with no mode flag, When parsing arguments, Then `--once` is the default behaviour.
- [ ] AC-3 [Normal]: Given a watcher process is also running, When `--once` is invoked, Then both processes proceed independently (no lock contention); any conflicting state writes are reconciled on the next poll cycle (see US-09).
- [ ] AC-4 [Failure]: Given an unrecoverable exception occurs during the sync cycle, When `--once` runs, Then the error is logged with structured context (pair_id where applicable, side, operation) and the process exits with code 1.

## Notes

`--once` shares all the sync logic with `--watch`; the only difference is the loop. Useful for scripts (CI hooks, manual verification) and for users who don't want the watcher running.

Related requirements: REQ-F-12, REQ-O-02.
