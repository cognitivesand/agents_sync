# US-15: Global-rules `@import` resolution + framework-specific egress guard

## Persona

Alice

## User Story

As a power user whose `CLAUDE.md` keeps its real instructions in other files referenced by `@import` directives (Claude Code's `@path` include syntax) — and which sometimes mention tool-private paths like `~/.claude/skills` — I want `agents_sync` to resolve those imports into the **effective** content when it syncs my `rules`, and to **hold back any file that is framework-specific**, so that other agentic_tools receive the instructions Claude actually loads but never inherit a meaningless `@import` line or a Claude-only path reference.

## Priority

Could Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`. "Global-rules family" denotes the agentic_tools whose `rules` customization_type is a single, whole-file global instructions document: `claude`, `codex`, and `opencode` (see [[US-14-standard-global-rules-filename]]). An **import directive** is a line of the form `@<relative-path>` that a tool resolves at load time by inlining the referenced file's content. The **effective content** of a rules file is its own text with every import directive transitively resolved. A rules file is **framework-specific** when its effective content references any agentic_tool's own private directory (`.claude/`, `.codex/`, `.cursor/`, `.gemini/`, `.opencode/`, or a copilot config dir).

## Scope note

This story covers (1) **import resolution within the detected global-rules file**, and (2) a **coarse, whole-file framework-specificity guard**. It builds on US-14 (filename detection — prerequisite). It deliberately does **not** do fine-grained shared-vs-tool-specific section decomposition (tracked in [[US-16-global-rules-section-decomposition]]); the guard here is the conservative interim: if *any* framework-specific token is present, the *whole* file is held back rather than split. Imports resolve only within the tool's configured `rules` root; an import escaping that root (e.g. `@../../secrets`) is refused, consistent with the existing path-containment invariant.

## Acceptance Criteria

> **Status: Implemented.** AC-1…AC-7 are verified by `tests/test_rules_import_resolution.py` (unit + integration over the two-tool harness). Implementation: `rules_io.resolve_rules_imports` / `detect_framework_specific`, threaded via `tool_specs/_rules_factory.py`, with the egress guard in `adoption/privacy_gate.py` (`_skip_framework_specific`, `_target_is_protected`).

- [x] AC-1 [Normal]: Given the detected global-rules file contains an import directive `@<relative-path>` pointing to a readable file inside the tool's `rules` root, When the daemon adopts that tool's `rules` artifact, Then the canonical's effective content includes the imported file's content (transitively, depth-first, in directive order).

- [x] AC-2 [Round-trip]: Given a `rules` artifact whose source file used import directives, When the daemon re-renders that artifact back to the **source** tool, Then the source file's import directives are preserved verbatim (the user's `@import` structure is not flattened on the tool that authored it), so `parse(render(c)) == c` over the agentic_tool-relevant subset (NFR-06).

- [x] AC-3 [Normal]: Given the effective content is propagated to another participating global-rules tool, When the daemon renders it, Then the imported content is written **inline** (resolved) so the target tool loads the same effective instructions, with no `@import` line.

- [x] AC-4 [Error]: Given an import directive points to a missing/unreadable file, a file outside the `rules` root, or forms an import cycle, When the daemon resolves imports (in discovery planning **and** in adoption), Then resolution fails closed for that artifact (skipped, not partially synced), a WARNING is logged, and no crash occurs and no other pair is affected.

- [x] AC-5 [Normal]: Given a detected global-rules file that contains **no** import directives and no framework-specific token, When the daemon adopts it, Then behaviour is identical to US-14 (the body is returned verbatim; backward compatible).

- [x] AC-6 [Normal]: Given a detected global-rules file whose effective content references a tool-private directory (e.g. `~/.claude/skills`), When the daemon processes it, Then the **whole file is held back** — it is not propagated to any other tool — and a WARNING is logged naming the matched token (`event=rules_framework_specific_held_back`).

- [x] AC-7 [Normal]: Given a participating tool already holds a framework-specific `rules` file, When the daemon would project another tool's `rules` onto it, Then the existing file is **not overwritten** (it is protected exactly as a `private` artifact is).

## Resolved design decisions

- **Canonical representation:** the canonical stores the *resolved effective* body in `body` (propagated to all other tools) plus the *original directive-bearing* body in `rules_source_body` keyed to `rules_import_origin` (the authoring tool). Render emits the raw body only when rendering back to the origin tool; everyone else gets the effective body. This satisfies AC-2 + AC-3 without a separate view.
- **Detection scope:** framework-specificity is tool-private directory path tokens only (low false-positive); not IDE/repo dirs, not tool-name/command references. Tokens live in `rules_io.FRAMEWORK_SPECIFIC_PATH_TOKENS`, derived from the per-tool roots in `config.py`.
- **Guard mechanism:** reuses the privacy-gate fail-closed pattern — a framework-specific source is skipped (not adopted/propagated, like `private`) and a framework-specific target is protected from overwrite. Both directions covered.

## Notes

- Depends on [[US-14-standard-global-rules-filename]]; sibling of [[US-16-global-rules-section-decomposition]]. US-15's whole-file guard is the coarse interim; US-16's section decomposition is the fine-grained successor (a file mixing shared + Claude-only content is held back entirely by US-15, but *split* by US-16).
- Known limitation (deferred): the framework guard is whole-file. A file that is mostly shared but mentions one tool-private path is held back in its entirety rather than partially propagated — by design until US-16.

Related requirements: FR-07 (rules matrix), FR-10 (standard global-rules filename detection — prerequisite), NFR-06 (round-trip stability — AC-2). A new FR formalising import resolution + the framework-specific egress guard should be cascaded via the `write-requirements` flow to give AC-1…AC-7 a parent requirement.
