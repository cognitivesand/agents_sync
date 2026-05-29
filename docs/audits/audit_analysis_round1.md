# v0.5 Branch — Code Quality Audit Analysis

**Branch:** `feat/v0.5-plan`
**Date:** 2026-05-28
**Method:** Six parallel `code-quality-auditor` agents, each scoped to a distinct subsystem. Findings consolidated, deduplicated, and prioritized below.

## Audit Verdicts

| # | Subsystem                              | Verdict        | Critical | Findings |
| - | -------------------------------------- | -------------- | -------- | -------- |
| 1 | Core sync / state / CLI                | AUDIT_WEAK     | 0        | 22       |
| 2 | Per-tool IO adapters                   | AUDIT_WEAK     | 0        | 20       |
| 3 | MCP server + formats + parsing         | **AUDIT_FAIL** | 4        | 21       |
| 4 | Adoption subsystem                     | AUDIT_WEAK     | 0        | 16       |
| 5 | Discovery + tool_specs                 | AUDIT_WEAK     | 0        | 23       |
| 6 | Filesystem + archive + scripts         | AUDIT_WEAK     | 0        | 23       |

**Aggregate: 4 CRITICAL, ~125 findings.** Security posture is sound (no hardcoded secrets, no injection vectors, careful atomic writes with fsync+quarantine, UUIDv4-validated archive entry names). The four CRITICAL findings cluster in the secret-policy gate where false-positive/false-negative cracks crept in. The dominant structural theme across the codebase is **half-finished refactors**: shared surfaces were extracted but only adopted by some call-sites, leaving observable schema drift in the divergent copies.

Audit reference format: `<subsystem>/CQ-NN`.

---

## P0 — Blockers (must fix before tagging v0.5)

| #     | Issue                                                                                                                                                                                                                                                                                                       | Files                                              | Refs              |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- | ----------------- |
| P0-1  | **`parse_mcp_server_json` / `render_mcp_server_json` default `secret_policy='refuse'` is the deprecated v0.5-pre-hardening spelling.** Every public-API call trips a DEPRECATION warning; can lock users out of rendering canonicals they ingested under `secrets_accepted`.                                | `mcp_server_io/parse.py:44`, `render.py:27`        | 5/CQ-01, 5/CQ-02  |
| P0-2  | **Case-sensitive `env:` regex misses uppercase form.** `${ENV:GITHUB_TOKEN}` classified as literal secret while bearer-regex companion uses `IGNORECASE` — silent false-positive at the security boundary.                                                                                                  | `mcp_secret_policy.py:33-40`                       | 5/CQ-03           |
| P0-3  | **Path-anchored env-secret check is top-level only**, while `_is_secret_header_path` walks any depth — nested env secrets escape detection.                                                                                                                                                                 | `mcp_secret_policy.py:328-331`                     | 5/CQ-04           |
| P0-4  | **`pyproject.toml` still pins `version = "0.4.3"`** on the v0.5 branch — every portable archive exported from this branch will lie about its origin in the manifest.                                                                                                                                        | `pyproject.toml:3`                                 | 6/CQ-21           |
| P0-5  | **v0.4→v0.5 migration script is non-atomic with no rollback.** If phase 5 ("strip pair_id frontmatter") succeeds and phase 6 ("wipe state") fails, frontmatter-stripped SKILL.md files reference an un-wiped state.json — unrecoverable without the backup directory.                                       | `scripts/migrate_v0.4.py:336`                      | 6/CQ-09           |
| P0-6  | **`detect_pre_v04_fix_state` triggers destructive migration on any transient `OSError`** (lock contention, AV scanner). A second `install.sh` run could trigger two concurrent migrations.                                                                                                                  | `scripts/migrate_v0.4.py:78`                       | 6/CQ-10           |

---

## P1 — Major structural debt (fix before v0.5)

### Half-finished refactors (the dominant theme)

| #     | Issue                                                                                                                                                                                                                                                                                                                                                                | Files                                                                       | Refs              |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ----------------- |
| P1-1  | **`markdown_yaml_metadata_block.py` extraction abandoned mid-refactor** — 4/9 adapters use it; cursor/copilot/gemini_cli each maintain private clones of 7+ helpers. Drift is already observable: `_set_or_pop` has two different empty-list policies (Cursor strips on `None`/`""`; Copilot/Gemini also strip on `[]`). Same canonical produces different frontmatter per tool. | `cursor_io.py:80-147`, `copilot_io.py:106-181`, `gemini_cli_io.py:113-193`  | 2/CQ-01, 2/CQ-02  |
| P1-2  | **Inconsistent name-resolution across 5 `parse_X_agent_md` functions** — 4 different precedence orders (cursor "path wins", copilot "frontmatter wins", opencode "path > prior > frontmatter, raise on empty", rules "override > path > frontmatter"). Renaming a Cursor file loses frontmatter name; same rename in Copilot doesn't.                                | five `*_io.py` files                                                        | 2/CQ-03           |
| P1-3  | **`AgentsSyncConfig` TypedDict declared in `config.py` then abandoned** — sync/cli/adapters all use `dict[str, Any]` with stringly-typed lookups. Two adapters annotate `config: dict` with no parameter type at all.                                                                                                                                                | `config.py:16-77`, callers everywhere                                       | 1/CQ-07, 1/CQ-12  |
| P1-4  | **`CustomizationTypeIO.storage`/`file_suffix` dual-representation** — legacy fields and `file_layout` both exist; `__post_init__` mutates a frozen dataclass to reconcile them. Half the tool_specs use the legacy form, half use `file_layout`.                                                                                                                     | `agentic_tool_spec.py:184-217`                                              | 6/CQ-05           |
| P1-5  | **`field_names.py` centralization only covers half the tools** — Copilot/Cursor/Gemini-CLI/Antigravity field names are raw string literals; hyphen-vs-snake mappings duplicated by literal in slash_command_io and copilot_io. ~30 magic strings should live in `field_names.py`.                                                                                    | `slash_command_io.py`, `copilot_io.py`                                      | 2/CQ-10           |

### God modules / shotgun surgery

| #      | Issue                                                                                                                                                                                                                                                  | Files                                | Refs              |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------ | ----------------- |
| P1-6   | **`config.py::validate_config` is a mutating "validator"** — mutates input dict (rewrites `secret_policy`), creates directories, probes FS permissions. Called by `Syncer.__init__` AND `sync_once`, so directory-creation side-effect fires on every poll. | `config.py:368-441`                  | 1/CQ-03           |
| P1-7   | **`cli.py::build_parser` is 273 lines of mechanical `add_argument` repetition** (38 calls, CC=1).                                                                                                                                                       | `cli.py:35-307`                      | 1/CQ-01           |
| P1-8   | **Shotgun surgery: adding one tool flag needs edits in 5 places** (`build_parser`, `_ARG_TO_CONFIG_KEY`, `platform_defaults`, required/optional tuples, `AgentsSyncConfig` TypedDict).                                                                  | `cli.py` + `config.py`               | 1/CQ-02           |
| P1-9   | **`config.py` is a God Module** (441 lines, 6 unrelated responsibility clusters).                                                                                                                                                                       | `config.py`                          | 1/CQ-09           |
| P1-10  | **`portable_archive.py` is a 748-line God Module** with `import_from_zip` at 200 lines (CC=18) bundling secret-filter + 3-phase transaction + projection.                                                                                                | `portable_archive.py`                | 3/CQ-01, 3/CQ-02  |
| P1-11  | **`mcp_secret_policy.py` is a 406-line module with 4 concerns** (policy normalization, env-regex, secret-finding, leak exception).                                                                                                                      | `mcp_secret_policy.py`               | 5/CQ-07           |
| P1-12  | **~250 lines of copy-paste across 7 tool_spec files** — agent/skill/slash_command thunks. `_rules_factory` and `_mcp_server_factory` prove the pattern works but were never extended to the other 3 kinds.                                              | `tool_specs/*.py`                    | 6/CQ-04           |
| P1-13  | **Default-config TOML duplicated across `install.sh` / `install-macos.sh` / `install.ps1`** with already-visible drift (Antigravity v1.19.6 caveat only in install.ps1).                                                                                | install scripts                      | 6/CQ-12           |
| P1-14  | **`rendering.py` mixes 5 concerns** (path identity, atomic staging, artifact IO, render dispatch, state digest).                                                                                                                                        | `rendering.py`                       | 5/CQ-19           |

### Mixin-reconstructed God Classes

| #      | Issue                                                                                                                                                                                                                                  | Files                | Refs    |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | ------- |
| P1-15  | **`AdoptionEngine` is a 685-line God Class spread across 5 mixin files** — each mixin reaches into `self.config`/`self.agentic_tools`/`self.state_dir` and into ~10 cross-mixin private methods. Decomposition is cosmetic.            | `adoption/*.py`      | 4/CQ-01 |
| P1-16  | **`DiscoveryWalker` is the same anti-pattern across 4 files** (~685 lines combined, 3 mixins sharing private state).                                                                                                                   | `discovery/*.py`     | 6/CQ-03 |

### Correctness gaps

| #      | Issue                                                                                                                                                                                                                                  | Files                                                  | Refs              |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | ----------------- |
| P1-17  | **`enumerator._enumerate_artifacts` uses `Path.rglob` with no symlink-loop protection and no depth bound** on `$HOME` config directories.                                                                                              | `discovery/enumerator.py:148`                          | 6/CQ-01           |
| P1-18  | **TOCTOU window across read/hash/stat** in `_add_agentic_tool_artifact` — three independent syscalls on the same path; `text`, `digest`, `mtime` can refer to different on-disk states.                                                | `discovery/enumerator.py:172-203`                      | 6/CQ-02           |
| P1-19  | **Adoption partial-failure idempotence gap** — `_propagate_removal` returns False on first failure leaving partial state mutations; `_adopt_from_agentic_tool` rewrites source with pair_id before projecting (mid-projection crash leaves state behind disk). | `adoption/removal_propagator.py`, `adopter.py`         | 4/CQ-04, 4/CQ-05  |
| P1-20  | **Collision blocker skips state-known pairs** — if a managed pair's path has drifted, the new pair is blocked as "collides with managed" but the drifted pair is never re-validated.                                                   | `discovery/collision_blocker.py:73`                    | 6/CQ-07           |
| P1-21  | **Extender source_dir selection is non-deterministic** — iterates `info.agentic_tools.items()` and breaks on first existing path. Stale-vs-canonical depends on caller insertion order.                                                | `adoption/extender.py:30`                              | 4/CQ-07           |
| P1-22  | **JSONC tokenizer silently consumes input past unterminated strings/block-comments** — no EOF check on `in_string`/`in_block_comment` state.                                                                                            | `formats/jsonc_tokenizer.py:35`                        | 5/CQ-14           |
| P1-23  | **Hand-rolled TOML serializer with no round-trip self-check** — duplicate copies in `codex_io._toml_dump` and `slash_command_io._toml_dump_top_level`; doesn't handle datetime/None.                                                    | `codex_io.py`, `slash_command_io.py`, `formats/toml_format.py` | 2/CQ-11, 5/CQ-16  |
| P1-24  | **`render_cursor_command_md` accepts `prior_text` then `del`s it** — every render rewrites from scratch, silently destroying any user-authored content.                                                                                 | `cursor_io.py:375`                                     | 2/CQ-06           |
| P1-25  | **Module-level `_PERMISSIVE_WARNING_CACHE` mutable global** — two concurrent Syncer instances share warning dedupe state; docstring openly acknowledges the smell.                                                                      | `mcp_secret_policy.py:62`                              | 5/CQ-06           |
| P1-26  | **Cyclic dependency `markdown_yaml_metadata_block ↔ parser_bounds`** broken only by lazy imports inside function bodies.                                                                                                                            | both files                                             | 5/CQ-09           |
| P1-27  | **`_secret_literal` classifier blends 5 disjoint heuristics in undocumented priority order** — no test pins precedence.                                                                                                                 | `mcp_secret_policy.py:319`                             | 5/CQ-08           |
| P1-28  | **Cross-tool denylists in gemini_cli and opencode** — each adapter must know every *other* adapter's field vocabulary. Already inconsistent.                                                                                            | `gemini_cli_io.py:77`, `opencode_io.py:67`             | 2/CQ-09           |
| P1-29  | **`ruamel.yaml >= 0.18` has no upper bound** — a future 0.20 with breaking API silently lands on `uv sync`.                                                                                                                             | `pyproject.toml:8`                                     | 6/CQ-22           |

---

## P2 — Warnings (fix when touching these files)

| #     | Issue                                                                                                                                                                              | Files                                              | Refs              |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- | ----------------- |
| P2-1  | `slash_command_io` imports private `_normalize_toml_text` from `codex_io` — Demeter violation.                                                                                     | `slash_command_io.py:20`                           | 2/CQ-07           |
| P2-2  | `cursor_io` / `gemini_cli_io` import `extract_pair_id_from_md` from `claude_io` (3-hop indirection through transitive re-export).                                                  | both                                               | 2/CQ-08           |
| P2-3  | `cursor_io` mcp_server cell bypasses `_mcp_server_factory` — duplicates `secret_policy` closure verbatim.                                                                          | `tool_specs/cursor.py:36-43`                       | 6/CQ-06, 6/CQ-14  |
| P2-4  | Privacy gate parses target with `prior_canonical=None` while sync path parses with prior — asymmetric parser context.                                                              | `adoption/privacy_gate.py:56`                      | 4/CQ-06           |
| P2-5  | Two separate removal entry points with divergent state semantics (`propagate_orphan_state` vs `_propagate_removal`).                                                              | `adoption/removal_propagator.py`                   | 4/CQ-15           |
| P2-6  | `archive_copy` not wrapped in `retry_fs` while `archive_move` is — asymmetric AV-retry defense.                                                                                    | `archive.py:76`                                    | 6/CQ-08           |
| P2-7  | `opencode._split_model_provider` truncates 2-slash model identifiers.                                                                                                              | `opencode_io.py:112`                               | 2/CQ-05           |
| P2-8  | `migrate_v0.4.move_skill_suffix_duplicates` uses `-skill` suffix as proxy for pair_id detection — relocates user-named legit directories.                                          | `scripts/migrate_v0.4.py:174`                      | 6/CQ-11           |
| P2-9  | systemd `ExecStart` and macOS launcher heredocs interpolate paths without `printf %q` quoting.                                                                                     | install scripts                                    | 6/CQ-13, 6/CQ-14  |
| P2-10 | `install.ps1` falls back to bare `wscript.exe` if `System32\wscript.exe` missing — defeats path hardening.                                                                          | `install.ps1:192`                                  | 6/CQ-16           |
| P2-11 | `install.ps1` VBS `On Error Resume Next` in `IsAlreadyRunning` — duplicate daemons on WMI error.                                                                                    | `install.ps1:54-117`                               | 6/CQ-17           |
| P2-12 | Daemon signal-registration failures logged at DEBUG (operator never sees SIGTERM-not-registered).                                                                                  | `daemon.py:37`                                     | 1/CQ-19           |
| P2-13 | `load_external_config` silently swallows unknown top-level TOML tables — mistyped `[agent-sync]` ignored.                                                                          | `config.py:215`                                    | 1/CQ-20           |
| P2-14 | Module-level `os.environ` reads at import time (`DEFAULTS`, `_LEGACY_PATHS`).                                                                                                      | `config.py:204`, `cli.py:22`                       | 1/CQ-10, 1/CQ-11  |
| P2-15 | Lexicographic-first source-of-truth selection in adoption planner — disagrees with stated mtime-tiebreaker policy.                                                                 | `discovery/adoption_planner.py:60`                 | 6/CQ-22           |
| P2-16 | Shared-keyed-map files re-parsed O(pairs × tools) per poll — no caching across pair iteration.                                                                                     | `discovery/adoption_planner.py:67`                 | 6/CQ-09           |
| P2-17 | `tool_status._probe_tool_roots` is 58 lines, CC≈14, mixes 3 responsibilities.                                                                                                      | `tool_status.py:139`                               | 6/CQ-10           |
| P2-18 | Case-insensitive filesystem collision (macOS/Windows) unverified — `Foo` vs `foo` slot keys may not casefold-collide.                                                              | `discovery/collision_blocker.py:110`               | 6/CQ-08           |
| P2-19 | Duplicate `_coerce_bool` in `copilot_io` and `rules_io`.                                                                                                                           | both                                               | 2/CQ-15           |
| P2-20 | Skill-slug applied to name on render but not parse (copilot, opencode) — `parse(render(canonical)) != canonical` for skills with non-kebab names.                                  | `copilot_io.py:374`, `opencode_io.py:327`          | 2/CQ-18           |
| P2-21 | Local `_split_frontmatter` clones bypass `parser_bounds.enforce_frontmatter_window` SEC-C-01 mitigation.                                                                           | cursor/copilot/gemini_cli `_io.py`                 | 2/CQ-16           |
| P2-22 | `_winner_is_private` reads+parses winner bytes; `_sync_from_agentic_tool` immediately re-reads+re-parses same bytes.                                                              | `adoption/conflict_resolver.py:64`                 | 4/CQ-12           |
| P2-23 | `_winner_is_private` doesn't wrap read/parse in fail-closed try/except — inconsistent with privacy_gate's own contract.                                                            | `adoption/conflict_resolver.py:64`                 | 4/CQ-13           |
| P2-24 | Extender silently returns False on missing canonical for a state-known pair — buries state-corruption invariant violation.                                                         | `adoption/extender.py:23`                          | 4/CQ-14           |
| P2-25 | `SyncResult` overrides `__eq__` without `__hash__` on a frozen dataclass — silently disables auto-hash. Plus three back-compat dunders openly admitted as legacy.                  | `sync.py:32`                                       | 1/CQ-06           |
| P2-26 | `validate_config` parallel tuples (`REQUIRED_DIR_KEYS`/`OPTIONAL_PATH_KEYS`/`OPTIONAL_BOOL_KEYS`) — no check that every key in DEFAULTS appears in exactly one.                     | `config.py:322`                                    | 1/CQ-22           |
| P2-27 | Integration test daemon-wait is `sleep 3` after `--interval 0.5` — flaky on CI.                                                                                                    | `scripts/integration_tests.sh:174`                 | 6/CQ-19           |
| P2-28 | Migration script preserves symlinks into backup via `shutil.copytree(..., symlinks=True)` — user-controlled skill dir can store symlinks to `/etc/passwd` in backup.                | `migrate_v0.4.py`                                  | 6/CQ-09 commentary |
| P2-29 | Render-side silent `except ValueError: pass` in `_render_transport_value` — intentional but undocumented.                                                                          | `mcp_server_io/render.py:160`                      | 5/CQ-11           |
| P2-30 | `_tool_only_spellings` + `known_slot_fields` co-changing tables with no compile-time link.                                                                                         | `mcp_server_io/parse.py:210,251`                   | 5/CQ-12, 5/CQ-13  |

---

## P3 — Cleanup (info, fix opportunistically)

- Dead `if redactions:` branch in `mcp_server_io/parse.py:55` — "redact" mode was removed but consumer code wasn't (5/CQ-05)
- `parse_mcp_server_json` has dead `artifact_root` parameter with explicit `del` (5/CQ-10)
- `_archive_prior_slot_results` magic `.json` extension fallback (4/CQ-10)
- `'skill'` / `'directory_skill'` magic-string comparisons (4/CQ-11, 6/CQ-12)
- Slugify magic strings `'converted'` / `'-item'` (1/CQ-21)
- State.py magic `NS_PER_MS = 1_000_000`, `SHA256_BLOCK_BYTES = 1024*1024` (1/CQ-18)
- Lazy imports inside function bodies (`state._monotonic_ms`, all tool_spec builders) (1/CQ-17, 6/CQ-13)
- Untyped `Any` parameters in `_archive_source_before_write` (4/CQ-16)
- `_decide_collision` takes 7 keyword params (data clump) (3/CQ-04)
- `_toml_scalar` raises `TypeError` without `from` clause or path context (5/CQ-17)
- Two redundant BOM-stripping helpers, neither covers UTF-16 (5/CQ-15)
- `apply_slot` has 6 params with pair-id data clump (5/CQ-21)
- `canonical._ORDER_INSENSITIVE_LIST_FIELDS` doesn't include `always_allow` — undocumented (5/CQ-18)
- `rendering._clear_stale_paths` uses `rmtree` without dir/file dispatch (5/CQ-20)
- `is_reserved_customization_name` hardcodes `:` separator knowledge (6/CQ-17)
- `kind_disable_config_keys` not validated against `io` keys (6/CQ-16)
- `build_antigravity_spec` signature deviates from other 6 builders (6/CQ-20)
- `state_owner_for_path` is O(N×M) per call — no precomputed index (6/CQ-21)
- Storage-shape and customization-kind magic strings throughout (6/CQ-12)
- `install.ps1` magic `RestartCount 999` (6/CQ-18)
- Integration test workspace-only grep regex fragile to digit-containing keys (6/CQ-20)

---

## Suggested release strategy

1. **Tag v0.5 only after P0-1 through P0-6 are fixed.** They are the only items that ship visible defects to users.
2. **P1-1 through P1-5** (the half-finished refactors) are the highest-leverage cleanup — every other adapter-level finding gets cheaper to fix once those land.
3. **P1-15 / P1-16** (mixin God Classes) should be decided before more functionality is layered on; refactoring later costs more.
4. **P2 / P3** can ride the v0.6 cycle.
