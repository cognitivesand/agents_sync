# agents_sync — Project Requirements

This document captures the system-level requirements for `agents_sync`. Each requirement is a single, verifiable "shall" statement, kept implementation-free.

User-visible behaviour is specified in `docs/stories/US-XX-*.md`. This document captures the system-wide constraints, quality properties, and interface contracts that those behaviours must collectively satisfy. Story acceptance criteria are not repeated here.

Categories:

- **REQ-C-XX** — Constraints (invariants the system must preserve at all times)
- **REQ-Q-XX** — Quality (non-functional properties, observable across the whole system)
- **REQ-I-XX** — Interface (contracts visible to operators, scripts, and orchestrators)

---

## Constraints

- **REQ-C-01**: The tool **shall not** cause loss of user-authored content.
- **REQ-C-02**: A managed pair **shall** maintain a stable identity that survives renaming the file on either side and changing the user-visible name field.
- **REQ-C-03**: Correctness of the tool **shall not** depend on inter-process synchronization mechanisms.

## Quality

- **REQ-Q-01** (Latency): A change on either side **shall** be observable on the other side within twice the configured polling interval.
- **REQ-Q-02** (Atomic visibility): External readers **shall never** observe a partial or half-written file produced by the tool.
- **REQ-Q-03** (Self-healing): The tool **shall** converge to a consistent state within one polling interval after any interruption of a sync operation.
- **REQ-Q-04** (Idempotency): Repeated executions of the tool against unchanged inputs **shall** produce no observable changes.
- **REQ-Q-05** (Round-trip stability): Translating a managed item from one side to the other and back **shall** result in content identical to the starting state on the original side.
- **REQ-Q-06** (Observability): Every adoption, conflict resolution, archive action, and rename **shall** be recorded in a manner accessible to operator audit.
- **REQ-Q-07** (Attribute preservation): File attributes that affect functional behaviour (e.g., POSIX execute bit) **shall** be preserved when files are propagated between sides.
- **REQ-Q-08** (Formatting preservation): Existing formatting choices (key order, comments, quoting style) in frontmatter **shall** survive tool-induced rewrites of the same file.

## Interface

- **REQ-I-01**: The tool's CLI **shall** support a one-pass execution mode and a continuous execution mode.
- **REQ-I-02**: The tool **shall** read configuration from a single user-scoped file, with every setting also overridable from the command line.
- **REQ-I-03**: The tool **shall** return distinct process exit codes for success, sync failure, and configuration failure.
- **REQ-I-04**: The tool **shall** support running as a long-lived background process managed by the operating system's user-level service manager.
