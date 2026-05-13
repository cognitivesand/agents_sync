# US-04: Customization-artifact identity persists across rename

## Persona

Alice

## User Story

As a power user who reorganises my customizations over time, I want renames — whether of the file/folder or of the `name` field, on any of my agentic_tools — to keep each customization linked to its copies elsewhere, so that I can reorganise freely without breaking sync or losing data.

## Priority

Must Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`.

## Acceptance Criteria

- [ ] AC-1 [Normal — filesystem rename, no field change]: Given a synced customization_artifact, When the artifact's file or folder is renamed on any one participating agentic_tool via a filesystem `mv` (artifact metadata unchanged, including `customization_artifact_id`), Then the next poll updates the stored path for that agentic_tool in state, and no rewrite occurs on any agentic_tool.

- [ ] AC-2 [Normal — name field change propagates to all agentic_tools]: Given a synced customization_artifact, When the `name` field is changed in the artifact metadata on any one participating agentic_tool, Then on the next sync: the canonical's `name` updates; every other participating agentic_tool's rendered output reflects the new `name` and its file or folder is renamed to match the new slug; each previously-named file or folder is archived before its rename.

- [ ] AC-3 [Normal — symmetric across agentic_tools]: AC-2 holds regardless of which agentic_tool originated the change. No agentic_tool is privileged.

- [ ] AC-4 [Normal — artifact metadata style preservation on rewrite]: Given an artifact metadata rewrite triggered by AC-2 (or by `customization_artifact_id` injection during adoption), When the rewrite runs on an agentic_tool, Then existing key order, comments, and quoting style in that agentic_tool's artifact metadata are preserved where the underlying format permits.

- [ ] AC-5 [Failure — slug collision]: Given a rename or `name`-field change that would produce a slug colliding with another managed customization_artifact's slug on any participating agentic_tool, When the sync runs, Then the rename is rejected, no destructive operation is performed on any agentic_tool, and a structured error names every colliding `customization_artifact_id` and the conflicting slug.

## Notes

`customization_artifact_id` is the stable identity of a customization_artifact; the slug derived from `name` is for human-readable filenames and can change. Renaming a file or folder without changing `name` is essentially free (just a state-path update on the affected agentic_tool). Renaming through a `name` change cascades across every participating agentic_tool: every other agentic_tool's counterpart filename or folder name changes, and the prior bytes are archived first.

The N-agentic_tool generalisation is structural: the same rename semantics apply regardless of how many agentic_tools participate. At v0.4 release, two agentic_tools support the `agent` customization_type and three support `skill`, but the algorithm does not depend on these counts.

Related requirements: NFR-01.
