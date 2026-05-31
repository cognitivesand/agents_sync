# Amendment 005 — Documentation coherence: docs describe shipped v0.6 behaviour

- status: applied (non-governance docs); one governance line pending user validation
- branch: feat/v0.5-cross-machine-merge
- date: 2026-05-31
- relates to: v0.6 architecture audit (finding B), amendments 002/003/004

## Motivation

The v0.6 canonical-as-truth work shipped (P1–P5, v0.5.2–v0.5.6) but several documents
were never updated and now misdescribe running behaviour — the architecture audit's
CRITICAL/MAJOR cluster:

- `architecture.md §6.1` declared the entire import/canonical work "designed, not
  built… the current code does the opposite". False — it is shipping.
- `architecture.md` header said "current as of v0.5"; the §4 module map still listed
  flat `adoption.py`/`discovery.py` and "Totals: 19 modules" against the v0.6 package
  split; `schema_version=2` appeared where the code is `=3`.
- `README.md` documented render-on-import (deleted by Decision A / US-12 AC-5) and
  called the bulk-delete glitch guard "planned" though US-11 AC-9 shipped; the
  changelog stopped at 0.5.0.
- amendment 002 was still stamped "code deferred", though the deferred pass shipped.

## Principle / decision

Governance and design documents describe **shipped** behaviour. Where a past
changelog entry recorded behaviour later reversed, it is **forward-referenced as
superseded**, never rewritten (no-rm/history rule).

## Proposed governance edits (require user validation)

`docs/project_description.md` (a governance artifact) line ~101 hard-codes
`schema_version: 2` in the state-envelope example. Proposed one-word factual
correction to match the shipped code (`STATE_SCHEMA_VERSION = 3`):

> before: `{"schema_version": 2, ...}`
> after:  `{"schema_version": 3, ...}`

No other governance text changes.

## Design edits (architecture — applied)

- §6.1 heading + status block: PLANNED → BUILT, with an honest note that the FR-15
  cross-process-lock gap (finding A) remains open.
- header status → v0.6 (v0.5.6); `schema_version` 2→3 (two sites); module-map note
  recording the adoption/ + discovery/ package split and `portable_archive.py`,
  with a full re-tabulation tracked as doc-debt.

## Implementation / other docs (applied)

- `README.md`: Backup/Restore prose → canonical-only import; bulk-delete prose →
  shipped glitch guard (US-11 AC-9); new 0.5.6 changelog entry; 0.4.3 render-on-import
  line forward-referenced as superseded.
- amendment 002 re-stamped `applied` with the landing commits.

## Verification

Full `uv run pytest` green (doc-only; no code touched). Governance line applied only
after user validation.
