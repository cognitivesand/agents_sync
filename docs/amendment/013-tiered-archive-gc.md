# Amendment 013 — Bounded archive growth via tiered GC (NFR-07 / RC-5)

- status: applied
- branch: fix/size-explosion-hardening
- date: 2026-06-04
- relates to: docs/bugs/602c6d_State_dir_size_explosion_crash_loop.md (RC-5, §5.4);
  NFR-07 (bounded archive growth), NFR-08 (resource stability), NFR-17
  (unattended operation); amendment 011 (clean identity core).

## Motivation

The data-preservation archive (`archive/<pair_id>/<side>/<name>.<ts>`,
`archive.py`) is append-only — every overwrite/delete snapshots prior bytes
(NFR-01) — and nothing bounded it (bug 602c6d, RC-5: 1.65 M dirs / 56 GB).
Amendment 011 removed the *driver* of the explosion (a malformed artifact is
never adopted, so it never archives), but NFR-07 requires the archive to stay
bounded under normal long-run operation too. There was no GC and no
`agents-sync` command to prune.

## Principle / decision

**The archive is bounded by a tiered, age-based GC**: keep all recent history,
then downsample older history by calendar day, then drop the oldest (bug
602c6d §5.4). GC runs automatically on a low-frequency daemon tick (NFR-17
unattended) and on demand via `agents-sync prune`. GC never deletes an entry
whose timestamp it cannot parse (fail-safe), and a GC fault never crashes the
poll loop (FR-02).

Tiers (constants in `archive_gc.py`): `<7 d` keep all; `7–30 d` keep newest 4
per (pair_id, side, UTC day); `30–365 d` keep newest 1 per day; `>365 d` delete.

## Proposed governance edits (require user validation)

**None.** NFR-07 and NFR-08 already require bounded archive growth and resource
stability; this implements them. No requirement/story/AC text changes.

> Note for P8: `agents-sync prune` is a new user-facing command with no owning
> user story. It is a mechanism for NFR-07, not new product scope, so no story
> is strictly required; flagged for the user to decide whether to add one.

## Design edits (architecture — applied after validation)

`docs/architecture.md`: add `archive_gc.py` (Layer 3, beside `archive.py`) to the
module map and the `prune` subcommand + daemon GC tick to the Layer-4 entries.

## Implementation plan

- `src/agents_sync/archive_gc.py`: `prune_archive(state_dir, *, now=None,
  dry_run=False) -> GcReport`; pure tier logic, injectable clock.
- `cli.py`: `prune [--dry-run]` subcommand → `_run_prune` (exit 0/1).
- `daemon.py`: `gc_interval_seconds` (default 24 h; `None` disables); a guarded
  `_prune_archive_safely` runs on the tick after a returning poll.

## Test plan

`tests/test_archive_gc.py`: each tier boundary, unparseable-entry fail-safe,
dry-run, missing-archive no-op. `tests/test_cli_prune.py`: command deletes
expired / `--dry-run` keeps. `tests/test_daemon_signals.py`: the GC tick prunes.

## Verification

`bash scripts/ci.sh` green (574). Expired archive entries are removed; recent
ones and unparseable ones are retained.
