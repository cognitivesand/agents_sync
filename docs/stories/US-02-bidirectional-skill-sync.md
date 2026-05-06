# US-02: Bidirectional sync of skill folders between Claude Code and Codex

## Persona

Both

## User Story

As a developer using skills on both Claude Code and Codex, I want skill folders kept in sync in both directions, including `SKILL.md` and any auxiliary files, so that I can maintain skills once.

## Priority

Must Have

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given a synced skill pair, When the Claude side's `SKILL.md` is edited, Then the Codex side's `SKILL.md` reflects the change within 4 seconds.
- [ ] AC-2 [Normal]: Given a synced skill pair, When a non-`SKILL.md` file inside the Claude skill folder is added, modified, or moved, Then the Codex side's folder reflects the change within 4 seconds.
- [ ] AC-3 [Normal]: Same as AC-2 in the reverse direction (Codex → Claude).
- [ ] AC-4 [Normal]: Given a sync in progress, When an external reader opens the target skill folder during the swap, Then it sees either the old folder or the new folder, never an empty or partial folder.
- [ ] AC-5 [Normal]: Given an auxiliary skill file with executable mode bits set on the source side, When the file is propagated to the other side, Then mode bits are preserved.
- [ ] AC-6 [Failure]: Given a skill folder whose `SKILL.md` is missing, When discovery runs, Then the folder is not treated as a skill and the tool logs a structured warning naming the folder.
- [ ] AC-7 [Failure]: Given the staged tmp directory cannot be created (disk full, permission denied), When a sync attempts the swap, Then the operation is aborted, neither side is altered, and a structured error is logged.

## Notes

`SKILL.md` is the only side-rendered file; auxiliary files are copied verbatim. The atomic swap stages the new tree as `.<name>.tmp`, renames the live tree to `.<name>.old`, renames `.tmp` into place, and archives `.old` — so the missing-target window is bounded by two `rename(2)` calls rather than the duration of a `copytree`.

For pair-level conflict purposes, a skill is a single unit: an edit to any file inside the tree counts as a side change.

Related requirements: REQ-Q-01, REQ-Q-02, REQ-Q-07.
