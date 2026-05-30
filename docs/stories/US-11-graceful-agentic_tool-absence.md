# US-11: Transparent handling of unavailable agentic_tools

## Persona

Both

## User Story

As a user whose set of installed agentic_tools changes over time — some not yet installed, some uninstalled later, some temporarily unreachable (e.g. an unmounted drive) — I want `agents_sync` to keep syncing my customizations across the reachable tools and to clearly report which tools are not, so that a missing tool never silently breaks my workflow or wipes my customizations in the other tools.

## Priority

Must Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`.

## Acceptance Criteria

- [ ] AC-1 [Normal — startup]: Given a configured, enabled agentic_tool has a missing root directory at daemon startup (any of the roots configured for its supported customization_types), When the daemon starts, Then:
  - the agentic_tool's status is set to `unavailable`;
  - an INFO-level log line names the agentic_tool, the missing root path, and the underlying reason ("path does not exist");
  - the daemon proceeds to operate over the remaining `available` agentic_tools without exiting.

- [ ] AC-2 [Normal — going unavailable mid-life]: Given an agentic_tool's status was `available` at the previous poll and its root has become missing or unreadable at the current poll (e.g. user uninstalled the agentic_tool, unmounted a drive, deleted the directory, or revoked permissions), When the watcher polls, Then:
  - a WARN-level log line names the agentic_tool, the root path, and the underlying reason;
  - the agentic_tool's status is set to `unavailable` for subsequent polls;
  - **no customization_artifact is treated as having been removed on that agentic_tool**, and its state entries for that agentic_tool are preserved verbatim.

- [ ] AC-3 [Normal — returning to available]: Given an agentic_tool's status was `unavailable` at the previous poll and its root is present, readable, and writable at the current poll, When the watcher polls, Then an INFO-level log line names the agentic_tool and its return to `available`, the agentic_tool's status is set to `available`, and any managed customization_artifact whose state lacks an entry for this agentic_tool begins extending to it on subsequent polls per the existing extension flow (see US-03).

- [ ] AC-4 [Normal — no destructive propagation from absence]: Given the daemon is running with one or more agentic_tools in status `unavailable`, When polls occur, Then for every managed customization_artifact: state entries for any `unavailable` agentic_tool are preserved unchanged (paths, digests); removal-propagation logic (see US-05 AC-2) never fires on the basis that an `unavailable` agentic_tool appears to be missing the artifact. Only an `available` agentic_tool can be the source of a removal signal.

- [ ] AC-5 [Normal — log only on transition]: Given an agentic_tool has been steadily in the same status (`available` or `unavailable`) across multiple polls, When the watcher polls, Then no per-poll log line is emitted for that agentic_tool's status. A log line is emitted only when the agentic_tool's status changes (steady-state silence). Startup is treated as a transition for the purpose of this rule (each agentic_tool's initial status is logged once).

- [ ] AC-6 [Failure — unreadable root]: Given an agentic_tool's root directory exists but is unreadable (permission denied, I/O error, etc.), When the watcher polls, Then the agentic_tool's status is set to `unavailable` for that poll, an ERROR-level log line names the agentic_tool, the root, and the underlying OS error, and no destructive operation is performed on any customization_artifact on the basis of this agentic_tool appearing to be missing artifacts.

- [ ] AC-7 [Failure — all agentic_tools unavailable]: Given every configured + enabled agentic_tool has status `unavailable` at the same poll, When the watcher polls, Then no destructive operation is performed on any customization_artifact, no state entry is mutated, and the daemon continues polling (a no-op cycle), waiting for at least one agentic_tool to return to `available`.

- [ ] AC-8 [Normal — project from canonical when never recorded]: Given a managed customization_artifact present in the canonical store and `state` but with **no on-disk file** on an enabled, supporting, `available` agentic_tool that `state` never recorded as holding it (a freshly imported artifact on zero agentic_tools, or a newly-available agentic_tool with no such file), When the watcher polls, Then the artifact is projected onto that agentic_tool from its canonical via the adoption pipeline (no bytes are displaced, so nothing is archived), and the projected file's digest is recorded in `state` so subsequent unchanged polls re-project nothing (NFR-05) — the absence is treated as "not yet projected," **not** as a removal. If the agentic_tool already holds an on-disk file for that artifact, it is **not** absent: discovery adopts or reconciles it through the normal path (archiving any displaced bytes per US-05 AC-1), never this heal path — so a heal never overwrites user-authored content. Absence of a file that `state` **did** record as present remains a removal signal per AC-4 / US-05 AC-2.

## Notes

The critical safety invariant is AC-4: an `unavailable` agentic_tool is **not** treated as "the user removed all the artifacts on that agentic_tool." Removal propagation (US-05 AC-2) fires only when an agentic_tool whose status is `available` is observed to be missing an artifact that is recorded in state. This is what prevents an unmounted drive or an uninstalled agentic_tool from wiping the user's library on the other agentic_tools.

Three statuses are deliberately distinguished:

| Status | Configured? | Enabled? | Root reachable? | Logged on entry |
|---|---|---|---|---|
| `available` | yes | yes | yes | INFO on first transition into this status |
| `unavailable` | yes | yes | no | INFO at startup; WARN on mid-life transition; ERROR if unreadable |
| `disabled` | yes | no | n/a | never (US-10 AC-7) |

An agentic_tool returning from `unavailable` to `available` triggers re-extension of every managed customization_artifact the agentic_tool is missing from. This reuses the new-customization-artifact / extension flow defined in US-03. Nothing manual is required from the user.

Log lines are structured. They include: the agentic_tool's `name`, the affected root path, the underlying OS error string (when applicable), and the transition direction (`available -> unavailable`, `unavailable -> available`, `startup -> available`, `startup -> unavailable`). Transitions are debounced: only status changes produce log output, not steady state.

This story replaces the v0.3 behaviour in which a missing root for any built-in agentic_tool caused the daemon to exit at startup. The safety property that motivated that behaviour (do not interpret a missing root as "all artifacts deleted") is now provided by AC-4 of this story without forcing the daemon to exit. See US-07 for the updated startup-failure semantics.

Related requirements: FR-04 (trusted removal source — load-bearing for AC-4), NFR-01 (data preservation), NFR-04 (resilience under transient failure), NFR-12 (log on transition only — AC-5), NFR-13 (structured error reporting — AC-1, AC-2, AC-6).
