# Amendment 004 — Import archives displaced canonical; quarantine failure fails closed

- status: applied
- branch: feat/v0.5-cross-machine-merge
- date: 2026-05-31
- supersedes / relates to: amendment 002 (canonical-only import, FR-13, US-12 AC-17),
  the v0.6 safety audit (findings C and #6), NFR-01, FR-11

## Motivation

A safety audit (Leveson/Schneier/Ormandy lens) traced two data-loss paths the code
does not close, both grounded in cited mechanism:

- **C — import overwrites a displaced canonical with no prior archive.**
  `portable_archive.import_from_zip` promotes each winning canonical with a bare
  `os.replace(pending_path, live_path)` (portable_archive.py:535-538) and defers
  archiving of the displaced bytes to "the next poll" via the FR-14 stale-digest
  trick. In the narrow but real case of a canonical-only **stub** (empty
  `agentic_tools`, never projected) that a second import overwrites before
  projection, there are no tool-side files to recover from and nothing was
  archived — the prior bytes are gone. This inverts NFR-01's archive-before-write
  ordering for the canonical store and contradicts US-12 AC-17 ("the loser archived").

- **#6 — corrupt-state quarantine fails open.** `state._quarantine_corrupt`
  (state.py:403-433) is best-effort: when the move of a corrupt `state.json` into
  `quarantine/` fails (read-only or cross-device `state_dir`), it logs and **does
  not propagate**. `load_state` then returns `{}`, and the next `save_state`
  atomic-overwrites the corrupt-but-original bytes the ERROR log just told the
  operator to "inspect to recover". The recovery source is destroyed.

## Principle / decision

The canonical store obeys the same archive-before-write rule as tool files (NFR-01):
a displaced canonical is preserved before it is overwritten. And a corrupt state
record that cannot be moved aside **fails closed** — the daemon must not overwrite
bytes it could not first preserve.

## Proposed governance edits (require user validation)

None. Both changes align the code to **existing** requirements — NFR-01 (no loss of
user-authored content) and FR-11 (malformed state is frozen/preserved, not silently
destroyed). No FR/NFR/US/AC text changes.

## Design edits (architecture — applied after validation)

None required; this restores the archive-before-write invariant the architecture
already states (I-3 / NFR-01).

## Implementation plan

- **C** — `portable_archive.import_from_zip`: in the promote loop, when the live
  canonical path already exists, call `archive.archive_canonical(state_dir,
  surviving_pair_id)` to move the displaced bytes into
  `archive/<id>/_canonical/` **before** the `os.replace`. Thread the surviving
  pair_id into the staged tuple.
- **#6** — `state._quarantine_corrupt`: on a quarantine-move `OSError`, log as now
  but then **raise** a new `StateQuarantineError` (the corrupt file is still at
  `state.json`; returning empty would let the caller clobber it). `load_state`
  propagates it; the daemon poll loop already catches whole-poll exceptions, so it
  fails the poll loudly, preserves the corrupt bytes, and retries — never overwrites.
  When the move **succeeds**, behaviour is unchanged (return `{}`, safe rebuild).

## Test plan

- C: import a stub canonical, then import a second canonical onto the same surviving
  id; assert the displaced bytes are present under `archive/<id>/_canonical/`.
- #6: corrupt `state.json`, force the quarantine move to fail (monkeypatch the move
  at the OS boundary to raise `OSError`), assert `load_state` raises
  `StateQuarantineError` and that `state.json` is left untouched (not overwritten).

## Verification

Full `uv run pytest` + `mypy --strict` + `ruff check` green. Done = both paths
archive/fail-closed, two new regression tests pass, live daemon unaffected.
