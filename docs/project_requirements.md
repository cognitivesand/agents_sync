# agents_sync — Project Requirements

This document captures the system-level requirements for `agents_sync`. Each requirement is a single, verifiable "shall" statement, kept implementation-free.

User-visible behaviour is specified in `docs/stories/US-XX-*.md`. This document is **complementary**: it captures cross-cutting concerns and emergent properties that no single story owns — for example, the absence of loop degradation under sustained operation. Story acceptance criteria are not repeated here.

Categories:

- **FR-XX** — Functional requirements (cross-cutting functional properties)
- **NFR-XX** — Non-functional requirements (system-wide qualities and constraints)

---

## Functional Requirements

- **FR-01** (Loop suppression): The daemon **shall not** propagate a change that originated from its own prior write.
- **FR-02** (Per-pair fault isolation): A failure to process any single managed pair **shall not** interrupt processing of other pairs.
- **FR-03** (Change-type coverage): The daemon **shall** observe additions, modifications, and removals on each monitored side.

## Non-Functional Requirements

- **NFR-01** (Data preservation): The daemon **shall not** cause loss of user-authored content under any operation.
- **NFR-02** (Latency): A change on either side **shall** be observable on the other side within twice the configured polling interval.
- **NFR-03** (Atomic visibility): External readers **shall never** observe a partial or half-written file produced by the daemon.
- **NFR-04** (Self-healing): The daemon **shall** converge to a consistent state within one polling interval after any interruption of a sync operation.
- **NFR-05** (No loop degradation): With user inputs unchanged, repeated polling cycles **shall** produce no file writes, no canonical updates, and no archive entries.
- **NFR-06** (Round-trip stability): Translating a managed item from one side to the other and back **shall** result in content identical to the starting state on the original side.
- **NFR-07** (Bounded archive growth): Archive entries **shall** be created only when an operation would otherwise lose user-authored content.
- **NFR-08** (Resource stability): Per-cycle CPU and memory usage of the daemon **shall not** grow with elapsed runtime in the absence of user-induced changes.
- **NFR-09** (Scalability): Daemon cycle time **shall** grow at most linearly with the number of managed pairs.
- **NFR-10** (Distinct exit codes): The daemon **shall** return distinct process exit codes for normal termination, configuration failure, and runtime failure.
