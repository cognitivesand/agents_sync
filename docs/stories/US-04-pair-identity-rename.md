# US-04: Pair identity persists across rename

## Persona

Alice

## User Story

As a power user reorganizing my agents over time, I want renaming a file or changing its `name` field on either side to keep the sync pair intact (no accidental delete-and-create) so that I can reorganize freely without losing state.

## Priority

Must Have

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given a synced agent pair, When the Claude `.md` file is renamed via filesystem `mv` (frontmatter unchanged, including `pair_id`), Then the next poll updates the stored Claude path and no rewrite occurs on either side.
- [ ] AC-2 [Normal]: Given a synced agent pair, When the Claude side's `name` field is changed in frontmatter, Then on the next sync the canonical's `name` updates, the Codex side's `name` is rewritten, and the Codex file is renamed to match the new slug; the previous Codex filename's content is archived.
- [ ] AC-3 [Normal]: Same as AC-2 but originating from a Codex-side change to the `name` key.
- [ ] AC-4 [Normal]: Given a YAML frontmatter rewrite (e.g., to inject `pair_id` or update `name`), When the rewrite runs, Then existing key order, comments, and quoting style are preserved.
- [ ] AC-5 [Failure]: Given a rename or name change that would produce a slug collision with another existing pair, When the sync runs, Then the rename is rejected, no destructive operation is performed, and a structured error names both colliding pair_ids and slugs.

## Notes

`pair_id` is the stable identity of a pair; the slug derived from `name` is for human-readable filenames and can change. Renaming a file without changing `name` is essentially free (just a state-path update). Renaming through `name` change cascades to the other side: counterpart filename change + archive of the prior filename.

Related requirements: REQ-C-01, REQ-C-02, REQ-Q-08.
