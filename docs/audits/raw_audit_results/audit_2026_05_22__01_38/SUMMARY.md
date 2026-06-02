# Follow-up audit summary — 2026-05-22

**Branch:** `feat/v0.5-plan`
**Predecessor audit:** `docs/global_audit_2026_05_21.md` + `docs/audit/0X-*.json` (2026-05-21)
**Predecessor remediation:** `docs/v0.5_audit_remediation_plan.md` (4 phases, commits af20d9c → 91528f3 → a49c9d0 → 626d7f2 → 126a5ed)
**This sweep:** 10 code-quality re-runs + 3 dedicated security slices.

## Slice-by-slice verdicts

| # | Slice | Verdict | CRITICAL | MAJOR | WARNING | INFO |
|---|---|---|---|---|---|---|
| 01 | mcp_server_io (now a package) | **PASS** | 0 | 0 | 0 | 5 |
| 02 | mcp_secret_policy | **PASS** | 0 | 0 | 3 | 1 |
| 03 | mcp_server_sync tests | **PASS** | 0 | 0 | 5 | 2 |
| 04 | shared_keyed_map | **PASS** | 0 | 0 | 7 | 0 |
| 05 | agentic_tool_spec / tool_specs/ | **PASS** | 0 | 0 | 0 | 3 |
| 06 | discovery / sync core | **PASS** | 0 | 0 | 5 | 1 |
| 07 | per-tool adapters | **PASS** | 0 | 0 | 4 | 6 |
| 08 | cli / config / rendering / adoption/ | **PASS** | 0 | 0 | 1 | 5 |
| 09 | daemon / archive / filesystem | **PASS** | 0 | 0 | 3 | 4 |
| 10 | e2e / integration tests | **PASS** | 0 | 1 | 3 | 2 |
| SEC-A | Secrets / credentials lifecycle | **PASS** | 0 | 1 | 0 | 4 |
| SEC-B | Filesystem / path traversal / archive | **FAIL** | 0 | 1 (HIGH) | 2 | 3 |
| SEC-C | Parsing / deserialization | **PASS** | 0 | 2 | 4 | 3 |

## Headline findings

### Must-fix before release

- **SEC-B-01 (HIGH) — Path traversal via raw MCP slot name in `archive.archive_text`.**
  Slot keys from `mcpServers` / `mcp_servers` / `mcp` are passed unsanitized as filename components when archiving prior slot bytes. A malicious slot name `../../../tmp/pwned` (delivered via a tampered portable-archive import OR via direct edit of `.claude.json` etc.) escapes `<state_dir>/archive/<pair_id>/<side>/`. Fix: slug the slot name and `resolve().is_relative_to()` the target dir.

### Strongly recommended

- **SEC-A-01 (MAJOR) — `export_to_zip` does not re-apply secret policy.**
  Under `mcp_server_secret_policy = permissive`, literal secrets sit in `<state_dir>/canonical/`. Export zips them verbatim. No `contains_secret_literals` flag in the manifest, no CLI warning. Mitigation: re-apply the policy at export, or set a manifest flag + WARNING line.
- **SEC-C-01 (MAJOR) — No YAML alias/anchor expansion cap.**
  `markdown_yaml_metadata_block.yaml_load` uses `typ='rt'` (RCE-safe) with no alias / anchor / size cap. Quadratic YAML-bomb is feasible against the long-running daemon.
- **SEC-C-02 (MAJOR) — No input-size cap at any parser boundary.**
  `read_slots` / `_read_root_and_node` / canonical/state loaders all `read_text()` without size guards. A 2 GB hostile `mcp.json` will OOM the daemon every poll.
- **TQ-01 / slice 10 (MAJOR) — slow/integration pytest markers are registered but applied to ZERO modules.**
  `pytest -m 'not integration'` deselects nothing; the §7.1 fast-path policy is unenforced.

### Should-fix (defense in depth)

- SEC-B-02 — discovery walker follows symlinks (Python 3.12 default), letting symlinks in `~/.claude/skills/` cross the configured-root boundary.
- SEC-B-03 — `is_transient_fs_error` retries every `PermissionError` on POSIX unconditionally.
- SEC-B-04 — `atomic_write_text` lacks `O_NOFOLLOW`/`O_EXCL`; tmp suffix only 32 bits.
- SEC-B-05 — quarantine dir inherits source perms (should be 0700/0600).
- SEC-B-06 — slug-displacement unlink races concurrent reader, producing misleading "corrupt" logs.
- SEC-C-03 — `HIGH_CONFIDENCE_SECRET_VALUE_RE` applied to arbitrary-length strings (no `len(value) > 4096` short-circuit).
- SEC-C-04 — `_strip_legacy_review_metadata` silently truncates body content matching the marker on first sight.
- SEC-C-05 — bare `str(...)` coercion of frontmatter values in every Markdown adapter masks type confusion.
- SEC-A-04 — stale canonicals persist literal secrets after policy downgrade; no rescan command exists.
- SEC-A-03 — `tomllib.TOMLDecodeError` tracebacks via `logging.exception` can leak partial slot bytes.

## What carried over cleanly (recap of closed criticals)

- Slice 04 CRITICAL: `apply_slot` optimistic re-read → **real cross-process `lock_file` (`fcntl.flock`/`msvcrt.locking`) on sidecar `.lock`**. Closed and tested.
- Slice 09 CRITICAL: daemon `bare-except + blocking sleep` → **error budget + `threading.Event.wait` + four behavioural loop tests**. Closed.
- Slice 06: silent rebuild of corrupt state/canonical → **quarantine + ERROR log + schema-version differentiation**. Closed.
- Slice 06: `atomic_write_text` not actually atomic → **fsync(tmp) + fsync(parent_dir) + unique pid+uuid suffix**. Closed (modulo SEC-B-04 hardening).
- Slice 05: 721-line God Module → **`tool_specs/` package** + `__post_init__` invariant against config/IO drift. Closed.
- Slice 08: 648-line `adoption.py` God Module → **`adoption/` package + five mixins**, broad excepts narrowed, privacy gate now **fails CLOSED**. Closed.

## Targets and gating

- Pre-v0.5 release gate: SEC-B-01 must be fixed and have a regression test. Everything else (MAJORs above + WARNINGs of choice) can be scheduled as a follow-up remediation pass.
- Suggested next step: spawn a fresh issue-resolver pass on SEC-B-01 + SEC-A-01 + SEC-C-01 + SEC-C-02 + TQ-01 only (the five MAJOR/HIGH findings). All other findings are bounded INFO/WARNING hygiene.

## Files

- 10 code-quality JSONs: `docs/audit/2026-05-22/{01..10}-*.json`
- 3 security JSONs: `docs/audit/2026-05-22/SEC-{A,B,C}-*.json`
