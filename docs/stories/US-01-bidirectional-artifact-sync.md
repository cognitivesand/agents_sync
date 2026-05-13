# US-01: Bidirectional sync of customizations across all participating agentic_tools

## Persona

Both

## User Story

As a developer who uses several agentic_tools, I want my customizations — like agents and skills — to stay identical across every tool that supports them, so that I can edit on whichever tool is convenient and every other tool picks up the change automatically.

## Priority

Must Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`.

## Acceptance Criteria

### Cross-agentic_tool propagation (customization_type-agnostic)

- [ ] AC-1 [Normal — edit propagates to all participating agentic_tools]: Given a customization_artifact with N participating agentic_tools (N ≥ 2), When the customization_artifact's bytes are modified on any one participating agentic_tool, Then every other participating agentic_tool reflects the change within at most two polling intervals (4 seconds at the default 2-second poll interval).

- [ ] AC-2 [Normal — symmetry]: AC-1 holds from every participating agentic_tool towards every other. No agentic_tool is privileged.

- [ ] AC-3 [Normal — customization_artifact_id preservation]: Given a synced customization_artifact, When sync runs on any participating agentic_tool, Then the customization_artifact's `customization_artifact_id` is preserved verbatim in every agentic_tool's rendered output.

- [ ] AC-4 [Normal — lossless canonical, selective render]: Given a customization_artifact synced across N participating agentic_tools, When sync runs, Then:
  - (a) **Lossless capture.** The canonical accumulates every field produced by every IO module that parsed its agentic_tool's native format. No field is dropped, regardless of whether other agentic_tools' IO modules can interpret it.
  - (b) **Selective render.** Each target agentic_tool's render emits only those canonical fields whose semantics its IO module knows how to map to that agentic_tool's native format. Fields without a mapping for a given target are not emitted by that target.
  - (c) **Preservation for later.** Fields that no current target can render remain in the canonical for round-trip stability on the originating agentic_tool, and for any future agentic_tool whose IO module gains the ability to render them.
  - (d) **No leakage.** A field originating from agentic_tool A and supported only by A never appears in any other agentic_tool's rendered output, even if structurally compatible (e.g. unknown YAML keys are not blindly forwarded into another agentic_tool's YAML artifact metadata).

- [ ] AC-5 [Normal — artifact metadata style preservation]: Given an agentic_tool whose native format supports comments, key order, or quoting style (e.g. YAML, TOML), When the agentic_tool's IO module rewrites the customization_artifact (e.g. to inject `customization_artifact_id` or update a cross-agentic_tool field), Then existing key order, comments, and quoting style are preserved where the underlying format permits.

- [ ] AC-6 [Normal — availability-restricted participation]: Given an agentic_tool has the customization_artifact's `customization_type` in `supported_customization_types` but its current status is `unavailable` (per US-11), When the customization_artifact is processed at this poll, Then that agentic_tool is excluded from this poll's participating set, its state entry for the customization_artifact is preserved unchanged, and the remaining participating agentic_tools converge normally. When the agentic_tool returns to `available`, US-11 AC-3 re-extends the customization_artifact to it.

### Atomicity per customization_type

- [ ] AC-7 [Normal — single-file customization_types: atomic write]: Given a customization_artifact whose `customization_type` has a single-file file_layout (e.g. `agent`), When a sync writes the customization_artifact on a target agentic_tool, Then the write is atomic (staged tmp + rename); an external reader either sees the prior bytes or the new bytes, never a partial file.

- [ ] AC-8 [Normal — folder customization_types: atomic folder swap]: Given a customization_artifact whose `customization_type` has a folder file_layout (e.g. `skill`), When a sync writes the customization_artifact on a target agentic_tool, Then the swap is atomic (staged `.<name>.tmp` tree built first; the current folder is renamed to `.<name>.old`; the `.tmp` tree is renamed into place; the `.old` tree is archived); an external reader during the swap sees either the old folder or the new folder, never an empty or partial folder.

- [ ] AC-9 [Normal — folder customization_types: auxiliary file propagation]: Given a customization_artifact whose `customization_type` has a folder file_layout, When any file inside the folder is added, modified, moved, or deleted on any participating agentic_tool, Then every other participating agentic_tool's folder reflects the change within at most two polling intervals. Auxiliary files are propagated verbatim (only the agentic_tool-rendered file — e.g. `SKILL.md` for the `skill` customization_type — is parsed and re-rendered from the canonical).

- [ ] AC-10 [Normal — folder customization_types: executable bits preserved]: Given an auxiliary file inside a folder-customization_type customization_artifact has executable mode bits set on the source agentic_tool, When the file is propagated to a target agentic_tool, Then mode bits are preserved on every target agentic_tool whose underlying filesystem supports them.

### Failure modes

- [ ] AC-11 [Failure — render or write failure on one target agentic_tool]: Given the IO module's `render` raises an exception, or the atomic write/swap on a target agentic_tool fails (permission denied, disk full, lock contention, etc.), When a sync attempts the operation on that target agentic_tool, Then the operation is aborted for that target agentic_tool only: the source agentic_tool and all other target agentic_tools are unchanged; a structured error names the failing agentic_tool, the customization_artifact's `customization_artifact_id`, and the underlying cause; the next poll re-attempts.

- [ ] AC-12 [Failure — folder customization_types: agentic_tool-rendered file missing on source]: Given a folder-customization_type customization_artifact whose required agentic_tool-rendered file is missing on the source agentic_tool (e.g. a skill folder without a `SKILL.md`), When discovery runs, Then the folder is not treated as a customization_artifact of that customization_type, no adoption or sync is attempted, and a structured warning names the agentic_tool, the folder, and the missing file.

## Notes

This story unifies what was previously split into US-01 ("agent sync") and US-02 ("skill sync"). Both stories described the same cross-agentic_tool propagation algorithm, parameterised by the on-disk customization_type of the artifact. Merging them into a single story:

1. Reflects the actual implementation: discovery, adoption, sync, conflict, removal, and reconciliation all operate generically over `(customization_artifact_id, customization_artifact, agentic_tools)` triples; the only customization_artifact-specific code is the file-layout-aware atomic-write helper.
2. Scales to future customization_types without writing a new story per customization_type. When a new customization_type is introduced (e.g. `prompt-template`, `mcp-server-config`), this story applies to it automatically — provided the new customization_type declares one of the existing file_layouts (single-file or folder) or introduces a new file_layout via `docs/agentic_tool_integration_protocol.md`.
3. Removes the false implication that agents and skills are categorically different from a sync-algorithm perspective. They differ only in on-disk customization_type, and the customization_type is the IO module's concern, not the algorithm's.

The set of "participating agentic_tools" is computed per poll, per customization_artifact. It is the intersection of (a) agentic_tools whose `supported_customization_types` include the customization_artifact's `customization_type` and (b) agentic_tools whose status is `available`. At v0.4 release, more agentic_tools support the `skill` customization_type than the `agent` customization_type, because not every tool exposes a stable per-agent file format. The algorithm does not depend on these counts.

When a new customization_type is introduced in a future version, the corresponding agentic_tool modules update their `supported_customization_types` declarations and provide the matching `CustomizationTypeIO` triple. No change to this story or its acceptance criteria is required.

Related requirements: FR-01, NFR-02, NFR-03.
