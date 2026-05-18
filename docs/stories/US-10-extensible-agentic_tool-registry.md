# US-10: Extensible agentic_tool registry

## Persona

Alice

## User Story

As a power user adopting new agentic_tools as they emerge, I want adding support for a new tool to be a small, isolated change to `agents_sync` — one new file describing how that tool stores its customizations on disk, plus a short config entry, with no edits to the sync engine — so that my library of customizations can extend to a new tool soon after the tool ships.

## Priority

Should Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`.

## The integration contract

Each registered agentic_tool is implemented as **one Python module** at `src/agents_sync/agentic_tools/<agentic_tool_name>.py` that exports a top-level `AGENTIC_TOOL: AgenticToolSpec` constant. The `AgenticToolSpec` answers three questions about the agentic_tool:

1. **What is synced.** The agentic_tool declares `supported_customization_types` — a subset of `{agent, skill}` (open for additional customization_types in future versions). For each supported customization_type, the agentic_tool participates in customization_artifacts of that customization_type; for unsupported customization_types, the agentic_tool is invisible to the sync algorithm.
2. **Where the files are.** The agentic_tool declares, per supported customization_type, the config-file key naming the on-disk root directory, plus a `file_layout` descriptor for that customization_type (single-file, e.g. an `.md` or `.toml`, for `agent`; folder containing a designated rendered file, e.g. `SKILL.md`, for `skill`).
3. **How to translate to and from the canonical form.** The agentic_tool declares, per supported customization_type, a `CustomizationTypeIO` triple: `extract_customization_artifact_id(text)`, `parse(text, prior_canonical)`, and `render(canonical, prior_text)`. These functions are pure and round-trip-stable: `parse(render(c)) == c` over the agentic_tool-relevant subset of the canonical.

The full contract — module discovery, exact function signatures, registration mechanism, and the end-to-end checklist for adding a new agentic_tool — is specified in `docs/agentic_tool_integration_protocol.md`. Acceptance criteria below state the user-story-level guarantees; the protocol document specifies the implementation-level contract.

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given the agentic_tool registry, When the daemon lists agentic_tools, Then each agentic_tool is fully specified by a single Python module at `src/agents_sync/agentic_tools/<agentic_tool_name>.py` that exports a top-level `AGENTIC_TOOL: AgenticToolSpec` constant satisfying `docs/agentic_tool_integration_protocol.md`. The `AgenticToolSpec` declares the agentic_tool's unique `name`, its `supported_customization_types`, a `CustomizationTypeIO` triple per supported customization_type, the config keys that name the on-disk roots per customization_type, and the file-layout descriptor per customization_type.
- [ ] AC-2 [Normal]: Given a new agentic_tool module is added under `src/agents_sync/agentic_tools/` and a matching `[agentic_tools.<name>]` config block is provided, When the existing sync algorithm runs, Then no changes are required to discovery, adoption, reconciliation, conflict resolution, or removal propagation logic to support the new agentic_tool.
- [ ] AC-3 [Normal]: Given two agentic_tools declare different `supported_customization_types`, When the daemon processes a customization_artifact of a given customization_type, Then participation is restricted to agentic_tools that include that customization_type in their `supported_customization_types`. Example: if `claude` and `codex` support `{agent, skill, rules, slash_command, mcp_server}`, `antigravity` supports `{skill}` only, `gemini_cli` supports `{agent, rules, slash_command, mcp_server}`, and `cursor` supports `{rules, slash_command, mcp_server}`, then `agent` customization_artifacts flow over `{claude, codex, gemini_cli}`; `skill` over `{claude, codex, antigravity}`; `rules` over `{claude, codex, gemini_cli, cursor}`; and so on for each customization_type.
- [ ] AC-4 [Normal]: Given an agentic_tool named `<name>`, When the daemon archives bytes, writes the canonical, or emits a state entry, Then `<name>` appears verbatim in archive paths (`archive/<customization_artifact_id>/<name>/...`), in canonical per-agentic_tool bags (`per_agentic_tool_only[<name>]`, `per_agentic_tool_extra[<name>]`), and in state entries (`state.customization_artifacts[<customization_artifact_id>].agentic_tools[<name>]`).
- [ ] AC-5 [Failure]: Given two agentic_tool modules under `src/agents_sync/agentic_tools/` export `AGENTIC_TOOL` constants whose `name` values are equal (after Unicode normalisation and case-folding), When the daemon initialises the agentic_tool registry at startup, Then it fails closed with a structured error that names both modules and the conflicting `name`.
- [ ] AC-6 [Failure]: Given an agentic_tool module's `AGENTIC_TOOL.io_per_customization_type` mapping declares a customization_type that is also in `AGENTIC_TOOL.supported_customization_types`, but the corresponding `CustomizationTypeIO` is missing any of `extract_customization_artifact_id`, `parse`, or `render`, When the daemon initialises the agentic_tool registry at startup, Then it fails closed with a structured error that names the agentic_tool, the customization_type, and the missing function.
- [ ] AC-7 [Normal]: Given an agentic_tool is registered but the config sets `enabled = false` for it, When the daemon runs, Then the agentic_tool is treated as if it were not registered: it is excluded from discovery, sync, conflict resolution, and removal propagation. No log line is emitted about its absence at any time. (Disabling an agentic_tool is a deliberate, silent choice; see US-11 for the distinct case of an enabled agentic_tool whose root is missing.)
- [ ] AC-8 [Failure]: Given a Python module under `src/agents_sync/agentic_tools/` does not export a top-level `AGENTIC_TOOL` constant of type `AgenticToolSpec`, When the daemon initialises the agentic_tool registry at startup, Then it fails closed with a structured error that names the module file and the missing or wrongly-typed `AGENTIC_TOOL`.

## Notes

The v0.4 release ships built-in agentic_tools under `src/agents_sync/agentic_tools/`. Subsequent agentic_tools are added in later releases by dropping a new `<tool_name>.py` into `src/agents_sync/agentic_tools/`, following the end-to-end checklist in `docs/agentic_tool_integration_protocol.md`. The user-facing README and the project description enumerate the concrete agentic_tools shipped in each release; this story does not, in order to remain tool-agnostic across versions.

Extensibility is the design property under test. AC-2 is the load-bearing acceptance criterion — if adding a new agentic_tool requires editing the sync algorithm, the design has failed. Each parallel set of `_add_claude_*` / `_add_codex_*` methods that survives the v0.4 refactor is a defect against this story.

This story addresses only the **structural** ability to register an agentic_tool. It does not address the runtime behaviour when a registered agentic_tool's root is missing or unreadable; that is US-11's responsibility.

Related requirements: NFR-11 (extensibility — load-bearing for AC-2), NFR-13 (structured error reporting — AC-5, AC-6, AC-8).
