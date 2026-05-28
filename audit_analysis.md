# v0.5 Branch — Code Quality Audit Analysis (Round 2)

**Branch:** `feat/v0.5-plan` (at commit `5ffe6d6`)
**Date:** 2026-05-28
**Method:** Eight parallel `code-quality-auditor` agents, each scoped to a distinct subsystem. The agent definition was rebuilt between Round 1 and Round 2 to introduce explicit **priority bands** (P0 / P1 / P2 / P3), a new **H-series honesty catalog** (LYING_NAME, HIDDEN_SIDE_EFFECTS, BROKEN_CONTRACT, ASYMMETRIC_ROUND_TRIP, HALF_FINISHED_REFACTOR), an explicit **D-series design-principle catalog** (POLA, KISS, YAGNI, DRY, SRP, SOC), and a deterministic security rule (HARDCODED_SECRET → P0 always; all other security findings → P2 always). Finding IDs follow the format `xxxx_CLASS_Px`.

The agent's overall objective: **the simplest and most efficient code that respects requirements.** Every finding ultimately measures the gap between the code and that yardstick.

## Audit Verdicts

| # | Subsystem | Verdict | Round 1 | Critical | Findings |
| - | --- | --- | --- | --- | --- |
| 1 | Core sync orchestration | **AUDIT_FAIL** | AUDIT_WEAK | 2 | 13 |
| 2 | CLI + config | **AUDIT_FAIL** | AUDIT_WEAK | 1 | 16 |
| 3 | Per-tool Markdown adapters | **AUDIT_FAIL** | AUDIT_WEAK | 1 | 25 |
| 4 | Shared parsing + rendering | AUDIT_WEAK | (n/a) | 1 | 20 |
| 5 | MCP server + formats + secrets | **AUDIT_FAIL** | AUDIT_FAIL | 2 | 12 |
| 6 | Adoption subsystem | **AUDIT_FAIL** | AUDIT_WEAK | 2 | 21 |
| 7 | Discovery + tool_specs | **AUDIT_FAIL** | AUDIT_WEAK | 1 | 15 |
| 8 | Filesystem + archive + scripts | AUDIT_WEAK | AUDIT_WEAK | 0 | 11 |

**Aggregate: 10 P0-CRITICAL findings, ~133 total findings, 6 of 8 subsystems AUDIT_FAIL.**

The verdict shift (1/6 → 6/8) is **not regression in the codebase** — it is the new catalog correctly naming defects that Round 1 filed as mere structural smells. Round 1's "M8 Divergent Change" on `validate_config` is now `HIDDEN_SIDE_EFFECTS` (a lie). Round 1's "partial-failure idempotence gap" in adoption is now `BROKEN_CONTRACT` (the orchestration class promises unit-of-work semantics it doesn't deliver). The codebase is the same; the audit is sharper.

## What v0.5 Actually Fixed (the wins)

- ✓ `pyproject.toml` correctly pinned to `0.5.0` (was `0.4.3` on the v0.5 branch)
- ✓ v0.4→v0.5 migration script now has snapshot+rollback infrastructure (was non-atomic with no rollback)
- ✓ MCP secret-policy default value (`parse_mcp_server_json` / `render_mcp_server_json`) — now `secrets_refused`, not the deprecated `'refuse'`
- ✓ `_is_secret_literal` now walks the full path (was top-level-only `path[0] == 'env'` while `_is_secret_header_path` walked any depth)

## What v0.5 Did NOT Fix (most of the previous P0s)

The previous audit's `validate_config` HIDDEN_SIDE_EFFECTS finding, the `AgentsSyncConfig` TypedDict abandonment, the dual `storage`/`file_layout` representation in `CustomizationTypeIO`, the adoption partial-failure idempotence gaps, the `markdown_yaml_metadata_block` half-finished migration, the `apply_mcp_secret_policy` permanently-empty redactions list, the case-sensitive `env:` regex — **all unchanged**.

---

## P0 — Code Honesty + Catastrophic Antipatterns

Read these first. Every P0 finding is a defect where the code's name, signature, docstring, or contract promises one thing and the body does another — or where the impact is catastrophic.

### P0-CRITICAL

| ID | Subsystem | File | Class | Defect |
| - | - | - | - | - |
| `0001_HIDDEN_SIDE_EFFECTS_P0` | Core sync | `config.py:368` (via `sync.py:99`) | HIDDEN_SIDE_EFFECTS | `validate_config` named like a pure validator with docstring "Structural validation only". Body mutates input dict (rewrites `secret_policy`), creates a directory on disk, probes FS permissions. Called by `Syncer.sync_once` on **every poll**, so mkdir+probe fire every tick. Three side effects, zero acknowledged in the name. |
| `0002_BROKEN_CONTRACT_P0` | Core sync | `sync.py:55` | BROKEN_CONTRACT | `SyncResult` is `@dataclass(frozen=True)` with custom `__eq__` that falls through to `super().__eq__(other)` — which is `object.__eq__` (identity). Two `SyncResult(changed=1)` instances **no longer compare equal**. Defining `__eq__` silently disables auto-`__hash__` → "frozen" dataclass is unhashable. |
| `0003_HIDDEN_SIDE_EFFECTS_P0` | CLI + config | `config.py:368` | HIDDEN_SIDE_EFFECTS | Same defect as `0001` — listed in two subsystems because both the orchestration layer and the config layer share responsibility. v0.5 did not fix the previous audit finding. |
| `0004_BROKEN_CONTRACT_P0` | Adoption | `adoption/adopter.py:52` (`_adopt_from_agentic_tool`) | BROKEN_CONTRACT | Rewrites source file with `pair_id` injected (line 80-84) **before** `save_canonical` (line 86) and `update_state_n_way` (line 99). Crash between lines 84-99 → source has pair_id on disk, no state entry. Next poll re-enters adopt with `pair_id_present=True` and no state record. `AdoptionEngine`'s docstring calls it an "orchestrator" with per-pair operations; there is no unit-of-work. |
| `0005_BROKEN_CONTRACT_P0` | Adoption | `adoption/removal_propagator.py:65` | BROKEN_CONTRACT | `_propagate_removal` returns False on first survivor failure, leaving partial disk state and untouched state dict. Next poll reclassifies the gone-from-disk survivors as `missing_from_state` and retries indefinitely. |
| `0006_HALF_FINISHED_REFACTOR_P0` | Discovery + tool_specs | `agentic_tool_spec.py:184` | HALF_FINISHED_REFACTOR | `CustomizationTypeIO` has dual `storage: str` + `file_layout: FileLayout \| None` representation. `__post_init__` mutates a `@dataclass(frozen=True)` via `object.__setattr__` to reconcile them. `rendering.py` alternately reads `io.storage == "single_file"` and `isinstance(io.file_layout, SharedKeyedMapLayout)` in the same function. |
| `0007_ASYMMETRIC_ROUND_TRIP_P0` | Per-tool adapters | `copilot_io.py:374` (and `opencode_io.py:327`) | ASYMMETRIC_ROUND_TRIP | `render_copilot_skill_md` applies `copilot_skill_slug(name)` on write; `parse_copilot_skill_md` reads `name` verbatim on read. `parse(render(canonical))` silently rewrites `name` on every save. The canonical `name` is the cross-tool identity — destruction propagates. |
| `0008_BROKEN_CONTRACT_P0` | Shared parsing | `markdown_yaml_metadata_block.py:165` | BROKEN_CONTRACT | `frontmatter_for_render` docstring promises empty-mapping fallback "if the prior frontmatter is unparseable or not a mapping". Body handles not-a-mapping but `yaml_load(raw)` has no try/except — unparseable YAML propagates. Every `render_rules_md` call relies on a safety net that doesn't exist. |
| `0009_LYING_NAME_P0` | MCP / secrets | `mcp_secret_policy.py:227` | LYING_NAME | `apply_mcp_secret_policy` signature declares `-> tuple[dict, list[dict[str, Any]]]`. Every reachable return emits `[]` for the second tuple element (redact mode was removed in the 2026-05-22 rewrite). Permanently-empty list dressed up as a populated type. Load-bearing dishonesty inside a security boundary. |
| `0010_DEAD_CODE_P0` | MCP / secrets | `mcp_server_io/parse.py:55` | DEAD_CODE | `if redactions: canonical['secret_redactions'] = redactions` branch is unreachable because `apply_mcp_secret_policy` always returns `[]` (see `0009`). Promoted from P3 to P0 because the dead branch sits inside the security boundary — a reader who edits it will reasonably assume it IS the redaction path. The dead code is a trap. Previous audit flagged this; unfixed. |

### P0-MAJOR (selected — 12 in total across all subsystems)

| ID | Subsystem | File | Class | Defect |
| - | - | - | - | - |
| `0011_HALF_FINISHED_REFACTOR_P0` | CLI + config | `config.py:16` | HALF_FINISHED_REFACTOR | `AgentsSyncConfig` TypedDict declared with 47 fields; **zero callers in src/**. Every consumer uses `dict[str, Any]`. The schema is orphaned. |
| `0012_HALF_FINISHED_REFACTOR_P0` | CLI + config | `cli.py:254` + 7 sites | HALF_FINISHED_REFACTOR | `--mcp-server-secret-policy` deprecation shim lives in **8 sites** documented "to be removed in v0.6" but no test or CI guard enforces removal. `merged_config` pops the key, then 6 downstream sites still defensively probe for it. |
| `0013_BROKEN_CONTRACT_P0` | CLI + config | `cli.py:324` (`_run_export`/`_run_import`) | BROKEN_CONTRACT | Annotates `config: dict` and uses the same defensive `secret_policy or mcp_server_secret_policy or 'secrets_refused'` chain that `merged_config + validate_config` already eliminated. **Sibling functions in the same file don't trust the validator's contract.** |
| `0014_HALF_FINISHED_REFACTOR_P0` | Per-tool adapters | three modules | HALF_FINISHED_REFACTOR | `markdown_yaml_metadata_block.py` shared surface exists, 4/7 adapters use it, 3 don't (cursor / gemini_cli / codex). Cursor & Gemini import the lower-level helpers and re-wrap them in private clones — paying migration cost without inheriting the SEC-C-01 `enforce_frontmatter_window` bound. Module docstring still says "four Markdown-based adapters"; there are seven. |
| `0015_LYING_NAME_P0` | Per-tool adapters | `cursor_io.py:375` + 5 other functions | LYING_NAME | `render_cursor_command_md(canonical, prior_text=None)` — first line is `del prior_text`. Six `parse_X` functions across cursor_io / gemini_cli_io accept `artifact_path`/`artifact_root` keyword-only then `del` them. Inverse defect in `render_codex_skill_md` — doesn't accept `prior_text` at all, missing comment/ordering preservation. |
| `0016_HALF_FINISHED_REFACTOR_P0` | Per-tool adapters | `cursor_io.py:21`, `gemini_cli_io.py:21` | HALF_FINISHED_REFACTOR | `extract_pair_id_from_md` lives in the shared module but cursor_io and gemini_cli_io import it from `claude_io` (transitive re-export). `antigravity_io` re-exports it via `__all__`. Three import paths for one symbol. |
| `0017_LYING_NAME_P0` | Core sync | `sync.py:47-53` | LYING_NAME | `SyncResult.__bool__` returns `changed != 0` — a poll with `changed=0, failed=['a','b','c']` is **falsy**. `SyncResult.__int__` returns `changed`, silently discarding the failed and blocked lists. Three back-compat dunders openly admitted as "legacy callers". |
| `0018_HIDDEN_SIDE_EFFECTS_P0` | Adoption | `privacy_gate.py:27` + `conflict_resolver.py:64` | HIDDEN_SIDE_EFFECTS | `_target_is_private` and `_winner_is_private` named as predicates; bodies perform FS reads, adapter parsing, and silent fail-closed reclassification. `_winner_is_private` parses winner bytes; `_sync_from_agentic_tool` immediately re-parses the same bytes. |
| `0019_ASYMMETRIC_ROUND_TRIP_P0` | Adoption | `privacy_gate.py:56` | ASYMMETRIC_ROUND_TRIP | Three call sites parse with **two different** `prior_canonical` values: privacy_gate uses `None`, sync path uses `load_canonical(...)`, conflict-resolver uses `load_canonical(...)`. Privacy gate inspects a different canonical than the projection produces. |
| `0020_BROKEN_CONTRACT_P0` | Discovery + tool_specs | `agentic_tool_spec.py:215` | BROKEN_CONTRACT | `@dataclass(frozen=True)` mutated via `object.__setattr__` in `__post_init__`. Hash and equality compute over fields that get rewritten post-construction. Frozen is a label, not a behavior. |
| `0021_BROKEN_CONTRACT_P0` | Discovery + tool_specs | `discovery/enumerator.py:202` | BROKEN_CONTRACT | TOCTOU across `read_artifact_text` → `sha256_file` → `path.stat().st_mtime` in `_add_agentic_tool_artifact`. The "info describes one snapshot" contract is violated three ways: text and digest can refer to different bytes; mtime can advance past the bytes that were hashed. |
| `0022_LYING_NAME_P0` | Shared parsing | `slash_command_io.py:186` | LYING_NAME | `render_slash_command_markdown(canonical, prior_text=None, ...)` body never references `prior_text`. The sibling `render_rules_md` *does* use it via `frontmatter_for_render(prior_text)`. Two near-identical APIs one module apart — one preserves user comments, one strips them. |
| `0023_HALF_FINISHED_REFACTOR_P0` | Shared parsing | `markdown_yaml_metadata_block.py:1` | HALF_FINISHED_REFACTOR | Module docstring brags about eliminating cross-adapter private imports — and `slash_command_io.py:20` does exactly `from agents_sync.codex_io import _normalize_toml_text`. Three independent BOM-strip implementations (markdown_yaml_metadata_block, codex_io, jsonc_tokenizer) with already-drifted constant forms. Victory-lap docstring for an unfinished refactor. |
| `0024_BROKEN_CONTRACT_P0` | Shared parsing | `parser_bounds.py:5` | BROKEN_CONTRACT | Documents "**Every** parser entry point validates `len(text) <= MAX_PARSE_BYTES`" — but `extract_pair_id_from_md` and `frontmatter_for_render` in the same shared module skip the bound. A 2 GB hostile Markdown file in `$HOME` reaches the regex engine with full linear scan. The lie is the word "Every". |
| `0025_BROKEN_CONTRACT_P0` | Filesystem + scripts | `scripts/migrate_v0.4.py:392` | BROKEN_CONTRACT | `rollback_migration` docstring claims "all-or-nothing" but `_restore_path` does `_remove_path(target)` *then* `copytree(snapshot, target)`. Crash between leaves the live tree gone with only the backup. Downgraded from CRITICAL because backup is retained, but the docstring still lies. |

---

## P1 — Design Principles

POLA, KISS, YAGNI, DRY, SRP, SOC violations, plus cross-file structural smells (FEATURE_ENVY, SHOTGUN_SURGERY, CYCLIC_DEPENDENCIES, GLOBAL_MUTABLE_STATE, DIVERGENT_CHANGE). These predict whether the codebase compounds or rots.

### POLA — Principle of Least Astonishment (5 findings)

- **CLI + config**: `redact → secrets_refused` silent remap in `_OLD_POLICY_VALUE_MAP` — the value name still says `redact` but the runtime semantics are now refusal, with no specific deprecation notice.
- **Adoption**: `_extend_to_new_tools` source_dir picked by dict iteration order — two polls on same disk state can pick different source_dirs.
- **Discovery + tool_specs**: `secret_policy()` implemented **verbatim twice** (`_mcp_server_factory.py:32-44` + `cursor.py:36-43`); cursor bypasses the factory for no expressed reason, the explanatory comment exists only on the factory copy.
- **Discovery + tool_specs**: `parse_agent` signature uniform across 5 tools; 4 of 5 drop `artifact_path`, 1 forwards it. Caller has no way to predict which.
- **Per-tool adapters**: 8 functions across the `parse_X` family implement **4 mutually-incompatible name-resolution precedence orders** (path-wins / frontmatter-wins / canonical>path>frontmatter / path-wins-raise-if-absent).
- **Shared parsing**: `expected_pair_id=str(pair_id) if pair_id else None` silently disables defense-in-depth pair_id collision check on empty strings.
- **Filesystem + scripts**: `MigrationFileLock` uses `O_CREAT|O_EXCL` with no liveness check on the embedded pid — a crashed prior migration leaves a stale lock forever; every subsequent installer exits 2 with "another migration appears to be running".
- **Filesystem + scripts**: `detect_pre_v04_fix_state` matches `.agents/skills` substring, which collides with OpenCode's legitimate skills root.

### KISS — Unnecessary Complexity (4 findings)

- **Adoption**: `AdoptionEngine` is a 685-line God Class spread across 5 mixin files. Each mixin reaches into `self.config`, `self.agentic_tools`, `self.state_dir`, `self.tool_status` and into ~12 cross-mixin private methods. Decomposition is cosmetic — recomposes into a God Class via MRO.
- **Discovery + tool_specs**: `DiscoveryWalker` is the same anti-pattern across 4 files (~685 lines combined, 3 mixins sharing private state and calling each other's private methods).
- **Filesystem + scripts**: `portable_archive.py` is 747 lines; `import_from_zip` is 200 lines with CC=18 across 3 documented phases (Stage / Promote / Project).
- **Per-tool adapters**: Hand-rolled TOML emitter in `codex_io.py:76-148` (72 lines) abuses `json.dumps` for string escaping where `tomli_w` exists in the ecosystem.

### YAGNI — Speculative Configurability (3 findings)

- **CLI + config**: `CodexField`, `OpencodeField`, `adapter_field_name()`, and `CROSS_ADAPTER_FIELD_MAP` declared in `field_names.py` with zero callers anywhere in src/ or tests/. Module docstring openly confesses: "the adapters still perform their own conversion (we don't yet have a generic rename keys pass)".
- **MCP / secrets**: `ALLOWED_MCP_SECRET_POLICIES` and `validate_mcp_secret_policy` exported with zero internal callers.
- **Per-tool adapters**: Six `parse_X` functions accept `artifact_root` then immediately `del` it.

### DRY — Repetition with Drift Risk (8 findings)

- **CLI + config**: Adding one new tool flag requires shotgun edits across **7 sites** (`build_parser`, `_ARG_TO_CONFIG_KEY`, `platform_defaults`, three required/optional tuples, `AgentsSyncConfig`).
- **Per-tool adapters**: `_set_or_pop` exists in 3 modules with **two incompatible empty-list policies** (Cursor preserves `[]`, Copilot/Gemini strip it). `tools=[]` in canonical produces different on-disk shapes per tool.
- **Per-tool adapters**: `copilot_skill_slug` and `opencode_skill_slug` 90% byte-identical with one drift point.
- **Per-tool adapters**: Parallel `FOREIGN_AGENT_FIELDS` denylists in gemini_cli_io and opencode_io with 8-field overlap and already-divergent edges.
- **Per-tool adapters**: `_yaml_dump`, `_split_frontmatter`, `_frontmatter_for_render` cloned across 3 modules.
- **Discovery + tool_specs**: 5 of 7 tool_spec files duplicate `parse_*`/`render_*` thunks (~250 lines). Observable drift: opencode forwards `artifact_path`; the other four drop it.
- **Shared parsing**: Three independent BOM-strip implementations (markdown_yaml_metadata_block, codex_io, jsonc_tokenizer) with already-drifted constant forms.
- **Filesystem + scripts**: Install scripts duplicate the default-config TOML across `install.sh` / `install-macos.sh` / `install.ps1`. install.ps1 carries Antigravity v1.19.6 + opencode advisories absent from the bash variants (observed drift).
- **Filesystem + scripts**: `archive_copy` not wrapped in `retry_fs` while `archive_move` is — asymmetric AV-retry defense.

### SRP — Single Responsibility Violation (3 findings)

- **Core sync**: `Syncer` carries the poll loop + a 60%-by-line first-boot multi-tool reconcile/merge cluster — at least 4 reasons to change.
- **CLI + config**: `config.py` has 5 unrelated responsibility clusters (TypedDict schema, platform defaults, argparse mapping, merge+deprecation, validation+provisioning).
- **Discovery + tool_specs**: `tool_status._probe_tool_roots` is 58 lines, CC=14, with the same 4-line failure-arm pattern duplicated 5 times.

### SOC — Separation of Concerns (2 findings)

- **CLI + config**: `cli.py::main` is the documented entry point but also library-importable; calls `logging.basicConfig` globally, mixing presentation/policy with business orchestration.
- **Adoption**: `PrivacyGateMixin` mixes 4 layers (filesystem IO, adapter parsing, policy classification, logging policy) in two methods. A parse-regression in any adapter looks identical to a user marking content as private.

### Cross-file structural smells (5 findings)

- **Shared parsing**: `parser_bounds ↔ markdown_yaml_metadata_block` cyclic dependency broken only by lazy imports with in-code comments admitting the cycle.
- **MCP / secrets**: `_PERMISSIVE_WARNING_CACHE` module-level mutable state mutated by `apply_mcp_secret_policy` and cleared by `Syncer.sync_once` every poll. Two concurrent Syncer instances would clobber each other.
- **Shared parsing**: `_FORMAT_REGISTRY` module-level mutable dict with documented "last writer wins" override semantics. Test isolation hazard.
- **Adoption**: `_pick_winner` lives in `AdopterMixin` but is called from `ConflictResolverMixin` (FEATURE_ENVY).
- **Shared parsing**: `slash_command_io` imports the private `_normalize_toml_text` from `codex_io` — exactly the anti-pattern the shared module's docstring claims was eliminated (INAPPROPRIATE_INTIMACY).

---

## P2 — Structural Metrics + Non-HARDCODED_SECRET Security

### GOD_MODULE / GOD_CLASS / LONG_FUNCTION (selected)

- `portable_archive.py` — 747 lines, 5 responsibility clusters, `import_from_zip` 200 lines / CC=18
- `copilot_io.py` — 538 lines, 4 full parse/render pairs (agent/skill/instruction/prompt) with their own field sets
- `cursor_io.py` — 460 lines, 5 artifact kinds in one file
- `mcp_secret_policy.py` — 410 lines, 4 unrelated concerns
- `config.py` — 441 lines, 5 unrelated concerns
- `cli.py::build_parser` — 273 lines, 38 `add_argument` calls (CC=1, purely repetitive)
- `Syncer.sync_once` — 54 lines, 2 nested try/except loops
- `_probe_tool_roots` — 58 lines, CC=14
- `apply_slot` — 64 lines, 4 responsibilities (lock + RMW + pair_id check + exception translation)

### Security (P2 by deterministic rule — `HARDCODED_SECRET` would be P0)

- **MCP / secrets**: Case-sensitive `env:` regex in `_ENV_REFERENCE_TOKEN_RE`/`ENV_REFERENCE_RE` — `${ENV:GITHUB_TOKEN}` (uppercase) is classified as a literal secret false-positive. Unfixed from previous audit. Severity MAJOR (band still P2).
- **Discovery + tool_specs**: `Path.rglob` follows symlinks by default with no cycle guard. A symlink loop in `~/.claude/commands/` causes unbounded walk. The relevant boundary is user-owned filesystem, not adversary-controlled — hence WARNING.
- **Adoption**: `_target_is_private` catches `(OSError, UnicodeDecodeError, ValueError, KeyError)` — broad enough to mask adapter parser refactor errors that silently reclassify real content as private (SILENT_SWALLOWING-adjacent, fail-closed-by-design).

### PRIMITIVE_OBSESSION

- `dict[str, Any]` config plumbed through `Syncer`, `CLI`, `merged_config`, `validate_config`, every adapter — despite `AgentsSyncConfig` TypedDict declared in the same file
- 14-key canonical dict + 9 helpers in `canonical.py` — primitive obsession across the central data model
- `storage` string-as-enum (`"single_file"`, `"directory_skill"`, `"shared_keyed_map"`) leaks across ~9 call sites
- 50+ raw field-name strings across copilot_io, cursor_io, gemini_cli_io, opencode_io constants — `field_names.CanonicalField` / `ClaudeField` enums stopped at Claude

### DATA_CLUMPS

- `_decide_collision` takes 7 keyword params (3 imported-side + 3 local-side + strategy)
- `render_to_agentic_tool` 9 params — 4 of them are "prior render state" that travel together
- `apply_slot` 6 params with pair-id ownership clump

---

## P3 — Style and Hygiene (summary only)

- `secret_redactions` is referenced in 3 places, never written — pure dead-cleanup trap (was P3 in previous round, **promoted to P0 this round** because it sits inside the security boundary)
- `archive_file = archive_copy` alias with zero callers
- Magic strings: `"converted"` slug fallback, `.json` extension fallback in archive paths, `999` restart count in install.ps1, hardcoded counts `2`/`9` in integration_tests.sh
- Lazy imports inside function bodies (`state._monotonic_ms`, all 7 tool_spec builders)
- Untyped `Any` parameters where concrete types exist
- Two redundant BOM-stripping helpers, neither covers UTF-16
- TOML format error message hardcodes "JSON" — confuses TOML users
- BOM literal written as invisible U+FEFF in source rather than `﻿` escape

---

## Cross-cutting themes

1. **Half-finished refactors dominate.** The single most damaging pattern is: extract a shared surface, migrate some callers, ship. The unmigrated callers then drift, and the drift produces real correctness defects (`_set_or_pop` empty-list policy split; `parse_X_agent_md` name-resolution split; `CustomizationTypeIO` dual representation).

2. **"Validation" functions consistently lie.** `validate_config` mutates and does FS I/O. `validate_mcp_secret_policy` normalizes and logs deprecation warnings. The `validate_*` prefix is the project's most reliable indicator that side effects are about to fire.

3. **Mixin-cosmetic decomposition recreates God Classes via MRO.** Two subsystems (`AdoptionEngine`, `DiscoveryWalker`) use 3-5 mixin files to keep per-file line counts under threshold; both reconstruct ~685-line God Classes via shared `self.*` state and cross-mixin private-method calls. The decomposition fools static analysis but not maintainers.

4. **Round-trip asymmetries silently rewrite user data.** Skill-slug applied on render but not parse. `_set_or_pop` empty-list policy diverges. TOML slash-command keys over-accept (`argument-hint` and `argument_hint`) and under-emit (only `argument_hint`). Every save rewrites the user's chosen style.

5. **Deprecation shims without removal milestones become permanent.** `--mcp-server-secret-policy` lives in 8 sites with "remove in v0.6" comments and no failing test enforcing v0.6. `ALLOWED_MCP_SECRET_POLICIES` and `validate_mcp_secret_policy` exported with zero internal callers. `SyncResult`'s three back-compat dunders.

6. **The orchestration layer trusts no one — and rightly so.** `_run_export` defensively re-reads `secret_policy or mcp_server_secret_policy or 'secrets_refused'` even after `merged_config + validate_config` have normalized the value. Sibling functions in the same file don't trust the validator's contract — because the validator has been observed to lie before.

7. **Partial-failure recovery is wishful.** Adoption rewrites source-on-disk before persisting state; removal-propagator returns False mid-loop with partial disk state; migration rollback removes-then-copies (non-atomic); `_propagate_removal` and `propagate_orphan_state` have divergent state mutation semantics. A crash anywhere in the middle of the poll leaves the world in an unrecoverable mixed state — recoverable only by the user, only because backup directories are retained.

---

## Suggested release strategy

1. **Block v0.5 tag on the 10 P0-CRITICAL findings.** They are user-observable defects or security-boundary lies.
2. **`validate_config` (`0001`/`0003`) is the highest-leverage single fix** — it cascades into the entire orchestration layer, fixes the "every poll fires three side effects" smell, and removes the contract-distrust that drives `0013`.
3. **`SyncResult` (`0002`/`0017`) — delete the back-compat dunders.** Daemon is the only in-tree consumer and uses the fields directly. The dunders serve no caller and break the type's own equality and hashability.
4. **MCP secret-policy redactions (`0009`/`0010`) — finish the rewrite.** The signature lies and the consumer is dead. Either restore redaction (unlikely — explicitly removed by NFR-15) or drop the second tuple element entirely.
5. **`CustomizationTypeIO` dual representation (`0006`/`0020`) — pick one grammar.** Mutating a frozen dataclass via `object.__setattr__` is too clever and too dishonest.
6. **Adoption transactions (`0004`/`0005`) — accept that they aren't transactional and rename `AdoptionEngine`** to something that doesn't imply unit-of-work, OR refactor to two-phase commit with documented rollback. Either is honest.
7. **The shared-surface migrations (`0014`/`0016`/`0023`)** — finish them. Three adapters and one BOM-stripper migration would close ~12 findings in one pass.
8. **P1 and P2** ride v0.6.

The audit ran with the upgraded `code-quality-auditor` (priority bands, full-word class names, deterministic security rule, `xxxx_CLASS_Px` IDs). Findings are sorted by priority then severity; the first finding in each subsystem's array is the single worst defect for that scope.
