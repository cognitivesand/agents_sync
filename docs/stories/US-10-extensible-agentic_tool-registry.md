# US-10: Extensible agentic_tool registry

## Persona

Alice

## User Story

As a power user adopting new agentic_tools as they emerge, I want adding support
for a new tool to be a small, isolated change to `agents_sync` — one new module
describing how that tool stores its customizations on disk, plus a short config
entry, with no edits to the sync engine — so that my library of customizations
can extend to a new tool soon after the tool ships.

## Priority

Should Have

## Terminology

Vocabulary used in this story is defined in the project glossary at
`docs/project_description.md`. The **agentic_tools_registry** is the set of
agentic_tools the daemon will sync, assembled in memory at startup — one entry
per tool, keyed by the tool's `name`.

## The integration contract

Each registered agentic_tool is implemented as **one integration module** that
declares how that tool stores its customizations and how to translate them to and
from the canonical form, and is added to the agentic_tools_registry. The
declaration answers three questions:

1. **What is synced.** The agentic_tool declares its supported
   customization_types — a subset of the registered customization_types. For each
   supported type it participates in customization_artifacts of that type; for
   unsupported types it is invisible to the sync algorithm.
2. **Where the files are.** Per supported customization_type, it declares the
   configuration key naming the on-disk root directory, plus a file-layout
   descriptor for that type (single-file, e.g. an `.md` or `.toml`, for `agent`;
   a folder containing a designated rendered file, e.g. `SKILL.md`, for `skill`).
3. **How to translate to and from the canonical form.** Per supported
   customization_type, the declaration translates the tool's on-disk form to the
   canonical form and back, and recovers the `customization_artifact_id` from the
   on-disk text in isolation (FR-11).

The full contract — module layout, exact function signatures, and the
registration mechanism — is specified in
`docs/agentic_tool_integration_protocol.md`. The acceptance criteria below state
the user-story-level guarantees; the protocol document specifies the
implementation-level contract.

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given the agentic_tools_registry, When the daemon lists
  agentic_tools, Then each is fully specified by a single integration module
  (per `docs/agentic_tool_integration_protocol.md`) that declares the tool's
  unique `name`, its supported customization_types, how to translate each
  supported type to and from the canonical form and recover its id in isolation,
  the configuration keys naming the on-disk roots per type, and the file-layout
  descriptor per type.

- [ ] AC-2 [Normal]: Given a new agentic_tool integration module is added to the
  agentic_tools_registry and a matching `[agentic_tools.<name>]` config block is
  provided, When the existing sync algorithm runs, Then no changes are required
  to discovery, adoption, reconciliation, conflict resolution, or
  removal-propagation logic to support the new agentic_tool.

- [ ] AC-3 [Normal]: Given two agentic_tools declare different supported
  customization_types, When the daemon processes a customization_artifact of a
  given customization_type, Then participation is restricted to agentic_tools
  that include that customization_type in their supported customization_types.
  Example: if `claude` and `codex` support `{agent, skill, rules, slash_command,
  mcp_server}`, `antigravity` supports `{skill}` only, `gemini_cli` supports
  `{agent, rules, slash_command, mcp_server}`, and `cursor` supports `{rules,
  slash_command, mcp_server}`, then `agent` customization_artifacts flow over
  `{claude, codex, gemini_cli}`; `skill` over `{claude, codex, antigravity}`;
  `rules` over `{claude, codex, gemini_cli, cursor}`; and so on for each
  customization_type.

- [ ] AC-4 [Normal]: Given an agentic_tool named `<name>`, When the daemon
  archives bytes, writes the canonical, or emits a state entry, Then `<name>`
  appears verbatim in archive paths
  (`archive/<customization_artifact_id>/<name>/...`), in canonical
  per-agentic_tool bags (`per_agentic_tool_only[<name>]`,
  `per_agentic_tool_extra[<name>]`), and in state entries
  (`state.customization_artifacts[<customization_artifact_id>].agentic_tools[<name>]`).

- [ ] AC-6 [Normal — well-formed integration]: Given a tool's integration
  declaration provides, for every supported customization_type, a root, a
  file-layout descriptor, and a complete canonical translation (read, write, and
  id-recovery), When the agentic_tools_registry is built at startup, Then the
  tool is registered and participates in those customization_types.

- [ ] AC-7 [Failure — incoherent integration]: Given a tool's integration
  declaration is incomplete — a supported customization_type whose canonical
  translation is incomplete, a declared root with no matching supported type, or
  a translation lacking a file-layout descriptor — When the agentic_tools_registry
  is built, Then construction fails closed with a structured error naming the
  tool and the offending customization_types (per NFR-13), and the daemon exits
  with the configuration-failure code (per US-07 AC-7).

- [ ] AC-8 [Normal — explicit registration]: Given an integration module exists
  but is not added to the agentic_tools_registry, When the daemon builds the
  registry, Then the tool is simply absent — modules are not auto-discovered;
  registration is explicit.

- [ ] AC-9 [Normal — disabled tool]: Given a registered agentic_tool whose config
  sets `enabled = false`, When the daemon runs, Then the agentic_tool is excluded
  from discovery, sync, conflict resolution, and removal propagation, and no log
  line is emitted about its absence at any time. (Disabling an agentic_tool is a
  deliberate, silent choice; see US-11 for the distinct case of an enabled
  agentic_tool whose root is missing.)

## Notes

Built-in agentic_tools ship with the release; subsequent agentic_tools are added
in later releases by adding a new integration module and registering it in the
agentic_tools_registry, following the end-to-end checklist in
`docs/agentic_tool_integration_protocol.md`. The README and the project
description enumerate the concrete agentic_tools shipped in each release; this
story does not, in order to remain tool-agnostic across versions.

Extensibility is the design property under test. AC-2 is the load-bearing
acceptance criterion — if adding a new agentic_tool requires editing the sync
algorithm, the design has failed.

This story addresses only the **structural** ability to register an
agentic_tool. It does not address the runtime behaviour when a registered
agentic_tool's root is missing or unreadable; that is US-11's responsibility.

Related requirements: NFR-11 (extensibility — load-bearing for AC-2), NFR-13
(structured error reporting — AC-7). Realises description goal 5 (agentic_tool
extensibility — AC-2).
