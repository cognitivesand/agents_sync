# US-01: Bidirectional sync of agents between Claude Code and Codex

## Persona

Both

## User Story

As a developer using both Claude Code and Codex, I want my agent definitions to be kept in sync between the two CLIs in both directions so that I can edit on whichever side is convenient and the other follows automatically.

## Priority

Must Have

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given a synced agent pair, When the Claude `.md` source is edited, Then the Codex `.toml` counterpart reflects the edit within 4 seconds.
- [ ] AC-2 [Normal]: Given a synced agent pair, When the Codex `.toml` source is edited, Then the Claude `.md` counterpart reflects the edit within 4 seconds.
- [ ] AC-3 [Normal]: Given a stable pair where neither side has changed since last sync, When a poll occurs, Then no files are rewritten on either side.
- [ ] AC-4 [Normal]: Given an edit that touches a field representable on only one side (e.g., a Codex-only `sandbox_mode` set by the user), When the sync runs, Then the field is preserved on the originating side and recorded in the canonical, and the other side's file is not invalidated.
- [ ] AC-5 [Failure]: Given a malformed YAML or TOML file on either side, When the watcher polls, Then the tool logs a structured error naming the file and the parse failure, skips that pair for this poll, and continues syncing all other pairs.
- [ ] AC-6 [Failure]: Given the canonical JSON for a pair is corrupted or unparseable, When the watcher polls, Then the tool logs a structured error naming the canonical path, skips that pair, and does not overwrite either side.

## Notes

The bidirectional pipeline goes through a per-pair canonical JSON intermediate. Loop suppression depends on per-side last-written and last-seen digests stored in `state.json`; the tool ignores any change whose current digest matches the digest it itself last wrote.

Round-trip stability — `parse(render(c)) == c` for any canonical `c` — is what keeps loop suppression sufficient. Without it, the tool's own writes could re-trigger syncs.

Related requirements: REQ-F-01, REQ-F-03, REQ-F-07, REQ-P-01, REQ-R-01, REQ-R-02, REQ-R-06.
