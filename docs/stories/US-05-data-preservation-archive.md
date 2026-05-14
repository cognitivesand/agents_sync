# US-05: Data preservation — never destroy user content

## Persona

Both

## User Story

As a user who values my customizations, I want every operation that would overwrite or remove one of them to first archive a copy of the prior contents, so that I can recover from any sync mistake or audit any change.

## Priority

Must Have

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given a sync operation that would overwrite content not reproducible from the current canonical (adoption of a new artifact, conflict-tiebreaker overwrite, retired filename during rename), When the overwrite runs, Then the prior bytes are first written to `~/.local/state/agents-sync/archive/<customization_artifact_id>/<agentic_tool_name>/<original-filename>.<ISO-UTC-timestamp>`.
- [ ] AC-2 [Normal]: Given the user has removed the customization_artifact's file or folder from one participating agentic_tool, When the daemon detects the absence and propagates the removal to every other participating agentic_tool, Then each other agentic_tool's file or folder is moved to archive — never `rm`'d.
- [ ] AC-3 [Normal]: Given a routine retranslation overwrite where the prior content is byte-equal to a render of the current canonical, When the overwrite runs, Then no archive entry is created (avoids noise without losing recoverable information).
- [ ] AC-4 [Failure]: Given the archive directory cannot be written (permission, disk full, etc.), When the tool needs to archive, Then the destructive operation that triggered the archive is aborted, the original file remains untouched, and a structured error is logged.

## Notes

The archive layout is partitioned by `customization_artifact_id` and `agentic_tool_name` for deterministic per-customization_artifact recovery. ISO 8601 UTC timestamps with `:` replaced by `-` ensure filesystem portability and avoid same-day collisions when the same file is overwritten multiple times in a day.

The tool internally uses `.tmp` and `.old` staging directories during atomic swaps; these are exempt from the archive rule because they hold only intermediate, reproducible state, not user-authored bytes.

Related requirements: NFR-01 (data preservation), NFR-07 (bounded archive growth), FR-04 (trusted removal source — archive-before-delete fires only on a real removal signal).
