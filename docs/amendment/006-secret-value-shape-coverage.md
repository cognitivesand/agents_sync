# Amendment 006 — Broaden MCP secret value-shape detection; document the residual

- status: applied (code); NFR-15 clarification (2b) pending user validation
- branch: feat/v0.5-cross-machine-merge
- date: 2026-05-31
- relates to: v0.6 safety audit (finding D), NFR-15

## Motivation

The safety audit found that `find_mcp_secret_literals` (mcp_secret_policy.py) flags a
literal via three legs — under an `env`/headers/auth path (any shape), under a field
whose name matches `SECRET_FIELD_RE`, or matching the `HIGH_CONFIDENCE_SECRET_VALUE_RE`
value menu. The value menu was a short prefix list (`sk-`, `ghp_`, `github_pat_`,
`AKIA`, `xoxb-`, JWT). A credential of a common-but-unlisted shape (Google `AIza…`,
Google OAuth `ya29.`, GitLab `glpat-`, Stripe `sk_live_`/`rk_live_`, npm `npm_`, Slack
`xoxp/xoxa/xoxr`) placed outside any env/headers/secret-named field would be classified
clean and exported under the default `secrets_refused` policy — a cross-machine leak.

## Principle / decision

The value-shape menu covers the well-known high-confidence credential prefixes.
Detection remains prefix/field/location-based, not generic-entropy-based (entropy
heuristics carry an unacceptable false-positive rate for MCP config values). The
**residual** — an arbitrary-shape literal in a non-secret field, outside env/headers —
is documented, with the guidance to place secrets in `env`/headers (where any literal
is caught).

## Proposed governance edits (require user validation)

`docs/project_requirements.md` NFR-15 — append one clarifying sentence naming the
detection model and the residual. Proposed addition (to the end of NFR-15):

> Secret detection at egress is heuristic: a literal is refused when it sits under an
> `env`, `headers`, or `auth.*` field, under a field whose name matches the
> secret-field set, or when its value matches a high-confidence credential shape. A
> literal of an arbitrary shape placed in a non-secret field outside those locations
> is the documented residual; such credentials **shall** be supplied via `env` or
> `headers`, where any literal is detected regardless of shape.

## Design edits (architecture)

None.

## Implementation (applied)

`mcp_secret_policy.HIGH_CONFIDENCE_SECRET_VALUE_RE`: added Stripe `sk_live_`/`rk_live_`,
GitLab `glpat-`, npm `npm_`, Google `AIza`/`ya29.`, and broadened Slack `xoxb-` →
`xox[baprs]-`. Each is a distinctive prefix with negligible false-positive risk.

## Test plan (applied)

`tests/test_mcp_server_io.py::test_value_shape_detects_broadened_credential_menu_outside_secret_fields`
— parametrized over the new shapes under a non-secret field; each is flagged.

## Verification

Full `uv run pytest` (506) + `mypy --strict` + `ruff` green. NFR-15 sentence applied
only after user validation.
