# Amendment 015 — Identity persists across rename (US-04)

- status: in-progress (AC-1 applied; AC-2/AC-3/AC-5 pending)
- branch: fix/size-explosion-hardening
- date: 2026-06-04
- relates to: US-04 AC-1/AC-2/AC-3/AC-5, NFR-01, NFR-06; plan P5.

## Motivation

US-04 requires identity to survive a rename, but the code never renames files:

- AC-1 (pure `mv`, metadata unchanged): the moved file is rediscovered by its
  embedded id, but `state` keeps the old path — never updated — so a later edit
  would target the stale path. No rewrite should occur, only a path update.
- AC-2/AC-3 (`name` field changed): renderers always write to `existing_path`
  (`rendering._render_single_file:305`, `_render_directory_skill:320`), so the new
  slug only lands in frontmatter; the file/folder is never renamed and the old
  name is never archived. The change must propagate symmetrically to every tool.
- AC-5 (slug collision): a rename that would collide with another managed
  artifact's slug must be rejected with no destructive op and a structured error.

## Principle / decision

Identity (the `customization_artifact_id`) is independent of the filename; the
filename is a projection of `target_slug(name)`. Therefore:

1. A pure `mv` (content digest unchanged, observed path != recorded path) updates
   the recorded path and rewrites nothing (AC-1).
2. When the canonical `name` changes, each participating tool whose recorded
   file/folder basename no longer matches `target_slug(name)` is **renamed**:
   the prior file/folder is archived (NFR-01), the new-slug target is written,
   and the old path removed — symmetrically, no tool privileged (AC-2/AC-3).
3. Before any rename writes, the new slug is checked against every other managed
   artifact's owned paths; a collision rejects the whole rename with a structured
   error and no destructive operation (AC-5).

Scope: file/folder rename applies to single-file and directory-skill layouts.
Shared-keyed-map (`mcp_server`) has no per-artifact file — its name is the slot
key — so it is outside US-04's file/folder-rename scope.

## Proposed governance edits (require user validation)

**None.** US-04 already specifies this behavior; the change implements it.

## Design edits (architecture — applied after validation)

`docs/architecture.md` §6 / §5.4: note that projection renames to the slug target
(archive-old → write-new → drop-old) when the recorded basename drifts from the
slug, and that a pure `mv` rebinds the recorded path with no rewrite.

## Implementation plan

- AC-1: `adoption/engine.py::process_pair` rebinds a present tool's recorded path
  when the observed path differs but the content digest is unchanged.
- AC-2/3/5: the projection path renames per tool when `target_slug(name)` differs
  from the recorded basename — collision pre-check across managed pairs, then
  archive-old / write-new-slug / remove-old; reuse `assert_target_available`.

## Test plan

`tests/test_rename.py`: AC-1 mv updates state path with no rewrite; AC-2 name
change renames every tool's file/folder and archives the old; AC-3 symmetric
across originating tools; AC-5 colliding slug rejected with no destructive op.

## Verification

`bash scripts/ci.sh` green.
