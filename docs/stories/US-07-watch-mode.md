# US-07: Continuous background sync

## Persona

Both

## User Story

As a developer who uses two or more agentic_tools, I want `agents_sync` to run quietly in the background and keep my customizations in sync continuously, so that my edits propagate without me having to invoke any command — and so that I can install or uninstall agentic_tools at any time without restarting `agents_sync`.

## Priority

Must Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`.

## Acceptance Criteria

- [ ] AC-1 [Normal — propagation latency]: Given the daemon is running, When an edit occurs on any one available agentic_tool, Then it is detected and propagated to every other available, participating agentic_tool within at most twice the configured polling interval.

- [ ] AC-2 [Normal — clean shutdown]: Given the daemon is running, When `SIGINT` or `SIGTERM` is received, Then the current poll completes if in progress and the process exits cleanly with code 0.

- [ ] AC-3 [Normal — transient-exception recovery]: Given the daemon catches a transient exception during a poll (e.g. a temporary I/O error on one customization_artifact, or an agentic_tool that becomes unavailable mid-poll), When the next poll occurs, Then the daemon resumes normally without operator intervention; the exception is logged with enough context to identify the customization_artifact and agentic_tool involved.

- [ ] AC-4 [Normal — restart resumes state]: Given the daemon is supervised by a user-level service manager, When the daemon is restarted, Then on next start it reads existing state and continues syncing without re-translating unchanged customization_artifacts.

- [ ] AC-5 [Normal — startup with fewer than two agentic_tools available]: Given fewer than two registered + enabled agentic_tools have status `available` at startup (because their roots are missing or unreadable), When the daemon starts, Then it logs each agentic_tool's status per US-11 AC-1, does not exit, and enters a polling loop in which it performs no destructive operations (no propagation, no removal, no adoption) until at least two agentic_tools become `available`.

- [ ] AC-6 [Normal — agentic_tools may come and go]: Given the daemon is running with two or more `available` agentic_tools, When the user installs or uninstalls an agentic_tool (causing one of that agentic_tool's configured roots to appear or disappear), Then at the next poll:
  - the agentic_tool's status transitions per US-11 (logged once on the transition);
  - the daemon continues operating;
  - the set of participating agentic_tools for each customization_artifact is recomputed automatically.

- [ ] AC-7 [Failure — configuration error]: Given the daemon's configuration is structurally invalid (malformed TOML, two agentic_tools with identical `name`, an agentic_tool declaring a `customization_type` in `supported_customization_types` for which its IO module is missing the required functions, the `state_path` parent cannot be created, the `poll_interval_seconds` is not a positive number, etc.), When the daemon starts, Then it logs a structured error naming the specific configuration defect and exits with a non-zero code distinct from any runtime sync failure code (per NFR-10).

- [ ] AC-8 [Normal - Windows silent startup]: Given `agents_sync` is installed on Windows, When the user logs in and the background launcher starts the daemon, Then no terminal, console, PowerShell, or command prompt window is opened, the daemon remains running in the background, and startup logs are written to the configured log destination.

## Notes

The daemon is the only execution mode; there is no separate one-shot CLI invocation. The polling interval is configurable; propagation latency under nominal conditions includes one poll to detect a change and one poll to write the result.

The v0.3 behaviour was: a missing root for any built-in agentic_tool at startup caused the daemon to exit with a configuration-failure exit code. v0.4 changes this: a missing root is a **runtime** condition (the agentic_tool is `unavailable`), not a **configuration** condition. The daemon stays alive and resumes when the root reappears. The safety property previously provided by the v0.3 exit — "never interpret a missing root as 'all artifacts deleted'" — is now provided by US-11 AC-4 (an `unavailable` agentic_tool never sources a removal signal).

The "at least two `available` agentic_tools" threshold in AC-5 reflects the obvious reality that sync needs a source and at least one destination. With one agentic_tool available, the daemon has nothing to project to; with zero, nothing to read from. In both degenerate cases the daemon polls quietly and waits.

Configuration errors (AC-7) remain a fatal startup condition: these are bugs in the config file, not absences in the environment. Distinct exit codes (per NFR-10) let the service manager apply the right restart policy.

Related requirements: FR-02 (fault isolation), NFR-02 (latency), NFR-04 (self-healing), NFR-08 (resource stability over long runs), NFR-10 (distinct exit codes), NFR-12 (log on change, not per poll), NFR-13 (structured error reporting).
