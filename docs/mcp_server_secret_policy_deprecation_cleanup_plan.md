# Deprecation cleanup plan: `mcp_server_secret_policy` → `secret_policy`

## What is deprecated

v0.5 renamed the top-level config key `mcp_server_secret_policy` to
`secret_policy` and replaced its three legacy values
(`refuse` / `redact` / `permissive`) with two (`secrets_refused` /
`secrets_accepted`). For **one release** (v0.5 only), the old key, the old
CLI flag, and the old values are accepted as compatibility aliases, each
emitting one structured `DEPRECATION-WARNING` at startup.

## Trigger and owner

- **Remove in: v0.6.** Already pinned in code (`config.py:301`: "To be
  removed in v0.6"). This document is the single place that also names the
  owner and the full removal surface, closing the governance-prose gap
  (the alias sentence in `docs/project_description.md` and
  `docs/agentic_tool_integration_protocol.md` named no trigger).
- **Owner: the v0.6 release.** The rename + shim was landed atomically in
  v0.5 (`docs/v0.5_security_hardening_plan.md` §2.1, D2); the removal is a
  single scoped change in v0.6, not a long-tail follow-up.

## Removal surface (verified against the v0.5 tree)

### Code

- `src/agents_sync/config.py`
  - `_ARG_TO_CONFIG_KEY` entry `("mcp_server_secret_policy", "secret_policy")` (line ~284).
  - Compat shim 1/2: `legacy_value = config.pop("mcp_server_secret_policy", …)` + the `DEPRECATION-WARNING` (lines ~296–308).
  - Compat shim 2/2: the `warn_deprecated=True` value-normalization call (lines ~310–318) reverts to a plain value read.
- `src/agents_sync/mcp_secret_policy.py`
  - `_OLD_POLICY_VALUE_MAP` (`refuse`/`redact` → `secrets_refused`, `permissive` → `secrets_accepted`).
  - `ALLOWED_MCP_SECRET_POLICIES` alias symbol.
  - The `warn_deprecated` branch of `normalize_secret_policy`.
- `src/agents_sync/cli.py` — the `--mcp-server-secret-policy` deprecated flag and its `config.get("mcp_server_secret_policy")` fallback (line ~329).
- `src/agents_sync/tool_specs/_mcp_server_factory.py` — the `config.get("mcp_server_secret_policy")` fallback (lines ~34–42).
- `src/agents_sync/tool_specs/cursor.py` — the same fallback (line ~41).
- `src/agents_sync/portable_archive.py` — the same fallback (line ~580).

### Tests

- `tests/test_portable_archive_secret_egress.py` — the three compat-shim
  tests (old key accepted with warning; `refuse` → `secrets_refused`;
  `redact` → `secrets_refused` with warning) are removed once the shim is
  gone. Any other test asserting the `DEPRECATION-WARNING` line is updated.

### Governance / reference docs (remove the alias clause)

- `docs/project_description.md` — the v0.5 release-note sentence about the
  deprecated key.
- `docs/agentic_tool_integration_protocol.md` §Secret policy — the
  "accepted for one release as compatibility aliases" clause.

### Left as historical record (do **not** edit)

The v0.5 per-tool implementation plans and research notes
(`v0.5_copilot_implementation_plan.md`, `v0.5_cursor_implementation_plan.md`,
`v0.5_gemini_cli_implementation_plan.md`, `v0.5_implementation_plan.md`,
`v0.5_mcp_server_implementation_plan.md`) reference the old key as a
point-in-time record. They are historical and stay as written.

## Verification at removal

- A config or CLI invocation using `mcp_server_secret_policy` / a legacy
  value fails with the normal unknown-key / invalid-value path — no special
  handling, no warning.
- `uv run pytest` is green with the shim tests deleted.
- `grep -rn "mcp_server_secret_policy" src/` returns nothing.
</content>
</invoke>
