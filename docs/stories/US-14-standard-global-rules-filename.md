# US-14: Standard global-rules filename detection

## Persona

Alice

## User Story

As a power user who keeps my global instructions in the cross-tool-standard `AGENTS.md` file, I want `agents_sync` to detect and sync whichever standard global-rules filename each agentic_tool actually uses — preferring `AGENTS.md` — so that my real guidelines are synced even when a tool (such as Claude Code) historically used a different name (`CLAUDE.md`).

## Priority

Should Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`. "Global-rules family" denotes the agentic_tools whose `rules` customization_type is a single, whole-file global instructions document: `claude`, `codex`, and `opencode`. Tools whose `rules` model is per-rule files (`cursor` `.mdc`) or a different surface (`gemini_cli`, `copilot`) are out of scope for this story.

## Scope note

This story covers **filename detection only**. It does NOT decompose the rules file into shared vs tool-specific components (tracked separately), and it does NOT resolve Claude `@import` directives (deferred). When a user keeps content in `AGENTS.md` and a thin `CLAUDE.md` that `@AGENTS.md`-imports it, this story makes the sync watch `AGENTS.md` (the content) directly and leave `CLAUDE.md` untouched.

## Acceptance Criteria

> **Status: Done (v0.5).** All six criteria are implemented and verified by `tests/test_rules_filename_detection.py` and shipped via PR #39. Phase 2 (`@import` resolution; shared-vs-tool-specific section decomposition) is tracked separately in the follow-up story — this story remains whole-file detection only.

- [x] AC-1 [Normal]: Given an agentic_tool in the global-rules family declares an ordered list of standard rules filenames, When the daemon enumerates that tool's `rules` artifacts under its rules root, Then it adopts the **highest-precedence filename that is present** as the tool's single `rules` artifact. Claude's precedence is (`AGENTS.md`, `CLAUDE.md`); codex's and opencode's is (`AGENTS.md`).

- [x] AC-2 [Normal]: Given Claude's rules root (`~/.claude`) contains BOTH `AGENTS.md` and `CLAUDE.md`, When the daemon enumerates `rules`, Then it selects `AGENTS.md` (higher precedence) and does not treat `CLAUDE.md` as a separate `rules` artifact; `CLAUDE.md` is left untouched on disk.

- [x] AC-3 [Normal]: Given Claude's rules root contains only `CLAUDE.md` (no `AGENTS.md`), When the daemon enumerates `rules`, Then it adopts `CLAUDE.md` (backward compatible with pre-v0.5.x installs).

- [x] AC-4 [Normal]: Given a `rules` artifact was detected on a tool under filename N, When the daemon re-renders that tool's `rules` after a sync, Then it writes back to the same on-disk path (filename N), so `parse(render(c)) == c` over the agentic_tool-relevant subset (NFR-06). The non-selected sibling filename is never written.

- [x] AC-5 [Normal]: Given a `rules` artifact is propagated to a participating global-rules tool that currently has **no** rules file under any of its standard names, When the daemon renders it, Then the file is created under that tool's **create-name** (the lowest-precedence / legacy standard name: `CLAUDE.md` for claude, `AGENTS.md` for codex and opencode). Creating the file under a name the tool natively loads is preferred over the cross-tool standard for the from-scratch case.

- [x] AC-6 [Normal]: Given a tool's rules root contains a file whose name is not one of that tool's declared standard names (e.g. `INSTRUCTIONS.md`), When the daemon enumerates `rules`, Then that file is ignored: no `rules` artifact is adopted for it, and no error is logged. Only declared standard names are recognized — there is no wildcard.

## Notes

- The render/create path already distinguishes existing from new artifacts (`rendering.single_file_target` is used only when there is no `existing_path`), so AC-4 (round-trip to the detected name) requires no special handling beyond carrying the discovered path, and AC-5 (create-name) reuses the existing single-file target rule.

- **Restart-time migration:** an install previously tracking Claude's `rules` at `CLAUDE.md` will, after this change, detect `AGENTS.md` if present. The `rules`/`global` reconciliation key is stable across the filename, so the artifact re-binds to `AGENTS.md`; the now-unselected `CLAUDE.md` is simply no longer the rules artifact (it is not deleted, and its disappearance from tracking is not a removal-propagation event because detection — not the file's existence — defines the artifact).

- This is phase 1 of the rules-modelling work. Phase 2 (shared vs tool-specific component decomposition, so a tool-specific section never propagates) is tracked separately and supersedes the whole-file model for tools that carry mixed content.

Related requirements: FR-07 (rules matrix), FR-10 (standard global-rules filename detection — load-bearing for AC-1/AC-2/AC-3), NFR-06 (round-trip stability — AC-4).
