# Amendment 018 — US-09 AC-4: a corrupt canonical is quarantined, not archived

- status: applied
- branch: fix/size-explosion-hardening
- date: 2026-06-05
- relates to: US-09 AC-4, NFR-01, NFR-04; `canonical.py:load_canonical`,
  `state.py:_quarantine_corrupt`; architecture proposal §17.

## Motivation

US-09 AC-4 (recovery from a truncated/unparseable canonical) says the bad bytes
are "archived". The shipped behaviour, and the established convention, is to
**quarantine** them: `load_canonical` moves a corrupt `canonical/<id>.json` to
`state_dir/quarantine/`, exactly as `state.py` does for a corrupt `state.json`.
The AC's "archived" is the outlier and the only remaining spec-vs-code
discrepancy from the architecture-proposal review.

## Principle / decision

`archive/` preserves **user-authored content** before an overwrite/delete
(NFR-01) and is subject to retention GC (NFR-07). A canonical is a **derived
internal daemon record**, not user content; a corrupt one belongs in
`quarantine/` — the home for unparseable internal records (`state.json`,
`canonical/*.json`) kept for recovery/forensics. Quarantining keeps the
user-content archive clean, keeps it out of the user-content GC, and unifies
corrupt-internal-record handling in one place. The recovery itself is unchanged:
the corrupt canonical is treated as missing and rebuilt next poll from the tool
with the most recent `mtime`.

## Governance edit (validated by the user)

### User stories — US-09 AC-4
"the truncated canonical is archived" → "the truncated canonical is moved to
quarantine (its bytes preserved for recovery, separate from the user-content
archive)". The rest of AC-4 (treated-as-missing, structured error, rebuild from
newest-mtime tool) is unchanged.

## Design edits (applied after)

`docs/architecture_simplification_proposal.md` §17: the US-09 AC-4 wording is no
longer an open governance item.

## Verification

No code change — the shipped behaviour already quarantines (covered by
`tests/test_state_schema_v3.py::test_load_canonical_quarantines_corrupt_file`).
The amendment removes the last spec-vs-code wording gap from the proposal review.
