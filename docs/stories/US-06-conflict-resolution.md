# US-06: Conflict resolution by last-modified time

## Persona

Both

## User Story

As a user who may occasionally edit both sides between polls, I want the most recently modified file to win (with the loser archived) so that conflicts resolve automatically and predictably without halting sync.

## Priority

Should Have

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given both sides of a pair have current digests differing from `last_synced_digest` (both edited since last reconciliation), When the watcher polls, Then the side whose file `mtime` is more recent is chosen as the winner; the canonical updates from it; the other side is overwritten; the overwritten side's prior bytes are archived first.
- [ ] AC-2 [Normal]: Given a conflict resolution completes, When it does, Then a `WARN conflict resolved` log entry is emitted naming the pair_id, both mtimes, the winner, and the archive paths of the loser.
- [ ] AC-3 [Normal]: Given two sides have identical `mtime` (millisecond-equal), When the watcher resolves the conflict, Then a deterministic tiebreaker (Claude wins) is applied and a `WARN tied-mtime` is logged.
- [ ] AC-4 [Failure]: Given the archive write fails during conflict resolution, When the tool attempts to overwrite the loser, Then no overwrite is performed, both sides retain their content, and a structured error is logged.

## Notes

The 2-second default polling window makes simultaneous human edits to both sides extremely unlikely; this story exists primarily as a safety net rather than a frequently-hit code path. Conflict *detection* compares current digests against `last_synced_digest` (not against `mtime`); `mtime` is used only as the tiebreaker once a divergence has been detected.

Related requirements: REQ-C-01, REQ-Q-06.
