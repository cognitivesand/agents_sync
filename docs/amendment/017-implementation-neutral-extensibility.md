# Amendment 017 — Implementation-neutral extensibility (NFR-11, US-10)

- status: applied
- branch: fix/size-explosion-hardening
- date: 2026-06-05
- relates to: NFR-11, US-10, US-07 AC-7, NFR-13, FR-11; the architecture
  simplification proposal (`docs/architecture_simplification_proposal.md`).

## Motivation

NFR-11 and US-10 named concrete code symbols — `agents_sync.agentic_tool_spec`,
`AgenticToolSpec`, `CustomizationTypeIO`, `build_<tool>_spec`,
`default_agentic_tools()`, `tool_specs/<tool>.py`, `file_layout`,
`config_dir_keys`, `io`. Requirements and stories must be free of implementation
choices (project_requirements preamble; INCOSE). Naming binding symbols in
governance both couples the spec to one design and blocked the cleaner
centralized-translation architecture under proposal. The concrete contract
belongs in the design doc `docs/agentic_tool_integration_protocol.md`, not in the
requirement/story.

Review also surfaced two defects in US-10's acceptance criteria:
- AC-5 justified a non-behaviour ("no duplicate-name detection is required")
  from an implementation detail (a name-keyed map), as a "does-not-do" AC, and
  contradicted US-07 AC-7, which already owns duplicate-name detection (fail
  closed). A name-keyed map does not make names unique safely — it silently
  shadows — so the AC papered over a latent fault.
- AC-6 restated US-07 AC-7's "declared type missing its IO" fail-closed case in
  registry-construction vocabulary, duplicating a behaviour owned elsewhere.

## Principle / decision

Requirements and stories describe capabilities and guarantees, not code symbols.
The integration contract is named once, in the design doc. Duplicate-name
detection is owned solely by US-07 AC-7. US-10 keeps the extensibility structure
as a well-formed/ill-formed pair (happy/failure) that references US-07 AC-7 and
NFR-13 for mechanics rather than restating them. Translation is described as
capabilities (read into canonical, write back, recover id in isolation per
FR-11), not as a fixed count of per-tool functions.

## Governance edits (validated by the user)

### Requirements — NFR-11
Reworded to drop the code symbols; capability + pointer to the protocol doc.

### User stories — US-10
- All code symbols removed; the term `agentic_tools_registry` introduced.
- Integration-contract question 3 describes translation as capabilities
  (both-direction translation + id-recovery-in-isolation, FR-11 referenced once);
  round-trip stability is left to its owners (NFR-06/NFR-16), not restated.
- AC-5 retired (number not reused; no tombstone displayed) — duplicate-name
  detection is US-07 AC-7's.
- AC-6 = happy path (well-formed declaration → registered + participates).
- AC-7 = failure path (incoherent declaration → fail closed; references NFR-13
  and US-07 AC-7 for mechanics).
- AC-8 de-crufted (autodiscovery archaeology removed): registration is explicit;
  an unregistered module is simply absent.
- AC-9 (new) = the disabled-tool guarantee (moved from the old AC-7).

## Design edits (applied after)

`docs/architecture_simplification_proposal.md`: adopt `agentic_tools_registry`
terminology; clarify that the state store is the *single intended writer* and
that two overlapping daemons are a tolerated *failure mode* (atomic writes +
recompute-from-disk, US-09 AC-3) — not a contradiction.

## Verification

No code change. The neutralized NFR-11/US-10 remain testable: AC-2 (engine
untouched), AC-3 (participation by supported types), AC-6/AC-7 (registry build
outcomes), AC-9 (disabled tool). Concrete-symbol checks live against the protocol
doc, not the story.
