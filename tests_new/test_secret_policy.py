"""Unit tests for the secret policy (rebuild S18, NFR-15, US-13).

Detection scans a canonical document's wire-shaped structured fields (command,
args, env, cwd, url, headers, auth, per_tool_extra) — never prose (name,
description, body) or bookkeeping (per_tool_only). A literal is a finding when it
sits under env/headers/auth, under a secret-named field, or matches a
high-confidence credential shape; a value that delegates to the environment
(env reference, any spelling) is safe. Enforcement: ``secrets_refused`` fails
closed with a structured error naming artifact, field path, and policy;
``secrets_accepted`` returns the findings for the caller's per-artifact warning.
Pure in-memory tests.
"""

from __future__ import annotations

from typing import Any

import pytest

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.secret_policy import (
    SECRET_POLICY_ACCEPTED,
    SECRET_POLICY_REFUSED,
    SecretLeakError,
    enforce_secret_policy,
    find_secret_literals,
)

_ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"


def _mcp_document(**overrides: Any) -> CanonicalDocument:
    fields: dict[str, Any] = {
        "artifact_id": _ARTIFACT_ID,
        "kind": "mcp_server",
        "name": "github",
        "transport": "stdio",
        "command": "npx",
    }
    fields.update(overrides)
    return CanonicalDocument(**fields)


def _paths(document: CanonicalDocument) -> set[str]:
    return {finding.field_path for finding in find_secret_literals(document)}


# --- detection: the three field locations --------------------------------------------


def test_an_env_literal_is_a_finding_regardless_of_shape() -> None:
    document = _mcp_document(env={"GH_TOKEN": "hunter2"})

    assert _paths(document) == {"env.GH_TOKEN"}


def test_an_env_reference_value_is_safe() -> None:
    document = _mcp_document(
        env={
            "A": "${GITHUB_TOKEN}",
            "B": "{env:GITHUB_TOKEN}",
            "C": "$GITHUB_TOKEN",
            "D": "%GITHUB_TOKEN%",
        }
    )

    assert _paths(document) == set()


def test_a_header_literal_is_a_finding() -> None:
    document = _mcp_document(
        transport="http", command=None, url="https://x", headers={"Authorization": "abc123"}
    )

    assert _paths(document) == {"headers.Authorization"}


def test_a_bearer_env_reference_header_is_safe() -> None:
    document = _mcp_document(
        transport="http",
        command=None,
        url="https://x",
        headers={"Authorization": "Bearer ${GITHUB_TOKEN}"},
    )

    assert _paths(document) == set()


def test_any_header_literal_is_a_finding_regardless_of_name() -> None:
    # NFR-15: location alone suffices under headers ("any literal is detected
    # regardless of shape") — the safe form is an env reference.
    document = _mcp_document(
        transport="http", command=None, url="https://x", headers={"X-Custom": "plain"}
    )

    assert _paths(document) == {"headers.X-Custom"}


def test_an_auth_literal_is_a_finding() -> None:
    document = _mcp_document(auth={"client_secret": "abc123"})

    assert _paths(document) == {"auth.client_secret"}


def test_auth_location_alone_suffices_for_a_non_secret_named_key() -> None:
    # The key is NOT secret-named and the value matches no credential shape:
    # only the auth location rule can flag it (NFR-15: location alone suffices).
    document = _mcp_document(auth={"type": "hunter2"})

    assert _paths(document) == {"auth.type"}


def test_the_http_headers_spelling_is_also_a_headers_location() -> None:
    document = _mcp_document(per_tool_extra={"x": {"http_headers": {"X-Key": "plain"}}})

    assert _paths(document) == {"per_tool_extra.x.http_headers.X-Key"}


def test_an_env_http_headers_carrier_holds_env_var_names() -> None:
    # The carrier maps header names to env var NAMES — valid names are safe even
    # though they sit under a headers-flavoured key.
    document = _mcp_document(per_tool_extra={"x": {"env_http_headers": {"X-Key": "GH_TOKEN"}}})

    assert _paths(document) == set()


def test_an_env_vars_suffixed_field_holds_env_var_names() -> None:
    document = _mcp_document(per_tool_extra={"x": {"secret_env_vars": ["GH_TOKEN"]}})

    assert _paths(document) == set()


# --- detection: secret-named fields and value shapes ----------------------------------


def test_a_secret_named_field_in_per_tool_extra_is_a_finding() -> None:
    document = _mcp_document(per_tool_extra={"cursor": {"apiKey": "abc123"}})

    assert _paths(document) == {"per_tool_extra.cursor.apiKey"}


def test_a_high_confidence_shape_in_args_is_a_finding() -> None:
    document = _mcp_document(args=("--token", "ghp_abcdefghijklmnop"))

    assert _paths(document) == {"args[1]"}


def test_an_arbitrary_literal_in_a_non_secret_field_is_the_documented_residual() -> None:
    # NFR-15: an arbitrary-shaped literal outside env/headers/auth and outside
    # secret-named fields is not detected — credentials belong in env/headers.
    document = _mcp_document(cwd="/srv/hunter2")

    assert _paths(document) == set()


def test_prose_fields_are_never_scanned() -> None:
    # An agent's body may quote a key shape in documentation; prose is not egress
    # of a credential field and the old policy never scanned non-wire prose.
    document = CanonicalDocument(
        artifact_id=_ARTIFACT_ID,
        kind="agent",
        name="ghp_abcdefghijklmnop",
        description="use sk-abcdefghijklmnop",
        body="example: sk_live_abcdefghijklmnopqrst",
    )

    assert _paths(document) == set()


def test_an_env_var_name_expecting_field_accepts_a_valid_name() -> None:
    # A tool's native env-carrier field holds an env var NAME: a valid name is
    # safe even though the field name matches the secret-field set.
    document = _mcp_document(per_tool_extra={"vscode": {"bearer_token_env_var": "GH_TOKEN"}})

    assert _paths(document) == set()


def test_an_env_var_name_expecting_field_rejects_a_credential_shape() -> None:
    document = _mcp_document(
        per_tool_extra={"vscode": {"bearer_token_env_var": "ghp_abcdefghijklmnop"}}
    )

    assert _paths(document) == {"per_tool_extra.vscode.bearer_token_env_var"}


def test_secret_field_matching_is_case_insensitive() -> None:
    document = _mcp_document(per_tool_extra={"cursor": {"API-KEY": "abc123"}})

    assert _paths(document) == {"per_tool_extra.cursor.API-KEY"}


def test_secret_field_matching_normalises_unicode_compatibility_forms() -> None:
    # A fullwidth key spelling must not evade the secret-field set (NFKC).
    document = _mcp_document(per_tool_extra={"cursor": {"ＡＰＩ＿ＫＥＹ": "abc123"}})

    assert _paths(document) == {"per_tool_extra.cursor.ＡＰＩ＿ＫＥＹ"}


def test_a_short_github_pat_prefix_is_rejected_as_an_env_var_name() -> None:
    # The proven guard: a ghp_-prefixed value too short for the shape pattern is
    # still no env var name — fail closed in the carrier branch.
    document = _mcp_document(per_tool_extra={"x": {"bearer_token_env_var": "ghp_abc"}})

    assert _paths(document) == {"per_tool_extra.x.bearer_token_env_var"}


def test_a_dollar_amount_in_a_plain_field_is_not_a_finding() -> None:
    # "$5" is no env reference and matches no shape: ordinary prose-ish values in
    # non-secret fields stay clean.
    document = _mcp_document(args=("--note", "$5 fee for C:\\Users\\$name"))

    assert _paths(document) == set()


def test_a_mixed_value_with_reference_and_credential_remainder_is_a_finding() -> None:
    # "${HOST}/sk-..." delegates part of the value but still carries a literal
    # credential shape in the remainder — not safe.
    document = _mcp_document(env={"URL": "${HOST}/sk-abcdefghijklmnop"})

    assert _paths(document) == {"env.URL"}


def test_every_high_confidence_credential_shape_is_detected() -> None:
    # One representative per alternation arm: deleting any single arm (or
    # breaking its quantifier) must fail here. A loop-free exact-set assertion
    # keeps each sample's path identifiable in the failure output.
    samples = {
        "openai": "sk-abcdefghij",
        "stripe": "sk_live_abcdefghijklmnop",
        "stripe_restricted": "rk_live_abcdefghijklmnop",
        "github_classic": "ghp_abcdefghij",
        "github_fine": "github_pat_abcdefghijklmnop",
        "gitlab": "glpat-abcdefghijklmnop",
        "npm": "npm_" + "a" * 36,
        "aws": "AKIAABCDEFGHIJKLMNOP",
        "slack": "xoxb-abcdefghijklmnop",
        "google_api": "AIza" + "a" * 35,
        "google_oauth": "ya29.abcdefghijklmnopqrst",
        "jwt": "eyJ" + "a" * 20 + "." + "b" * 10 + "." + "c" * 10,
    }
    document = _mcp_document(per_tool_extra={"x": samples})

    assert _paths(document) == {f"per_tool_extra.x.{key}" for key in samples}


def test_multiple_findings_accumulate_across_locations() -> None:
    document = _mcp_document(
        env={"GH_TOKEN": "hunter2"},
        per_tool_extra={"cursor": {"apiKey": "abc123"}},
    )

    findings = find_secret_literals(document)

    assert {finding.field_path for finding in findings} == {
        "env.GH_TOKEN",
        "per_tool_extra.cursor.apiKey",
    }
    # the structured path tuple is the primary datum downstream callers consume
    assert ("env", "GH_TOKEN") in {finding.path for finding in findings}


# --- enforcement -----------------------------------------------------------------------


def test_refused_policy_fails_closed_with_a_structured_error() -> None:
    document = _mcp_document(env={"GH_TOKEN": "hunter2"})

    with pytest.raises(SecretLeakError) as error:
        enforce_secret_policy(document, SECRET_POLICY_REFUSED, artifact_label="github")

    message = str(error.value)
    assert "github" in message  # the artifact (NFR-15)
    assert "env.GH_TOKEN" in message  # the offending field path
    assert SECRET_POLICY_REFUSED in message  # the policy
    # the structured attributes the daemon's logging (S22) consumes programmatically:
    assert error.value.artifact_label == "github"
    assert error.value.policy == SECRET_POLICY_REFUSED
    assert [finding.field_path for finding in error.value.findings] == ["env.GH_TOKEN"]


def test_refused_policy_passes_a_clean_document() -> None:
    document = _mcp_document(env={"GH_TOKEN": "${GITHUB_TOKEN}"})

    findings = enforce_secret_policy(document, SECRET_POLICY_REFUSED, artifact_label="github")

    assert findings == ()


def test_accepted_policy_returns_findings_without_raising() -> None:
    # The caller logs one structured warning per affected artifact (S22).
    document = _mcp_document(env={"GH_TOKEN": "hunter2"})

    findings = enforce_secret_policy(document, SECRET_POLICY_ACCEPTED, artifact_label="github")

    assert [finding.field_path for finding in findings] == ["env.GH_TOKEN"]


def test_an_unknown_policy_is_a_recipe_error() -> None:
    document = _mcp_document()

    with pytest.raises(ValueError, match="secret_policy"):
        enforce_secret_policy(document, "secrets_maybe", artifact_label="github")
