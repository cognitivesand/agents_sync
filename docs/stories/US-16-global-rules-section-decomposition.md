# US-16: Shared vs tool-specific global-rules section decomposition

## Persona

Alice

## User Story

As a power user whose global instructions mix **cross-tool** guidance ("always write tests") with **tool-specific** guidance ("Claude: use the Task tool for X"), I want `agents_sync` to sync only the shared portion across my agentic_tools and keep the tool-specific portion local — so that a paragraph meant only for Claude never propagates verbatim into Codex's or OpenCode's rules file.

## Priority

Should Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`. "Global-rules family" denotes `claude`, `codex`, and `opencode` (see [[US-14-standard-global-rules-filename]]). A **shared section** is rules content intended for every tool; a **tool-specific section** is content intended for exactly one tool. The current model treats the rules file as one indivisible unit (a "whole-file" artifact); this story replaces that with a **decomposed** model in which the canonical carries shared and per-tool components separately.

## Scope note

This story **supersedes the whole-file `rules` model** of US-14 for files that carry mixed content; it does not change filename detection (US-14) and is independent of import resolution ([[US-15-global-rules-import-resolution]]). It applies to the global-rules family only (`claude` / `codex` / `opencode`); per-rule layouts (`cursor` `.mdc`) and other surfaces (`gemini_cli`, `copilot`) are out of scope. A file with no tool-specific markers is treated exactly as US-14 (whole-file = all-shared), so the change is backward compatible.

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given a tool's `rules` file delimits a tool-specific section (by the agreed marker — see open questions), When the daemon adopts the artifact, Then the canonical records that section as belonging to that tool only, and the remaining content as the shared section.

- [ ] AC-2 [Normal]: Given a decomposed `rules` canonical, When the daemon projects it to another participating global-rules tool, Then only the shared section is rendered onto that tool; the originating tool's tool-specific section never appears on it.

- [ ] AC-3 [Normal]: Given two tools each contribute their own tool-specific section plus shared content, When the daemon syncs, Then each tool's rendered file contains the shared section plus **only its own** tool-specific section; no tool-specific section crosses tools.

- [ ] AC-4 [Round-trip]: Given a `rules` file with shared and tool-specific sections, When the daemon re-renders it back to the same tool, Then both sections are preserved in their original positions, so `parse(render(c)) == c` over the agentic_tool-relevant subset (NFR-06).

- [ ] AC-5 [Normal]: Given a `rules` file with **no** tool-specific markers, When the daemon adopts and syncs it, Then it behaves exactly as US-14 (entire file is shared; whole-file propagation), preserving backward compatibility.

- [ ] AC-6 [Edit-propagation]: Given an edit confined to one tool's tool-specific section, When the next sync runs, Then no other tool's `rules` file changes (the edit is not a cross-tool change).

## Open questions (resolve before committing — Example-Mapping red cards)

- **Marker mechanism (load-bearing).** How is a tool-specific section delimited? Candidates: an HTML-comment fence (`<!-- agents_sync:tool=claude -->` … `<!-- /agents_sync -->`), a heading convention, or out-of-file config keyed by heading. Must round-trip (AC-4) and be invisible to the tools at load time.
- **Authoring ergonomics.** Is decomposition opt-in (only files containing markers are decomposed) or inferred? AC-5 assumes opt-in.
- **Interaction with [[US-15-global-rules-import-resolution]].** If a tool-specific section is itself an `@import`, which feature owns resolution? Define precedence or declare mutually exclusive for v1.
- **Ordering/merge.** When rendering shared + tool-specific onto a target, what is the deterministic ordering, and how is it preserved on the authoring tool (AC-4)?
- This story is likely **not estimable until a spike** settles the marker mechanism; consider a 2-day exploration enabler first whose deliverable is the chosen marker design + a round-trip proof-of-concept.

## Notes

- Depends on [[US-14-standard-global-rules-filename]]; sibling of [[US-15-global-rules-import-resolution]] (independent, either order). This is the first of US-14's two deferred "phase 2" concerns and the more design-heavy of the pair.
- Risk this story retires: today a Claude-only instruction authored in `~/.claude/AGENTS.md` propagates verbatim into Codex and OpenCode, which is incorrect behaviour the whole-file model cannot prevent.

Related requirements: FR-07 (rules matrix), FR-10 (standard global-rules filename detection — prerequisite), NFR-06 (round-trip stability — AC-4). A new FR defining the decomposition contract (amending/superseding the whole-file scope of FR-10) needs to be cascaded via the `write-requirements` flow before this story is marked Ready.
