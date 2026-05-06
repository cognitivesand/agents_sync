# US-10: Automatic migration from claude-codex-sync v0.1

## Persona

Bob

## User Story

As a current user of `claude-codex-sync` v0.1.x, I want the new `agents-sync` v0.2 to detect my prior installation and migrate state, paths, and configuration on first run so that I don't lose history or have to reconfigure manually.

## Priority

Must Have

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given a v0.1 state file at `~/.local/state/claude-codex-sync/state.json` exists, When v0.2 starts for the first time, Then for each entry it mints a UUIDv4 `pair_id`, archives the live Claude `.md`, injects `pair_id` into the Claude file, archives the live Codex `.toml`, regenerates the Codex file from the canonical (with `pair_id`), and writes the migrated index to `~/.local/state/agents-sync/state.json`.
- [ ] AC-2 [Normal]: Given a v0.1 config at `~/.config/claude-codex-sync/config.toml` exists, When migration runs, Then it is moved (not copied) to `~/.config/agents-sync/config.toml`; the old path no longer exists after success.
- [ ] AC-3 [Normal]: Given a v0.1 systemd unit `claude-codex-sync.service` is installed in `~/.config/systemd/user/`, When migration runs, Then the v0.1 unit is disabled, an `agents-sync.service` unit is installed and enabled, and the user is informed via INFO log of the unit change.
- [ ] AC-4 [Normal]: Given migration has completed previously, When the tool starts again, Then it detects no v0.1 artifacts and proceeds with a normal v0.2 startup (idempotent).
- [ ] AC-5 [Failure]: Given migration encounters a parse or write error mid-flight, When the error is detected, Then partial migration is rolled back where possible (renamed paths restored), the v0.1 paths are preserved, a structured error is logged with the failed step, and the tool exits with code 1.

## Notes

Migration is a one-shot operation gated on the presence of v0.1 paths. Once successful, the v0.1 state directory is itself archived under `archive/migration-v01-to-v02/` along with a manifest of what was migrated. The user's edits in v0.1 Claude sources are preserved bit-for-bit (archive before pair_id injection).

Related requirements: REQ-F-14, REQ-F-09, REQ-F-15, REQ-R-05, REQ-O-04.
