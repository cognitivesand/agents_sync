# Amendment 010 — US-12 DRY clean: consolidate import ACs, rename the rule to `last_modified_wins`, resolve the AC-10/FR-16 contradiction

- status: governance applied 2026-06-01 (US-12 + glossary + FR-14); architecture / README / code / test propagation pending
- branch: feat/v0.5-cross-machine-merge
- date: 2026-06-01
- supersedes / relates to: US-12 (all import ACs and Notes), amendment 008 (canonical
  metadata model — supersedes its US-12 G4/G5/AC-3 drafts), amendment 009 (single import
  rule — renames its `mtime_wins` to `last_modified_wins`), US-03 (slug uniqueness),
  US-06 (runtime conflict rule), FR-12/FR-13/FR-16, NFR-05

## Motivation

US-12 had accumulated DRY/KISS debt: acceptance criteria that re-narrated mechanics already
owned by requirements, a rule named inconsistently with the field it compares, an impossible
`Given`, a redundant aggregate AC, and — after amendment 008 changed the import model — a
direct contradiction with FR-16. A clean pass under a strict "one fact, one home" discipline
consolidated the story from 19 acceptance criteria to 14 live (5 retired) with no loss of
governed behaviour.

## Principle / decision

Each acceptance criterion states one observable behaviour that no other artifact owns;
everything else references its owning requirement, glossary entry, or sibling AC. Volatile
implementation choices are pinned in one place. Removed criteria retire their numbers (no
renumbering — code and tests reference AC numbers).

## Governance edits (applied 2026-06-01)

### Terminology — the import/runtime rule renamed `mtime_wins` → `last_modified_wins`

The rule compares the metadata field `last_modified`; the former name `mtime_wins` wrongly
implied file-write time (the project defines `last_modified` as user-content modification
time, not file time). The rule is renamed `last_modified_wins` everywhere it is named. The
behaviour is unchanged: the candidate with the higher `last_modified` prevails, ties favouring
the locally-present artifact (FR-12). This is the same rule mirrored by the runtime conflict
resolution (US-06).

### US-12 acceptance criteria

- **AC-3 retired** — covered by AC-1 plus the canonical metadata model (amendment 008): the
  exported canonical carries its own `last_modified` in its `metadata` block.
- **AC-7 absorbs AC-17** — both had the identical `Given` (the import carries an artifact whose
  `target_slug(name)` matches a *different* local artifact under the same `customization_type`,
  a different `customization_artifact_id`). AC-7 now states the rule and the id-survivorship
  outcome in one place: reconcile by `last_modified_wins` (FR-12); the surviving content is
  written under the **local** `customization_artifact_id` (reused so on-disk files are not
  re-stamped) and the other id is retired. **AC-17 retired.**
- **AC-8 retired** — the `--collision-strategy` CLI flag no longer exists (amendment 009).
- **AC-10 rewritten** — the old text said orphan canonicals are "inert (the engine ignores
  canonicals without a state entry)", which directly contradicted FR-16 (the daemon adopts
  exactly those). Rewritten in FR-13 terms: per-artifact atomic import holds — each
  customization_artifact is either fully imported or not imported at all; each fully-imported
  canonical is adopted on the next poll (FR-16); the rest are absent until a later import
  completes them.
- **AC-11 retired** — covered by FR-12 ("re-importing a library exported from an unchanged
  state shall produce no change").
- **AC-19 retired** — a redundant aggregate: it only composed AC-5 (adopt new) + AC-6 / AC-7
  (collisions) + FR-12 (idempotent convergence) + NFR-05 (no further changes) + the slug
  uniqueness invariant (US-03 AC-8). The end-to-end "merge two libraries" scenario is an
  integration concern, not a governance AC that re-derives the per-case rules.
- **AC-18 moved** into the Import section (the dedicated "Cross-machine merge" section is
  dissolved — its merge rule now lives in AC-7); "intra-import slug merges" dropped (a
  single-source export cannot contain a slug collision, per US-03 AC-8); "pair" → the glossary
  term `customization_artifact`.
- **Format-neutral ACs** — the export's container (`.zip`) is pinned once in Notes; the ACs
  use the neutral nouns "the export" / "the import" so the container can change without
  rewording any AC.
- **Secret block (AC-12–AC-16)** — the repeated per-artifact WARNING clause is factored into a
  one-line Rule preamble; the five export/import × refused/accepted scenarios are retained.
- **Retired-numbers ledger** — a single line records the retired numbers: AC-3, AC-8, AC-11,
  AC-17, AC-19. No renumbering.

### Glossary (`project_description.md`)

Added **Customization library** and **Customization library export** (used by FR-12, FR-15,
NFR-15 as well as US-12), so they have one home; US-12's Terminology section is reduced to a
pointer (no index-then-restate).

## Requirements

None beyond amendment 008's FR-14 revision (change detection over canonical content only).
FR-12/FR-13/FR-15/FR-16 and NFR-05 already own every behaviour the retired/trimmed ACs
referenced.

## Design edits (architecture + README — pending)

- Rename `mtime_wins` → `last_modified_wins` wherever the rule is named (architecture, README,
  code identifiers, tests).
- The lexicographic-by-`customization_artifact_id` tiebreaker for cross-host `last_modified`
  ties — the concrete realization of FR-12's "deterministic total order" — lives in the
  architecture document, not in the acceptance criteria (it was removed from the old AC-17 in
  the AC-7 merge). Record that `generation` is host-local and not a cross-host discriminator.
- Remove the configurable-strategy description (amendment 009).

## Verification

Governance (US-12, glossary, FR-14) applied 2026-06-01. Architecture / README / code / test
propagation — including the `last_modified_wins` rename — lands with amendments 008 and 009's
code work; full `uv run pytest` + `mypy --strict` + `ruff` green before commit.
