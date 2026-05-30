# Amendment 003 — Import shall run safely while the daemon is active

- status: applied
- branch: feat/v0.5-cross-machine-merge
- date: 2026-05-31
- supersedes / relates to: amendment 002 (cross-machine merge import; FR-12/FR-13),
  FR-14 (canonical-change detection)

## Motivation

The v0.6 P4 work made the daemon canonical-aware precisely so a customization-library
import could be performed without first stopping the daemon. On 2026-05-31 this was
exercised against the live install: with `agents-sync.service` **active**, an
`agents-sync import` of a snapshot ran to completion — `accepted=3 skipped=2`, the
accepted canonicals projected onto every supporting tool, and the next daemon polls
held steady at `changed=0 failed=0 blocked=0`. No state corruption, no lost content.

This coexistence is a real, relied-upon property, but **no requirement states it**.
FR-12 covers import idempotency, FR-13 covers per-artifact import atomicity, and FR-14
covers the daemon re-projecting a changed canonical — none of them says the import and a
running daemon may operate **concurrently** without corrupting shared state or losing
data. The property is therefore untested and unprotected against regression.

## Principle / decision

An import and a running daemon may operate at the same time; their interleaving must
converge to the same managed state as running them sequentially, and must never corrupt
the shared state record or lose user-authored content.

## Proposed governance edits (require user validation)

### User stories

None. Import is owned by US-12 (portable library snapshot); concurrency between the
import process and the daemon process is a system-wide property no single story owns,
which is exactly what `docs/project_requirements.md` is for. No user-story edit is
proposed.

### Requirements

New requirement (no original — this is a brand-new FR), to be added to
`docs/project_requirements.md` after FR-14:

> - **FR-15** (Import-while-active safety): The daemon **shall** permit a customization
>   -library import to run while the daemon is active. A concurrent import and daemon poll
>   **shall not** corrupt the shared state record nor lose user-authored content, and the
>   resulting managed state **shall** be identical to that produced by the same import and
>   poll run sequentially.

## Design edits (architecture — applied after validation)

Add a short note to `docs/architecture.md` (the canonical-aware daemon / import section)
recording the two mechanisms that realise FR-15:
1. **Atomic state replacement** — `state.atomic_write_text` writes a unique per-process
   temp file and `os.replace`s it onto `state.json`, so a daemon poll never reads a torn
   record and a concurrent import write lands all-or-nothing.
2. **Canonical-as-truth idempotent reconcile** (FR-14) — a poll that interleaves with an
   import reconciles from the canonical store, so any ordering converges; a mid-import
   poll at worst defers projection to a later poll, never corrupts.

## Implementation plan

No production code change is expected: the mechanisms above already exist
(`state.atomic_write_text`, the canonical-aware reconcile from P4). The change is a new
regression test that pins the property, plus the requirement and architecture note. If
the test surfaces a genuine interleaving defect, that becomes a separate, scoped fix
under this amendment.

## Test plan

`tests/test_import_while_daemon_active.py` — one test per FR-15:
- Build a snapshot and a populated state dir; run an `import_from_zip` and a daemon
  `sync_once` against the **same** state dir interleaved (poll immediately before and
  after the import, and a poll that races the import), then assert: (a) `state.json`
  parses and is well-formed at every observation (no torn read), (b) no pair loses its
  recorded content, (c) the final managed state equals the sequential
  import-then-poll result, (d) `failed == 0`.

## Verification

Full `uv run pytest` + `mypy --strict` + `ruff check` green. "Done" = FR-15 added,
architecture note added, the new test passes, and the live daemon (already observed)
remains `failed=0`.
