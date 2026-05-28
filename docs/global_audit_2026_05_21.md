# Global Code-Quality Audit — 2026-05-21

**Branch:** `feat/v0.5-mcp-server` (HEAD `ba17ac0`)
**Scope:** 10 parallel `code-quality-auditor` subagents over the full Python codebase + tests.
**Per-slice JSON reports:** [`docs/audit/`](./audit/)

| # | Slice | Verdict | CRITICAL |
|---|---|---|---|
| 01 | [MCP server I/O](./audit/01-mcp-server-io.json) | AUDIT_WEAK | 0 |
| 02 | [MCP secret policy + real adapters](./audit/02-mcp-secret-policy.json) | AUDIT_WEAK | 0 (weakest_axis: **security**) |
| 03 | [MCP server sync tests](./audit/03-mcp-server-sync-tests.json) | AUDIT_WEAK | 0 |
| 04 | [Shared keyed-map module](./audit/04-shared-keyed-map.json) | AUDIT_WEAK | **1** |
| 05 | [`agentic_tool_spec` + `tool_status`](./audit/05-agentic-tool-spec.json) | AUDIT_WEAK | 0 |
| 06 | [Discovery / state / sync core](./audit/06-discovery-sync-core.json) | AUDIT_WEAK | 0 |
| 07 | [Per-tool I/O adapters](./audit/07-per-tool-adapters.json) | AUDIT_WEAK | 0 |
| 08 | [CLI / config / rendering / adoption](./audit/08-cli-config-rendering-adoption.json) | AUDIT_WEAK | 0 |
| 09 | [Daemon / archive / filesystem / rules](./audit/09-daemon-archive-filesystem.json) | AUDIT_WEAK | **1** |
| 10 | [E2E + integration + platform tests](./audit/10-e2e-integration-tests.json) | AUDIT_WEAK | 0 |

Every slice landed at `AUDIT_WEAK`. No slice landed at `AUDIT_PASS`. No security-critical injection/secret-leak defects, but two **CRITICAL** correctness defects and several cross-cutting structural patterns surfaced repeatedly.

---

## 1. CRITICAL findings (data-loss or unsupervised-failure risk)

### 1.1 TOCTOU in `shared_keyed_map_io.apply_slot` — race contract not enforced
Slice 04 · CQ-01 · `src/agents_sync/shared_keyed_map_io.py:88`

The module docstring promises atomic semantics and "never partially overwritten" with detect-and-retry against concurrent writers. The implementation only re-reads `before_text` immediately before `atomic_write_text`. `os.replace` is atomic at the inode level but **does not compare-and-swap on file contents**. Two writers can both observe a stable `before_text`, both decide they "won", and the second `os.replace` silently clobbers the first. Needs real locking (`fcntl.flock`, O_EXCL + cmpxchg via stat, or `portalocker`). No test simulates this.

### 1.2 `daemon.watch()` silently swallows every Exception
Slice 09 · CQ-01 · `src/agents_sync/daemon.py:34`

The daemon catches every `Exception` from `sync_once` with no error counter, no backoff, no circuit breaker, no rate-limited logging. A persistent IOError (disk full, perms revoked, `atomic_write_text` failing) spins forever, logging once per interval. Against NFR-01 (data preservation), a daemon that swallows IO errors but keeps running risks **masking user data loss**. Compounded by Slice 09 · CQ-03: the only daemon test exercises a 4-line helper — the loop, exception path, and cancellation race have zero coverage.

---

## 2. Cross-cutting structural debt

### 2.1 `isinstance(SharedKeyedMapLayout, ...)` switch repeated across the engine
Surfaces in slices 05, 06, 08, 09. Five branches in `discovery.py` + `sync.py`, two more in `tool_status.py`, plus duplicated branches in `adoption.py`. The `FileLayout` protocol exists precisely to abstract this but is never used polymorphically. Adding a third layout = shotgun surgery across 8+ sites in 4+ files.

**Recommended shape:** put `probe_target(config_value)`, `read_text_for(info, slot)`, `target_for(canonical, root)` on the `FileLayout` protocol so the call sites become uniform.

### 2.2 `canonical.py` does not actually canonicalize
Slice 06 · CQ-01 · `src/agents_sync/canonical.py`

Only `sort_keys=True` is enforced. **No invariants on:** list ordering of `tools` / `disallowed_tools`, None-vs-missing semantics for `model` / `effort` / `permission_mode`, whitespace stripping on `name` / `description`, CRLF normalization on `body`. Two semantically-equal canonicals from different tools can produce different SHA-256 digests. No `canonicalize()` helper, no `canonical_equal()` helper, no `parse(render(canonical))` symmetry assertion anywhere in the engine (Slice 06 · CQ-11). The codebase is structured to allow asymmetry to slip in unnoticed and write the same bytes every poll silently.

### 2.3 `atomic_write_text` is not actually atomic
Slice 06 · CQ-05 · `src/agents_sync/state.py:195`

No `fsync(tmp)` before rename, no `fsync(parent_dir)` after rename. Power loss on ext4 `data=writeback` or most Windows filesystems can leave the renamed inode pointing at zero bytes. Fixed `.{name}.tmp` suffix → two interleaved writers clobber each other's tmp file. This is the routine that persists `state.json` and `canonical/*.json` — **it is the source of the corrupt-state scenarios that `load_state` / `load_canonical` then silently mishandle** (slice 06 · CQ-02, CQ-03 below).

### 2.4 Silent state-rebuild on corruption
Slice 06 · CQ-02, CQ-03 · `canonical.py:58` and `state.py:207`

- `load_canonical` collapses 3 distinct failure modes (absent / corrupt JSON / non-dict) to `None`. Callers re-mint and overwrite corrupted bytes.
- `load_state` collapses **5 anomalies** (missing / parse error / not-a-dict / wrong schema / missing customization_artifacts) to `return {}`. An empty state dict drives `sync_once` to treat every artifact on disk as a newly-discovered orphan → fan-out unintended writes across all tools. No `.bak`, no quarantine, no metric.

### 2.5 Capability matrix declared in two unchecked dicts
Slice 05 · CQ-03 · `src/agents_sync/agentic_tool_spec.py:160`

`AgenticToolSpec.config_dir_keys` and `AgenticToolSpec.io` both encode the set of customization types. `supported_customization_types` reads from `io`; `tool_status` iterates `config_dir_keys`. No `__post_init__` enforces `set(config_dir_keys) == set(io)`. Drift risk doubled by the v0.5 addition of `rules` and `mcp_server` slots in both dicts.

### 2.6 `claude_io.py` is the de-facto YAML-frontmatter library
Slice 07 · CQ-02 · the three sibling adapters import 5 underscore-prefixed helpers from `claude_io` (`_make_yaml`, `_yaml_load`, `_strip_bom_prefix`, `_normalize_markdown_text`, `FRONTMATTER_RE`). `codex_io` does it lazily at function scope to hide the dependency. The YAML-frontmatter parse prelude is duplicated **4 times** with 3 different error messages for the same logical condition (CQ-03, CQ-06). Render prelude duplicated 3 times.

**Recommended shape:** extract `agents_sync/markdown_yaml_metadata_block.py` with public API; `claude_io` consumes it like the others. Define a shared `AdapterParseError`.

### 2.7 Liskov violation in `parse_X` adapter family
Slice 07 · CQ-01 · `parse_opencode_agent_md` alone derives `name` from `artifact_path.stem` (keyword-only, default None). All siblings derive `name` from document content. **`sync.py` / `discovery.py` must treat the family as interchangeable**; a caller that forgets the kw-only arg gets a silent `name=''`. No `Protocol`/ABC declares the divergence. Exactly the `artifact_path=None` branch has no test (CQ-13).

### 2.8 God Module / Long Functions

| Module | Lines | Threshold | Notes |
|---|---|---|---|
| `agentic_tool_spec.py` | **721** | 500 | God Module: data model + 3 IO factories + 4 per-tool builders (each 100+ lines) + registry assembler |
| `adoption.py` | **648** | 500 | `AdoptionEngine` spans 5 responsibility clusters; 4 in-function imports of `SharedKeyedMapLayout` mask a latent cycle |
| `mcp_server_io.py` | 612 | 500 | God-Class-lite `McpServerDialect` (18 fields, 4 responsibilities) |
| `discovery.py` | 507 | 500 | 7 over budget; 13 methods across 3 responsibility clusters |
| `shared_keyed_map_formats.py` | 283 | — | Registry + JSON + hand-rolled TOML emitter + hand-rolled JSONC tokeniser in one |

Long functions ≥40 lines flagged: `_project_to_other_tools` (76), `_propagate_removal` (74), `_planned_adoption_targets` (65), `parse_mcp_server_json` (66), `block_target_collisions` (60), `_reconcile_new_groups` (88, closure-in-loop), `import_from_zip` (99), `_strip_jsonc_comments` (57), `apply_slot` (56), `render_to_agentic_tool` (49), `_render_http_headers` (50), `_build_opencode_spec` (136), `_build_codex_spec` (116), `_build_claude_spec` (108).

### 2.9 Primitive Obsession on `(path, slot)`
Slice 06 · CQ-17. Four dataclasses (`AgenticToolInfo`, `PlannedTarget`, `RenderResult`, `AgenticToolState`) + 6 function signatures carry `(path: Path, slot: str | None)`. The pair is semantically one thing: a location at which an artifact lives. Also: `AgenticToolState.path` is `str` while everywhere else uses `Path`.

**Recommended shape:** `ArtifactLocation` value type with `for_file(path)` / `for_slot(path, key)` constructors.

---

## 3. Security gaps in `mcp_secret_policy` (Slice 02)

The secret heuristic is the security-sensitive boundary of v0.5. It is the only audited file where `security` is the weakest axis. Findings are concentrated and inter-related:

| ID | Issue |
|---|---|
| CQ-01 | `_ENV_NAME = [A-Z_][A-Z0-9_]*` rejects lowercase env names. `${env:my_token}` → treated as literal → redact silently rewrites a valid env reference to a placeholder, destroying intent. |
| CQ-02 | Safe-reference regex is **fully anchored**. Concatenated refs (`prefix-${env:TOKEN}`, `Basic ${env:BASIC_AUTH}`) treated as literals → redact destroys prefix/suffix. |
| CQ-03 | **Two over-permissive allowlists** trust key names without inspecting values: keys ending in `env_var` / `env_vars`, and any path containing `env_http_headers`. A literal placed under `bearer_token_env_var='ghp_xxxx'` or `env_http_headers.X-Auth='literal-token'` **bypasses detection under all 3 policies — including `refuse`**. |
| CQ-04 | Secret-field regex misses `passphrase`, `credential(s)`, `dsn`, `connection_string`, `cookie`, `session`, `jwt`, `pat`, **`private_key`**. No NFKC normalization → homoglyph bypass (`аpi_key` Cyrillic `а`, `ＡＰＩ_ＫＥＹ` fullwidth). No value-side entropy detection (`ghp_`, `sk-`, `AKIA`, `xoxb-`, `eyJ`). |
| CQ-06 | Headers allowlist hardcodes `len(path) == 2` — silently stops matching if caller passes the full Claude file shape (`mcpServers.<name>.headers.Authorization`). |
| CQ-07 | `_PERMISSIVE_WARNING_CACHE` is module-level mutable; requires explicit `reset_mcp_secret_warning_cache()` hook; unbounded growth. |
| CQ-09 | Inconsistent return aliasing — input dict returned by reference for no-findings / permissive; deep-copied for redact. |
| CQ-12 | The **only** test exercising the policy asserts placeholder presence but **never asserts `"literal-token"` is absent** from any output file. |
| CQ-13 | 5 of 6 real-adapter tests use env-reference inputs — they cannot detect a regression that loosens literal detection. |
| CQ-14 | Refuse policy never exercised end-to-end with a real literal. |
| CQ-15 | Policy test reads only Claude + Codex output; never `state.json`, never opencode, never `secret_redactions` metadata. |

**Net effect:** "refuse" is softer than its name implies, and the test suite cannot detect a real leak regression.

---

## 4. Test-suite anti-patterns

### 4.1 Mislabeled platform tests (Slice 10)
- `test_macos_compat.py` — monkeypatches `sys.platform`; runs on Linux CI exactly as on darwin. No `@pytest.mark.skipif`. Real HFS+/APFS / AppleDouble interaction never exercised.
- `test_windows_silent_startup.py` — **grep-as-test**. Asserts substrings of `install.ps1`. PowerShell syntax errors, quoting regressions, visible-window regressions all pass silently.
- `test_windows_slug_collision.py` — monkeypatches `os.path.normcase`. Real NTFS case-only filename behaviour never exercised.
- `test_windows_filesystem_retries.py` — monkeypatches `time.sleep` to no-op. Real Windows filesystem races (Defender, OneDrive lazy hydration) never exercised.

### 4.2 Missing promised coverage
- `test_migrate_v0_4.py` — three tests, **zero of them materialize a real v0.3 layout** in `tmp_path` and run the real `run_migration`. All three monkeypatch the migration into stubs.
- AC-10 transactional guarantee for `import_from_zip` — test only asserts `state.json` absent; does NOT verify rollback of partially-written canonicals / projected tool-side files (Slice 09 · CQ-04, CQ-05).
- Missing critical contracts on MCP server sync (Slice 03 · CQ-11): no idempotency test, no head-on conflict-resolution test, no `mcpServers` key-ordering test.

### 4.3 Tests that pass when the SUT is broken
- `test_mcp_secret_policy_refuse_blocks_adoption` (Slice 03 · CQ-01) — all 4 assertions negative; would pass if MCP processing silently bailed for any reason.
- `test_mcp_two_adapters_same_shared_file_same_slot_collide` (Slice 03 · CQ-02) — no collision-specific signal; would pass if collision detector were removed entirely.

### 4.4 Capability-matrix under-pinning
`test_agentic_tool_spec.py` (Slice 05 · CQ-09) asserts `mcp_server` IO *presence* but never the differentiating per-tool fields:
- `map_key_path` — `('mcpServers',)` vs `('mcp_servers',)` vs `('mcp',)`
- `file_format` — `json` vs `toml`
- Any `McpServerDialect` field

A regression flipping claude's map path to `mcp_servers` would pass the entire test file. 9 of 15 registered cells lack registry-level round-trip tests (CQ-10).

### 4.5 Other recurring test smells
- **God Fixture** — `conftest.syncer` wires 4 tools / 13 dirs / 16+ config keys for every test (Slice 10 · CQ-04). Tests needing variation copy 30+ lines inline.
- **Sensitive Equality on log messages** — `test_unreadable_prior_text_logs_warning_and_continues` (Slice 10 · CQ-07), `test_mcp_secret_policy_permissive_warns` (Slice 03 · CQ-03), `test_antigravity_config.py` log-substring assertions (Slice 08 · CQ-14).
- **Magic placeholder format** as test contract — `${env:AGENTS_SYNC_REDACTED_1}` literal duplicated across tests (Slice 03 · CQ-04).
- **Conditional logic in helpers** — `_pair_id_for_slot` (Slice 03 · CQ-05) used by 4 tests; a helper bug masks 4 regressions.
- **Synthetic-only fixtures** — `tests/` has no `fixtures/` dir; adapters never exercised on artifacts captured from the real tools (Slice 07 · CQ-12).
- **`time.sleep(0.01)`-based ordering** — `test_update_state_n_way_advances_last_modified_on_subsequent_edit` (Slice 10 · CQ-06) flaky on coarse clocks.
- **Test documents known defect without `xfail(strict=True)`** — `test_mixed_managed_and_new_at_same_slug_is_blocked` (Slice 10 · CQ-09) asserts block-and-log when spec §5.5 calls for managed-wins-and-archive; future implementer sees an obscure assertion failure.

---

## 5. Silent-overwrite surfaces (data preservation against NFR-01)

| Site | Severity | Issue |
|---|---|---|
| `daemon.watch` exception swallowing | CRITICAL | §1.2 |
| `apply_slot` race condition | CRITICAL | §1.1 |
| `_navigate_or_create` (slice 04 · CQ-07) | MAJOR | If `map_key_path` has a non-dict value (user wrote `"mcpServers": "disabled"`), it is silently replaced with `{}`. |
| `load_state` rebuild | WARNING | §2.4 |
| `atomic_write_text` non-atomicity | WARNING | §2.3 |
| `import` CLI default `mtime_wins` | WARNING | Slice 08 · CQ-07. No `--force` for `overwrite`, no diff preview, no confirmation. |
| `_target_is_private` fails OPEN | WARNING | Slice 08 · CQ-13. Any `parse` exception → "NOT private" → renderer overwrites. Security adjacency. |
| `last_modified` wall-clock skew | WARNING | Slice 06 · CQ-18. NTP rewind / VM resume / Windows local-time → `mtime_wins` silently overwrites live edits. |
| `_propagate_removal` broad except | WARNING | Slice 08 · CQ-12. Swallows TypeError/AttributeError equally with I/O errors. |
| Read/write asymmetry in `apply_slot` | MAJOR | Slice 04 · CQ-02. First round-trip drifts user data on disk (`name` field injected). |

---

## 6. Remediation priorities

**Tier 1 — fix before next release:**
1. Real locking in `apply_slot` (slice 04 · CQ-01).
2. Error budget + backoff + observable failure surface in `daemon.watch` + tests against the loop (slice 09 · CQ-01, CQ-02, CQ-03).
3. Tighten `mcp_secret_policy`: drop suffix allowlists or gate them on value-shape validation; add NFKC; broaden secret-field dictionary; add value-side entropy/prefix checks; add a test that asserts literal absence across **all** output surfaces (slice 02 · CQ-03, CQ-04, CQ-12).
4. Real fsync + unique tmp suffix in `atomic_write_text` (slice 06 · CQ-05).
5. Quarantine-then-rebuild semantics for `load_state` / `load_canonical` with `.bak` preservation (slice 06 · CQ-02, CQ-03).

**Tier 2 — structural cleanup before adding a third file layout:**
6. Polymorphic `FileLayout` protocol; eliminate `isinstance(SharedKeyedMapLayout, ...)` switches (cross-cutting, §2.1).
7. `canonicalize()` + `canonical_equal()` + an assertion that `parse(render(canonical))` round-trips at adoption time (§2.2).
8. Extract `markdown_yaml_metadata_block` module; collapse 4× duplicated parse prelude; unify `AdapterParseError` (§2.6).
9. `__post_init__` invariant on `AgenticToolSpec` (§2.5).
10. Split `adoption.py` (`AdoptionEngine` → 5 collaborators); split `agentic_tool_spec.py` per-tool builders into a thin data-only registry; lift in-function imports.

**Tier 3 — test-suite hygiene:**
11. Rename mislabeled `test_*macos*` / `test_*windows*` files to `test_*_simulated.py` or gate with `@pytest.mark.skipif`. Wire real-platform CI matrix or delete the false promise.
12. Real-artifact fixtures in `tests/fixtures/<tool>/` captured from Claude / Codex / Antigravity / opencode.
13. Add a true v0.3→v0.4 migration test that materializes a real layout and asserts the post-migration state.
14. Replace log-substring assertions with structured log fields or named exception types.
15. Idempotency / conflict-resolution / key-ordering tests for the MCP-server sync feature.
16. Mark `test_mixed_managed_and_new_at_same_slug_is_blocked` as `@pytest.mark.xfail(strict=True, reason='spec §5.5 deferred')` so the future implementer sees a green→red transition with the correct message.

---

## 7. What is in good shape

- **No hardcoded secrets, no injection vectors, no `pickle`/`yaml.unsafe_load`, no `shell=True`, no star imports, no global mutable state outside the two flagged registries.**
- **Acyclic import graph** across the six core engine modules (`identity → state → canonical → sync_types → discovery → sync`).
- **`identity.py`** scored a clean 1.0 across all axes.
- **`test_round_trip.py`, `test_rules_io.py`, `test_rules_sync.py`, `test_rules_real_adapters.py`, `test_slash_command_*.py`, `test_config_platform_defaults.py`, `test_cli_export_import.py`, `test_agentic_tool_status.py`** — all scored clean with zero findings.
- **E2E tests against `Syncer.sync_once` over real tmp filesystems** are genuine and the strongest layer of the test pyramid.
- **CLI / config / per-OS branching** in `cli.py` / `config.py` are well-disciplined; the per-OS code is localised to a few small helpers rather than scattered.

---

*This report aggregates output from 10 parallel `code-quality-auditor` subagents. Each slice's full structured JSON is in `docs/audit/`. The auditor catalog is from Fowler, Martin, Suryanarayana, Lacerda, Zhang (code smells), van Deursen, Meszaros, Spadini, Peruma, Khorikov (test smells), and OWASP (security smells).*
