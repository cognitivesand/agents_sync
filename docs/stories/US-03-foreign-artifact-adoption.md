# US-03: Auto-adoption of foreign artifacts

## Persona

Both

## User Story

As a user who occasionally creates an agent or skill directly on either side outside this tool, I want unmanaged artifacts to be automatically adopted into the sync system and a counterpart created on the opposite side so that I don't have to manually pair them.

## Priority

Should Have

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given a `.toml` file appears in the Codex agents directory with no `pair_id`, When the watcher polls, Then within 2 polls a fresh UUIDv4 `pair_id` is injected into the file, a canonical record is created, and a Claude `.md` counterpart is rendered.
- [ ] AC-2 [Normal]: Same as AC-1 but for an unmanaged Claude `.md` agent file or a `SKILL.md`-bearing skill folder.
- [ ] AC-3 [Normal]: Given a foreign artifact about to be adopted, When adoption runs, Then the original (pre-injection) bytes are first archived under `archive/<pair_id>/<side>/<original-filename>.<ISO-timestamp>`.
- [ ] AC-4 [Normal]: Given an already-adopted artifact (carries `pair_id` and has a canonical record), When the watcher polls, Then no re-adoption occurs.
- [ ] AC-5 [Failure]: Given a foreign artifact whose `name` field slugifies to a slug already used by another pair, When adoption runs, Then adoption is aborted, the artifact is left untouched, and a structured error names both colliding paths and pair_ids.
- [ ] AC-6 [Failure]: Given the archive write fails (permission denied, disk full), When adoption attempts to archive the pre-injection content, Then adoption is aborted, the original file is unchanged, and a structured error is logged.

## Notes

Adoption is the only point at which the tool writes a `pair_id` into a previously untouched user file. The data-preservation rule mandates archiving before injection — no exception. The "watch is always running" assumption means there is no special "first-run adoption mode"; every poll is identical and adopts whatever foreign artifacts have appeared.

Related requirements: REQ-C-01, REQ-C-02, REQ-Q-06.
