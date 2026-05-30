# Amendment 001 — Identity tag readable in isolation; freeze on malformed managed metadata

- status: applied
- landing commit: d151d4e
- branch: fix/v0.5-malformed-metadata-warn-not-block
- date: 2026-05-30
- supersedes / relates to: US-03 (AC-10); deferred option-3 framing from the
  fix/v0.5-unconfigured-root-extend-crash investigation; relates to FR-02, FR-04, NFR-13

## Motivation

A live daemon poll reported `blocked=1`. Root cause: the real on-disk skill
`~/.claude/skills/code_and_tests_quality_review/SKILL.md` had a `description`
field — an artifact-owned field that users and bots freely edit — containing an
unquoted `: ` (`source/test pair: each pair`). ruamel rejected it
(`ScannerError: mapping values are not allowed here`). Because
`extract_pair_id_from_md` full-parses the entire artifact-metadata block to read
our injected `customization_artifact_id`, a corrupted field we **do not own**
broke our ability to read the one field we **do** own. The pair was blocked.

This exposed a coupling: our identity read depends on the validity of content we
do not control. Per project_description §35, the `customization_artifact_id` is
the **only** thing we inject; per §123, `name`/`description` are the artifact's
own fields that the tool requires. So the id tag must be readable on its own,
regardless of the surrounding block.

## Principle / decision

**The `customization_artifact_id` tag must be extractable in isolation: id
extraction shall succeed whenever the tag itself is present and well-formed, even
if the rest of the artifact metadata is malformed. A managed artifact whose
surrounding metadata becomes malformed is frozen — never re-identified, never
removed — until repaired.**

## Proposed governance edits (require user validation)

### User stories — `docs/stories/US-03-new-customization-artifact-adoption.md`

Add a new acceptance criterion (AC-10 unchanged; it stays scoped to *new*
artifacts):

> - [ ] **AC-11 [Failure — managed customization artifact became malformed]**:
>   Given an **already-managed** customization artifact whose on-disk artifact
>   metadata has become malformed or unparseable (e.g. invalid YAML frontmatter)
>   while its `customization_artifact_id` tag is still present and well-formed,
>   When discovery encounters it, Then the artifact's owning
>   `customization_artifact_id` is **frozen** — not reconciled, not synced, and
>   **not interpreted as a removal** (no removal is propagated to other
>   agentic_tools) — and a **structured warning** names the agentic_tool, the
>   path, and the underlying parse error, until the user repairs the metadata.

### Requirements — `docs/project_requirements.md`

Add a new functional requirement:

> - **FR-11** (Identity robustness): The daemon **shall** extract a
>   customization_artifact's `customization_artifact_id` independently of the
>   validity of the remainder of its artifact metadata. When the artifact
>   metadata is malformed but the `customization_artifact_id` tag is present and
>   well-formed, the daemon **shall** recover the id, **shall not** mint a new
>   id, and **shall not** misattribute the artifact. When the metadata is
>   malformed such that content cannot be parsed, the daemon **shall** freeze the
>   owning customization_artifact (no reconcile, no sync, no removal) and emit a
>   structured warning per NFR-13, rather than failing or blocking on identity.

## Design edits (architecture — applied after validation)

`docs/architecture.md`: (a) §5.1 contract point 3 — strengthen "`extract_pair_id`
never raises … returns `None`" (a contract the code currently violates) to the
**isolation** rule: recover the id when the tag is well-formed even if the rest
of the block is malformed. (b) `DiscoveryWalker` note — clarify that isolated id
recovery means a malformed managed artifact still appears under its own id and is
never mistaken for a deletion. (c) §6 `sync_once` pipeline — document the
**orchestrator freeze**: a pair whose content cannot be parsed is warned, added
to `blocked`, and not synced or removed.

## Implementation plan

> **Refinement (post-validation, governance unchanged):** the original plan put
> the freeze in the enumerator. Tracing `sync_once` showed the enumerator already
> defers full parsing; once id extraction is made non-raising (FR-11), the content
> parse-failure surfaces at `process_pair`, where FR-02 isolation already prevents
> sync and removal. So the freeze belongs at the **orchestrator boundary**, not the
> walker/enumerator. FR-11 and AC-11 text are unaffected.

Surgical, markdown/YAML adapter first (the path that failed); other adapters
tracked as follow-up.

1. `src/agents_sync/markdown_yaml_metadata_block.py` — `extract_pair_id_from_md`:
   on `YAMLError` from the full parse, recover the `pair_id` via an isolated
   line regex within the frontmatter delimiters; return it (validated downstream),
   else `None`. Happy path unchanged. Restores architecture §5.1 point 3.
2. `src/agents_sync/sync.py` — at the `process_pair` boundary, catch
   `(AdapterParseError, YAMLError)` **before** the generic `Exception` handler:
   emit a structured warning naming `pair_id`, each `tool:path`, and the cause,
   and add the pair to `_blocked_pair_ids` (FROZEN). No sync; no removal (the pair
   is in `discovery`, so the removal loop already skips it). Serves AC-11.
3. Enumerator unchanged — with extract no longer raising on malformed YAML, its
   defensive ERROR paths remain only for genuinely unexpected failures.

## Test plan

- FR-11 / isolation: a markdown artifact whose `description` is malformed YAML
  but whose `pair_id:` line is intact → `extract_pair_id_from_md` returns the id
  (regression for the exact `code_and_tests_quality_review` failure).
- AC-10 (currently untested): a **new** malformed artifact → skipped, not
  blocking, structured WARNING via `caplog` naming tool/path/error.
- AC-11: a **managed** malformed artifact → owner frozen (blocked), no removal
  propagated, structured WARNING.

## Verification

Full `uv run pytest`, `mypy --strict`, `ruff check` clean on touched files.
"Done" = all three tests green, no behavioral change on the happy path, and the
live daemon (already unblocked by the data fix) stays `blocked=0`.
