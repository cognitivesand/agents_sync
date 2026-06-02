# Amendment 009 — Import reconciliation is mtime_wins only (remove configurable collision strategy)

- status: applied 2026-06-01 — strategy-removal code (config.py / cli.py /
  portable_archive.py) and test adaptations landed in Stream 2 (91a8265);
  rule renamed `last_modified_wins` throughout; full suite green on merge.
- branch: feat/v0.5-cross-machine-merge
- date: 2026-06-01
- supersedes / relates to: US-12 AC-6/AC-7/AC-8/AC-11/AC-18, the
  `import_collision_strategy` config key and `--collision-strategy` CLI flag
  introduced at US-12's origin (commit 69449a4 / 53efcb0 / 206d346); relates to
  amendment 008 (both edit US-12 AC-6 — apply 008's metadata change and 009's
  strategy removal as one combined AC-6 text).

## Motivation

US-12 import shipped with three configurable collision strategies — `skip`,
`mtime_wins` (default), `overwrite` — selectable per-install (`import_collision_strategy`
config key) and per-invocation (`--collision-strategy` CLI flag). Provenance check
(git log -S) confirms this was original to US-12, not a recent silent addition.

The configurability is unused complexity (KISS / YAGNI). The daemon's runtime
conflict rule (US-06) is already a single deterministic rule; import should mirror
it with the same single rule, not offer a knob. `skip` (ignore the import) and
`overwrite` (displace unconditionally) are footguns: `skip` can silently drop a
newer artifact; `overwrite` can destroy a newer local one. `mtime_wins` —
most-recent-content prevails, ties to the local artifact — is the safe, sufficient
rule and the only one any user needs.

## Principle / decision

Import reconciliation is a single, non-configurable rule: **`mtime_wins`** (renamed
**`last_modified_wins`** in amendment 010; behaviour unchanged). There is no
`import_collision_strategy` config key and no `--collision-strategy` CLI flag.

## Proposed governance edits (require user validation)

### User stories — US-12

- **AC-6** — rewrite to state the single `mtime_wins` rule (drop the `skip` and
  `overwrite` bullets). Combined with amendment 008's content-differs change.
- **AC-7** — replace "the same `import_collision_strategy` is applied" with "the
  same `mtime_wins` reconciliation is applied".
- **AC-8** — removed in place (number retained to keep AC-9…AC-19 stable):
  marked `[Removed]`, superseded by this amendment; there is no CLI flag or config
  key.
- **AC-11** — drop "under any `import_collision_strategy`".
- **AC-18** — drop the "under `overwrite`/`mtime_wins`" qualifier (mtime_wins is the
  only mode); `--force` is still required when any local pair would be displaced.
- **Notes** — rewrite the `import_collision_strategy` paragraph to state the single
  fixed rule.

### Requirements

None. FR-12 already mandates the mtime_wins behaviour ("the most recently modified
candidate prevailing, ties resolved in favour of the locally-present artifact") and
never required configurability; removing the knob brings code in line with FR-12.

## Design edits (architecture — applied after validation)

- `docs/architecture.md`: where import collision handling is described, state the
  single mtime_wins rule; remove any mention of strategy selection.
- `README.md`: remove `--collision-strategy` / `import_collision_strategy` from the
  import usage and config sections.

## Implementation plan

- `config.py`: remove the `import_collision_strategy` field and its default/validation.
- `cli.py`: remove the `--collision-strategy` option from the `import` subcommand.
- `portable_archive.py`: remove the strategy parameter and the `skip`/`overwrite`
  branches; mtime_wins is the unconditional reconciliation rule.
- Honour "never delete content": removing config/flag/branches is code deletion, not
  user-content deletion — allowed.

## Test plan

- Remove or re-point `skip`/`overwrite` tests in `test_cli_export_import.py`,
  `test_portable_archive.py`, `test_portable_archive_secret_egress.py`.
- Keep/strengthen the `mtime_wins` tests (import-newer-wins, local-newer-wins,
  tie-to-local).
- Assert the CLI `import` subcommand no longer accepts `--collision-strategy`.
- Assert `config` rejects/ignores a stray `import_collision_strategy` key per the
  config's unknown-key policy.

## Verification

Full `uv run pytest` + `mypy --strict` + `ruff` green. Governance applied only after
user validation of the US-12 edits.
