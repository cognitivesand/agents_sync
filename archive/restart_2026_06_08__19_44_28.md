# Restart — 2026-06-08

> Last updated by Claude at 2026-06-08T19:45:00Z. Session-handoff snapshot. A fresh
> session reading this should be able to resume without further explanation.

## 0. Git pin (do not edit by hand)

- `head_sha`: a3abe954df8b1e2606eb081cc8aff62106db57c8
- `head_short`: a3abe95
- `branch`: fix/size-explosion-hardening
- `dirty`: true
- `dirty_summary`: ~17 untracked, all under `docs/audits/` — review artifacts, intentionally NOT tracked
- `remote_head`: a3abe954df8b1e2606eb081cc8aff62106db57c8 (pushed, up to date)
- `saved_at`: 2026-06-08T19:45:00Z

## 1. Read these first

Order matters:

- `AGENTS.md` (via `~/.claude/CLAUDE.md`) — global rules (POLA/KISS/YAGNI/DRY/SRP/SoC; §3 size limits ≤40 lines/fn, ≤300/file; §8 fail-fast; §11 commits; §13 bash discipline; §14 deps).
- `docs/architecture_implementation_plan.md` — **the active plan**: greenfield rebuild as gated steps S1–S25. Phase A ✓, Phase B (planner) ✓, **Phase C dialects done through S11b** (S11 was split into S11a/S11b). Next is **S12**.
- `docs/architecture_simplification_proposal.md` — rev 4 target design. §10 = centralized translation (the dialects + the shared `field_mapping` recipe-application); §13 = module map; §12 = cross-cutting homes.
- `docs/project_description.md`, `docs/project_requirements.md` (FR/NFR), `docs/stories/US-*.md` — governing spec. **S12 touches US-15 (framework-specific hold-back) — a user story; read it before coding.**
- The `incremental_step` skill (`~/.claude/skills/incremental_step/SKILL.md`) — the per-step gate this work follows.

## 2. Working context (deltas not in the docs)

- **We execute the rebuild one gated step per `/incremental_step`.** User drives with "next"/"continue". The user's standing instruction (set this session): run the **code AND test audits at the end of each step, max 3 audit→fix loops, and only advance to the next step when both are spotless** — escalate rather than weaken anything.
- **Per-step gate (fixed order):** detail (+confirm scope/split, surface genuine decisions to the user) → docs (design docs applied directly; governance needs user approval of exact text) → tests + `/audit-tests` (the ONLY point tests change; fix every finding, re-audit after any change) → code → full CI (`bash scripts/ci.sh`) → `/code_and_tests_quality_review` on the diff (run by hand-orchestrating the **code-quality-auditor** + **test-quality-auditor** subagents in parallel; 3 targets: spec / clean-code / efficiency) → spotless (≤3 loops) → write a markdown report under `docs/audits/code_audit_<ts>.md` + update `docs/audits/.last_code_review.json` (NEVER stage docs/audits) → `/bcp`.
- **Greenfield-parallel:** new code in `src_new/agents_sync/`, tests in `tests_new/` (`uv run pytest -c pytest_new.ini`). Old `src/` is **reference only, never modified**. Conformance suite (`tests/`) must stay green every step. Rebuild suite now **245 green**; conformance green. Cutover (S24–S25) is a directory rename.
- **Versioning:** each rebuild step is a **PATCH** `feat(rebuild)` (nothing shipped changes until cutover). Now at **0.7.19**. **Always `uv lock` + stage `uv.lock` with the bump** — see [[project_uvlock_version_bump]].
- **The translation architecture (built S9–S11b):** `translation.py` dispatches on `tool_surface.surface_format.dialect` to a dialect's `parse`/`render`/`extract_id` (the three take the whole **ToolSurface**, not just the format — the seam keys per-tool bags and stamps kind; the pure core never names a tool). Dialects share ONE recipe-application: **`dialects/field_mapping.py`** (`fold_fields_into_canonical` / `project_canonical_to_fields` + coercion). A dialect differs only in how it extracts a flat field-mapping from the wire and reassembles it. `MalformedSurfaceError(ValueError)` (in `dialects/__init__.py`) = malformed CONTENT (read phase catches → ParseFailure); a plain `ValueError` = recipe/config error (fail loud, e.g. unsupported dialect/format). The distinction is load-bearing and **tested via `not isinstance(err, MalformedSurfaceError)`** because MalformedSurfaceError subclasses ValueError.
- **`SurfaceFormat` recipe fields grown so far:** `dialect`, `id_field`, `known_fields` (tuple of (field_key→canonical_attr) pairs, hashable), `tool_only_fields`, `map_key_path` (keyed-map), `file_format` (json/toml). All additive with empty defaults.
- **Body handling:** `fold_fields_into_canonical(..., body=...)` — markdown passes the md body; keyed-map/structured-text pass `body=None`. Structured-text carries its body as a NAMED FIELD via a `known_fields` pair like `("developer_instructions","body")` — NO field_mapping change needed. **Invariant (documented in field_mapping):** body comes from the `body` param OR a known_fields→body pair, never both (the known_fields loop runs after and would override the param).
- **Decisions locked this session (do NOT re-litigate):**
  - S9 signature: the three translation fns take the whole `ToolSurface` (not `surface_format`) — proposal §10 updated.
  - Size-explosion hardening (`parser_bounds`) is OUT of the dialects — deferred to **S24 cutover gate** (conformance size-explosion tests enforce it). Recorded in plan S9 row + S24 gate.
  - S11 round-trip fidelity: **key-order + data only, comments NOT preserved, stdlib only (no tomlkit/jsonc dep)** — user-confirmed. JSONC comment-tolerant read deferred (no tool declares it; a correct strip must be string-aware — mcp URLs contain `//`).
  - structured_text holds BOTH the shared json/toml codec AND the whole-file dialect (one module, §10-sanctioned).
- **`docs/audits/` is deliberately UNTRACKED** — never stage it; every `/bcp` excludes it. `.last_code_review.json` marker is at `2026_06_08__19_35` / `diff` mode.

## 3. Active task

### 3.1 Goal

Rebuild `agents_sync` as the thin, clean, spec-compliant architecture in the proposal, in small independently-shippable gated steps, then cut over from the old `src/`.

### 3.2 Constraints

- Hard: conformance suite green every step; full `incremental_step` gate to spotless (both code + test audits clean, ≤3 loops or escalate); governance artifacts (description/stories/AC/requirements) change only with explicit user approval of exact text ([[feedback_governance_approval]]); removing behaviour updates the spec in the same change ([[feedback_spec_code_alignment]]).
- Soft: greenfield-parallel; PATCH bumps; additive YAGNI growth; surface genuine scope/dependency decisions to the user at the detail step.

### 3.3 Status — what is done

**Phase A (domain core) ✓, Phase B (planner) ✓, Phase C dialects through S11b ✓.**
- S1–S8 ✓ (canonical_document, identity, naming, tool_surface, sync_plan, recover_identity, reconcile_known, adopt_candidates, winner_selection, compute_sync_plan + 4 guards). Shipped 0.7.15.
- **S9 ✓** markdown_frontmatter dialect + translation seam — `f49d284`→release, then `863e3d7` (0.7.16).
- **S10 ✓** keyed_map_slot dialect + shared `field_mapping` extraction — `5d80b1d` (0.7.17).
- **S11a ✓** structured_text json+toml codec + wired keyed_map_slot to it (unblocked codex mcp toml) — `4fa63b4` (0.7.18).
- **S11b ✓** whole-file structured_text dialect (codex whole-.toml agent; body-via-known_fields) — `a3abe95` (0.7.19, HEAD).
- Per-step audit reports in `docs/audits/code_audit_2026_06_08__{16_41,17_38,19_01,19_35}.md`.

### 3.4 Status — what is in progress

Nothing mid-edit. HEAD `a3abe95` is clean and pushed. Only untracked `docs/audits/` artifacts remain (intentionally not tracked). This restart-save commit stages ONLY `restart.md`.

### 3.5 Next concrete step

Run `/incremental_step` for **S12 — global-rules dialect** (`dialects/global_rules`). Whole-file rules (e.g. `AGENTS.md`/`CLAUDE.md`) with **`@import` resolution (cycle + escape fail-CLOSED)** and the **framework-specific hold-back (US-15)** — projection of framework-specific content is withheld via a read-phase flag. **At the detail step: read `docs/stories/US-15*.md` first** (this step realises a user story — confirm scope before coding; the private flag was already retired in amendment 019, so US-15 is the surviving framework-specific concern). Decide whether `@import` resolution belongs in the dialect (read-phase, per proposal §12) and whether the framework hold-back predicate needs a new `SurfaceFormat`/observation field. Consider splitting (S12a `@import` / S12b hold-back) if it can't pass the gate as one increment. Reference old `src/agents_sync/rules_io.py` for the `@import` behaviour the conformance suite preserves.

### 3.6 Open questions / decisions awaiting the user

None blocking. S12's scope (single increment vs split; whether US-15 needs a governance touch) is a detail-step decision — surface it to the user then.

## 4. Other tasks queued behind the active one

Per `docs/architecture_implementation_plan.md`, after S12:
- **S13** — mcp_server dialect specifics (per-tool MCP transport/auth field maps). medium.
- **S14–S16** — gateways (atomic_file_writer, canonical/state stores, archive+GC). medium.
- **S17–S19** — read phase (constructs SurfaceObservation/StoredCanonical inputs; resolves `@import`; the framework/secret projection predicates land here), secret_policy, execute_sync_plan (sole mint site). medium.
- **S20–S23** — tools-as-data + registry (the per-tool recipes/SurfaceFormats as DATA), runtime_config, daemon/CLI, portable_library. medium.
- **S24–S25** — cutover (wire daemon read→plan→execute; full conformance green; **parser_bounds size-explosion hardening MUST land here**) + retire old `src/` incl. legacy `formats/` (directory rename, LOC measurement). large.

## 5. Files touched this session (skim list)

Rebuild source (`src_new/agents_sync/`): `translation.py` [edited — dispatch + 3 dialects registered], `dialects/__init__.py` [created S9 — MalformedSurfaceError], `dialects/markdown_frontmatter.py` [created S9, refactored S10 to delegate], `dialects/field_mapping.py` [created S10 — shared fold/project; S11b doc-note], `dialects/keyed_map_slot.py` [created S10, S11a wired to codec], `dialects/structured_text.py` [created S11a codec, S11b added dialect], `domain_model/tool_surface.py` [grew SurfaceFormat recipe fields].
Rebuild tests (`tests_new/`): `test_translation.py`, `test_markdown_frontmatter.py`, `test_keyed_map_slot.py`, `test_structured_text.py` [all created/grown].
Design docs: `docs/architecture_simplification_proposal.md`, `docs/architecture_implementation_plan.md` [edited each step].
Old `src/` files [READ ONLY, reference]: `claude_io.py`, `markdown_yaml_metadata_block.py`, `field_names.py`, `shared_keyed_map_io.py`, `shared_keyed_map_formats.py`, `formats/json_format.py`, `formats/toml_format.py`, `codex_io.py`, `tool_specs/codex.py`.

## 6. Anything else the next session needs to know

- **Commit gate is `bash scripts/ci.sh`** (ruff + mypy src + mypy src_new + pytest tests/ + pytest -c pytest_new.ini). The pre-push hook also runs it. Fast iteration: `uv run pytest -c pytest_new.ini <files>`.
- **The audits genuinely catch real bugs every step** — don't treat them as rubber stamps. Examples this session: S9 caught a YAML-null→None crash in content_digest() and an empty-frontmatter fence leak; S10 caught that the toml fail-loud test couldn't distinguish ValueError from its MalformedSurfaceError subclass; S11a caught an alphabetically-ordered key-order assertion blind to a sort regression. Verify auditor P0/P1 findings by reproducing before fixing; push back on findings that are conscious justified decisions (Rule-of-Three not met, §-sanctioned co-location).
- **Ruff: PEP 695 `type X = ...`; lines ≤100; `uv run ruff format <file>` to wrap.** ruff rule families: E, F, I, W, UP, B (ARG not enabled, so an unused-but-signature-required param like structured_text.render's `prior_text` is fine — document it).
- 2026-06-08 (restart `save` note): user invoked /restart after S11b shipped (0.7.19), before S12. S12 is heavier (touches US-15, a user story). Four increments shipped this session (S9→S11b). Resume by reading US-15 then running `/incremental_step` for S12 under the audit-gated rhythm.
