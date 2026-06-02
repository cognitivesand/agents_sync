# agents_sync — Project Requirements

This document lists the system-level requirements for `agents_sync`. Each entry is one verifiable "shall" statement, free of implementation choices.

User-visible behaviour is specified in `docs/stories/US-XX-*.md`. This document is **complementary**: it captures system-wide properties no single story owns — for example, the daemon's CPU usage staying flat when nothing is changing. It does not repeat the stories' acceptance criteria.

Categories:

- **FR-XX** — Functional requirements (cross-cutting functional properties)
- **NFR-XX** — Non-functional requirements (system-wide qualities and constraints)

Project-wide constraints (Python 3.12+, per-OS supervision mechanism, single user / single workstation) live in `docs/project_description.md` and are not restated here.

---

## Functional Requirements

- **FR-01** (Loop suppression): The daemon **shall not** propagate a change that originated from its own prior write.
- **FR-02** (Fault isolation): If processing fails for one customization_artifact on one agentic_tool, the daemon **shall** continue processing the other agentic_tools and the other customization_artifacts.
- **FR-03** (Change-type coverage): The daemon **shall** observe additions, modifications, and removals on each participating agentic_tool.
- **FR-04** (Trusted removal source): The daemon **shall** treat a customization_artifact as removed only when an `available` agentic_tool no longer has it. A missing artifact on an `unavailable` or `disabled` agentic_tool **shall not** trigger removal.
- **FR-05** (agent matrix): The daemon **shall** sync user-level `agent` customization_artifacts across every available agentic_tool whose `supported_customization_types` includes `agent`.
- **FR-06** (skill matrix): The daemon **shall** sync user-level `skill` customization_artifacts across every available agentic_tool whose `supported_customization_types` includes `skill`.
- **FR-07** (rules matrix): The daemon **shall** sync user-level `rules` customization_artifacts across every available agentic_tool whose `supported_customization_types` includes `rules`.
- **FR-08** (slash_command matrix): The daemon **shall** sync user-level `slash_command` customization_artifacts across every available agentic_tool whose `supported_customization_types` includes `slash_command`.
- **FR-09** (mcp_server matrix): The daemon **shall** sync user-level `mcp_server` customization_artifacts across every available agentic_tool whose `supported_customization_types` includes `mcp_server`.
- **FR-10** (Standard global-rules filename detection): For the whole-file global-rules family (`claude`, `codex`, `opencode`), the daemon **shall** detect a tool's `rules` artifact by an ordered list of standard filenames and treat the highest-precedence present file as that tool's single `rules` artifact, preferring `AGENTS.md`. A filename not on a tool's declared list **shall not** be adopted as a `rules` artifact.
- **FR-11** (Identity robustness): The daemon **shall** extract a customization_artifact's `customization_artifact_id` independently of the validity of the remainder of its artifact metadata. When the artifact metadata is malformed but the `customization_artifact_id` tag is present and well-formed, the daemon **shall** recover the id, **shall not** mint a new id, and **shall not** misattribute the artifact. When the metadata is malformed such that content cannot be parsed, the daemon **shall** freeze the owning customization_artifact (no reconcile, no sync, no removal) and emit a structured warning per NFR-13.
- **FR-12** (Import convergence): The daemon **shall** import a customization library idempotently: candidate customization_artifacts that resolve to the same customization_type and name **shall** be reconciled into a single managed customization_artifact, the most recently modified candidate prevailing, ties resolved in favour of the locally-present artifact or, absent a local candidate, by a deterministic total order. Re-importing a library exported from an unchanged state **shall** produce no change.
- **FR-13** (Per-artifact atomic import): The daemon **shall** import each customization_artifact atomically and in isolation: a customization_artifact **shall** be either fully imported or not imported at all, and a failure to import one customization_artifact **shall not** affect customization_artifacts that have already imported successfully.
- **FR-14** (Canonical-change detection): The daemon **shall** detect when a customization_artifact's canonical content has changed independently of its tool-side files and **shall** re-project the canonical onto every supporting available tool, preserving any displaced bytes. Change detection **shall** be computed over canonical content only, not on the metadata.
- **FR-15** (Import-while-active safety): The daemon **shall** permit a customization-library import to run while the daemon is active. A concurrent import and daemon poll **shall not** corrupt the shared state record nor lose user-authored content, and the resulting managed state **shall** be identical to that produced by the same import and poll run sequentially.
- **FR-16** (Canonical adoption): When the customization library contains a canonical record for a customization_artifact the daemon is not yet managing, the daemon **shall** adopt that customization_artifact and project it onto every supporting available agentic_tool.

## Non-Functional Requirements

- **NFR-01** (Data preservation): The daemon **shall not** cause loss of user-authored content under any operation.
- **NFR-02** (Latency): A change on any participating agentic_tool **shall** be observable on every other participating agentic_tool within twice the configured polling interval.
- **NFR-03** (Atomic visibility): External readers **shall** see either the prior or the new customization_artifact, never an intermediate state. This holds for both single-file and folder customization_types.
- **NFR-04** (Self-healing): After a sync operation is interrupted, the daemon **shall** converge to a consistent state within one polling interval.
- **NFR-05** (No loop degradation): With user inputs unchanged, repeated polling cycles **shall** produce no file writes, no canonical updates, and no archive entries.
- **NFR-06** (Round-trip stability): Propagating a customization_artifact from one agentic_tool to another and back **shall** preserve the original bytes on the source.
- **NFR-07** (Bounded archive growth): Archive entries **shall** be created only when an operation would otherwise lose user-authored content.
- **NFR-08** (Resource stability): When the user makes no changes, the daemon's per-cycle CPU and memory usage **shall not** drift upward over time.
- **NFR-09** (Scalability): Daemon cycle time **shall** be at most linear in both the number of managed customization_artifacts and the number of participating agentic_tools.
- **NFR-10** (Distinct exit codes): The daemon **shall** return distinct process exit codes for normal termination, configuration failure, and runtime failure.
- **NFR-11** (Extensibility): Adding support for a new agentic_tool or a new customization_type **shall** require only a new agentic_tool integration module — or a new customization_type declaration in `agents_sync.agentic_tool_spec` plus its `file_layout` class, per `docs/agentic_tool_integration_protocol.md` — and a matching config entry. The sync engine, conflict resolution, adoption, reconciliation, and removal-propagation code **shall** be untouched.
- **NFR-12** (Log on change, not per poll): The daemon **shall** log an agentic_tool's status only on transitions (startup counts as a transition), not on every poll.
- **NFR-13** (Structured error reporting): Every failure the daemon reports **shall** be a structured log entry naming the customization_artifact_id (when applicable), the agentic_tool (when applicable), and the underlying cause.
- **NFR-14** (Clean code maintainability): Production code **shall** follow Robert C. Martin's Clean Code principles: intention-revealing names, small cohesive functions, minimal duplication, explicit boundaries, and simple designs that remain easy to test and change.
- **NFR-15** (Secret handling): The daemon **shall** apply the configured `secret_policy` at every artifact-egress boundary (parse, render, customization-library export, and customization-library import). Accepted values are `secrets_refused` (default) and `secrets_accepted`. Under `secrets_refused`, when a customization_artifact carries a literal value matching the secret-detection heuristics on any of its `env`, `headers`, or `auth.*` fields, the daemon **shall** fail closed for that artifact: it **shall not** propagate the literal to any other agentic_tool and **shall** emit a structured error (NFR-13) naming the artifact, the offending field path, and the policy. Under `secrets_accepted`, the literal **shall** propagate verbatim and the daemon **shall** log one structured warning per affected artifact. Secret detection at egress is heuristic: a literal is refused when it sits under an `env`, `headers`, or `auth.*` field, under a field whose name matches the secret-field set, or when its value matches a high-confidence credential shape. A literal of an arbitrary shape placed in a non-secret field outside those locations is the documented residual; such credentials **shall** be supplied via `env` or `headers`, where any literal is detected regardless of shape. This requirement realises description goal 6.
- **NFR-16** (Canonical authority and fidelity): The canonical record **shall** be the authoritative representation of a customization_artifact, and every tool-side file **shall** be a projection derived from it. Reading a tool-side file into canonical form **shall not** lose user-authored information, such that projecting the canonical reproduces every field and value the source declared.
- **NFR-17** (Unattended operation): After initial configuration, the daemon **shall** adapt to the user adding, editing, removing, renaming, or uninstalling customization_artifacts and agentic_tools without requiring any further interaction with `agents_sync`.
