"""Parse/render tests for the v0.5 ``mcp_server`` customization_type."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents_sync.config import ConfigError, platform_defaults, validate_config
from agents_sync.mcp_secret_policy import (
    McpSecretLeakError,
    bearer_env_reference_name,
    env_reference_name,
    find_mcp_secret_literals,
    format_env_reference,
)
from agents_sync.mcp_server_io import (
    McpServerDialect,
    extract_pair_id_from_mcp_server_json,
    parse_mcp_server_json,
    render_mcp_server_json,
)


def test_parse_stdio_mcp_server_json_round_trips_pair_id_and_extras():
    text = json.dumps({
        "pair_id": "00000000-0000-4000-8000-000000000001",
        "name": "filesystem",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        "cwd": "/work",
        "disabled": False,
        "vendor_flag": "keep",
    })

    canonical = parse_mcp_server_json(
        text,
        None,
        agentic_tool_name="alpha",
        artifact_path=Path("mcp.json"),
    )
    rendered = render_mcp_server_json(
        canonical,
        text,
        agentic_tool_name="alpha",
    )
    parsed = parse_mcp_server_json(
        rendered,
        canonical,
        agentic_tool_name="alpha",
    )

    assert canonical["kind"] == "mcp_server"
    assert canonical["pair_id"] == "00000000-0000-4000-8000-000000000001"
    assert canonical["name"] == "filesystem"
    assert canonical["transport"] == "stdio"
    assert canonical["command"] == "npx"
    assert canonical["args"] == ["-y", "@modelcontextprotocol/server-filesystem"]
    assert canonical["per_agentic_tool_extra"]["alpha"] == {"vendor_flag": "keep"}
    assert json.loads(rendered) == json.loads(text)
    assert parsed == canonical
    assert parsed["per_agentic_tool_extra"]["alpha"] == {"vendor_flag": "keep"}


def test_parse_http_aliases_preserve_tool_spellings_on_render():
    text = json.dumps({
        "pair_id": "00000000-0000-4000-8000-000000000001",
        "name": "docs",
        "type": "remote",
        "httpUrl": "https://example.test/mcp",
        "headers": {"X-Request-ID": "abc"},
        "alwaysAllow": ["search"],
    })

    canonical = parse_mcp_server_json(text, None, agentic_tool_name="beta")
    rendered = json.loads(render_mcp_server_json(
        canonical,
        text,
        agentic_tool_name="beta",
    ))

    assert canonical["transport"] == "http"
    assert canonical["url"] == "https://example.test/mcp"
    assert canonical["always_allow"] == ["search"]
    assert rendered["type"] == "remote"
    assert rendered["httpUrl"] == "https://example.test/mcp"
    assert rendered["alwaysAllow"] == ["search"]


def test_gemini_cli_dialect_distinguishes_http_url_from_sse_url():
    dialect = McpServerDialect(
        render_name_field=False,
        render_transport_field=False,
        url_fields=("httpUrl", "url", "serverUrl"),
        transport_from_fields=(
            ("httpUrl", "http"),
            ("url", "sse"),
            ("command", "stdio"),
        ),
        url_render_fields=(
            ("http", "httpUrl"),
            ("streamable-http", "httpUrl"),
            ("sse", "url"),
        ),
        auth_fields=("oauth", "auth"),
        auth_render_field="oauth",
        env_reference_style="gemini",
    )
    http_text = json.dumps({
        "name": "docs",
        "httpUrl": "https://example.test/mcp",
        "headers": {"Authorization": "Bearer $DOCS_TOKEN"},
        "trust": False,
        "includeTools": ["search"],
    })
    sse_text = json.dumps({
        "name": "events",
        "url": "https://example.test/sse",
    })

    http = parse_mcp_server_json(
        http_text,
        None,
        agentic_tool_name="gemini_cli",
        dialect=dialect,
    )
    sse = parse_mcp_server_json(
        sse_text,
        None,
        agentic_tool_name="gemini_cli",
        dialect=dialect,
    )
    rendered_http = json.loads(render_mcp_server_json(
        http,
        None,
        agentic_tool_name="gemini_cli",
        dialect=dialect,
    ))
    rendered_sse = json.loads(render_mcp_server_json(
        sse,
        None,
        agentic_tool_name="gemini_cli",
        dialect=dialect,
    ))

    assert http["transport"] == "http"
    assert http["headers"]["Authorization"] == "Bearer ${env:DOCS_TOKEN}"
    assert http["per_agentic_tool_extra"]["gemini_cli"] == {
        "trust": False,
        "includeTools": ["search"],
    }
    assert rendered_http["httpUrl"] == "https://example.test/mcp"
    assert rendered_http["headers"]["Authorization"] == "Bearer ${DOCS_TOKEN}"
    assert "transport" not in rendered_http
    assert "type" not in rendered_http
    assert sse["transport"] == "sse"
    assert rendered_sse["url"] == "https://example.test/sse"
    assert "httpUrl" not in rendered_sse


def test_extract_pair_id_from_mcp_server_json():
    pair_id = extract_pair_id_from_mcp_server_json(json.dumps({
        "pair_id": "00000000-0000-4000-8000-000000000001",
    }))

    assert pair_id == "00000000-0000-4000-8000-000000000001"
    assert extract_pair_id_from_mcp_server_json(json.dumps({"name": "no-id"})) is None
    with pytest.raises(json.JSONDecodeError):
        extract_pair_id_from_mcp_server_json("{")
    with pytest.raises(ValueError, match="must be an object"):
        extract_pair_id_from_mcp_server_json(json.dumps(["not", "an", "object"]))


def test_json_slot_format_does_not_fallback_to_toml():
    text = 'name = "filesystem"\ncommand = "npx"\n'
    dialect = McpServerDialect(render_transport_field=False)

    with pytest.raises(json.JSONDecodeError):
        parse_mcp_server_json(text, None, agentic_tool_name="alpha")
    with pytest.raises(json.JSONDecodeError):
        extract_pair_id_from_mcp_server_json(text)

    canonical = parse_mcp_server_json(
        text,
        None,
        agentic_tool_name="alpha",
        dialect=dialect,
        slot_format="toml",
    )
    rendered = render_mcp_server_json(
        canonical,
        None,
        agentic_tool_name="alpha",
        dialect=dialect,
        slot_format="toml",
    )
    reparsed = parse_mcp_server_json(
        rendered,
        canonical,
        agentic_tool_name="alpha",
        dialect=dialect,
        slot_format="toml",
    )

    assert canonical["name"] == "filesystem"
    assert canonical["command"] == "npx"
    assert 'command = "npx"' in rendered
    assert reparsed == canonical


@pytest.mark.parametrize("transport", ["sse", "streamable-http"])
def test_remote_mcp_transports_round_trip(transport: str):
    text = json.dumps({
        "pair_id": "00000000-0000-4000-8000-000000000002",
        "name": f"{transport}-server",
        "transport": transport,
        "url": f"https://example.test/{transport}",
    })

    canonical = parse_mcp_server_json(text, None, agentic_tool_name="alpha")
    rendered = render_mcp_server_json(canonical, text, agentic_tool_name="alpha")
    reparsed = parse_mcp_server_json(
        rendered,
        canonical,
        agentic_tool_name="alpha",
    )

    assert canonical["transport"] == transport
    assert canonical["url"] == f"https://example.test/{transport}"
    assert json.loads(rendered)["transport"] == transport
    assert reparsed == canonical


def test_unknown_mcp_transport_is_rejected():
    with pytest.raises(ValueError, match="unsupported mcp_server transport"):
        parse_mcp_server_json(
            json.dumps({
                "name": "strange",
                "transport": "websocket",
                "url": "https://example.test/mcp",
            }),
            None,
            agentic_tool_name="alpha",
        )


def test_parse_reuses_prior_pair_id_when_slot_omits_pair_id():
    prior = parse_mcp_server_json(
        json.dumps({
            "pair_id": "00000000-0000-4000-8000-000000000003",
            "name": "filesystem",
            "transport": "stdio",
            "command": "npx",
        }),
        None,
        agentic_tool_name="alpha",
    )

    canonical = parse_mcp_server_json(
        json.dumps({
            "name": "filesystem",
            "transport": "stdio",
            "command": "node",
            "args": ["server.js"],
        }),
        prior,
        agentic_tool_name="alpha",
    )

    assert canonical["pair_id"] == "00000000-0000-4000-8000-000000000003"
    assert canonical["command"] == "node"
    assert canonical["args"] == ["server.js"]


@pytest.mark.parametrize(
    "field_name,slot",
    [
        ("env.API_KEY", {"name": "a", "command": "cmd", "env": {"API_KEY": "sk-live"}}),
        (
            "headers.Authorization",
            {
                "name": "a",
                "transport": "http",
                "url": "https://example.test",
                "headers": {"Authorization": "Bearer secret"},
            },
        ),
        (
            "headers.X-API-Key",
            {
                "name": "a",
                "transport": "http",
                "url": "https://example.test",
                "headers": {"X-API-Key": "secret"},
            },
        ),
        (
            "auth.client_secret",
            {
                "name": "a",
                "transport": "http",
                "url": "https://example.test",
                "auth": {"client_secret": "secret"},
            },
        ),
        (
            "nested.refresh_token",
            {"name": "a", "command": "cmd", "nested": {"refresh_token": "secret"}},
        ),
    ],
)
def test_mcp_secret_policy_refuse_flags_documented_fields(
    field_name: str,
    slot: dict[str, object],
):
    with pytest.raises(McpSecretLeakError) as exc:
        parse_mcp_server_json(
            json.dumps(slot),
            None,
            agentic_tool_name="alpha",
            secret_policy="refuse",
        )

    assert [finding.field_path for finding in exc.value.findings] == [field_name]


def test_mcp_secret_policy_refuse_flags_secret_extra_exactly():
    with pytest.raises(McpSecretLeakError) as exc:
        parse_mcp_server_json(
            json.dumps({
                "name": "licensed",
                "command": "licensed-mcp",
                "authentication_blob": "literal-authentication-data",
            }),
            None,
            agentic_tool_name="alpha",
            secret_policy="refuse",
        )

    assert [finding.field_path for finding in exc.value.findings] == [
        "authentication_blob",
    ]


def test_legacy_redact_policy_value_now_refuses_with_deprecation_warning(
    caplog: pytest.LogCaptureFixture,
):
    """The redact mode was removed in the 2026-05-22 hardening rewrite.

    The compatibility shim maps ``redact`` to ``secrets_refused`` (the safer
    default), so existing configs that say ``redact`` now refuse the
    artifact and log one DEPRECATION-WARNING. See US-12 / NFR-15.
    """
    with caplog.at_level("WARNING"):
        with pytest.raises(McpSecretLeakError):
            parse_mcp_server_json(
                json.dumps({
                    "name": "licensed",
                    "command": "licensed-mcp",
                    "license_key": "literal-license-key",
                }),
                None,
                agentic_tool_name="alpha",
                secret_policy="redact",
            )

    deprecation_records = [
        r for r in caplog.records
        if "DEPRECATED" in r.message and "redact" in r.message
    ]
    assert deprecation_records, "expected one DEPRECATED secret_policy log for 'redact'"


def test_secrets_refused_blocks_secret_extra_before_persisting():
    with pytest.raises(McpSecretLeakError) as exc_info:
        parse_mcp_server_json(
            json.dumps({
                "name": "github",
                "command": "gh",
                "env": {"GITHUB_TOKEN": "ghp_literal"},
            }),
            None,
            agentic_tool_name="alpha",
            secret_policy="secrets_refused",
        )

    assert exc_info.value.policy == "secrets_refused"
    assert [f.field_path for f in exc_info.value.findings] == ["env.GITHUB_TOKEN"]


def test_nested_env_block_is_treated_as_secret_path():
    findings = find_mcp_secret_literals({
        "mcpServers": {
            "github": {
                "env": {
                    "GITHUB_TOKEN": "literal-token",
                },
            },
        },
    })

    assert [f.field_path for f in findings] == [
        "mcpServers.github.env.GITHUB_TOKEN",
    ]


def test_parse_refuses_nested_env_secret_at_any_depth():
    with pytest.raises(McpSecretLeakError) as exc_info:
        parse_mcp_server_json(
            json.dumps({
                "name": "github",
                "command": "gh",
                "metadata": {
                    "mcpServers": {
                        "github": {
                            "env": {"GITHUB_TOKEN": "literal-token"},
                        },
                    },
                },
            }),
            None,
            agentic_tool_name="alpha",
        )

    assert [f.field_path for f in exc_info.value.findings] == [
        "metadata.mcpServers.github.env.GITHUB_TOKEN",
    ]


def test_public_mcp_server_io_defaults_use_canonical_secret_policy(
    caplog: pytest.LogCaptureFixture,
):
    text = json.dumps({
        "name": "github",
        "command": "gh",
        "env": {"GITHUB_TOKEN": "${env:GITHUB_TOKEN}"},
    })

    with caplog.at_level("WARNING"):
        canonical = parse_mcp_server_json(
            text,
            None,
            agentic_tool_name="alpha",
        )
        render_mcp_server_json(
            canonical,
            text,
            agentic_tool_name="alpha",
        )

    assert canonical["env"]["GITHUB_TOKEN"] == "${env:GITHUB_TOKEN}"
    assert not any("DEPRECATED secret_policy" in r.message for r in caplog.records)


def test_secrets_accepted_logs_warning_with_new_message(
    caplog: pytest.LogCaptureFixture,
):
    with caplog.at_level("WARNING"):
        canonical = parse_mcp_server_json(
            json.dumps({
                "name": "github",
                "command": "gh",
                "env": {"GITHUB_TOKEN": "ghp_literal"},
            }),
            None,
            agentic_tool_name="alpha",
            secret_policy="secrets_accepted",
        )

    assert canonical["env"]["GITHUB_TOKEN"] == "ghp_literal"
    assert any(
        "secret_policy=secrets_accepted" in r.message for r in caplog.records
    )


def test_env_reference_is_not_treated_as_literal_secret():
    canonical = parse_mcp_server_json(
        json.dumps({
            "name": "github",
            "command": "gh",
            "env": {"GITHUB_TOKEN": "${env:GITHUB_TOKEN}"},
        }),
        None,
        agentic_tool_name="alpha",
    )

    assert canonical["env"]["GITHUB_TOKEN"] == "${env:GITHUB_TOKEN}"
    assert "secret_redactions" not in canonical


def test_uppercase_env_prefix_is_supported_secret_reference():
    slot = {
        "name": "github",
        "transport": "http",
        "url": "https://example.test/mcp",
        "headers": {"Authorization": "Bearer ${ENV:GITHUB_TOKEN}"},
        "env": {"GITHUB_TOKEN": "${ENV:GITHUB_TOKEN}"},
    }

    assert env_reference_name("${ENV:GITHUB_TOKEN}") == "GITHUB_TOKEN"
    assert bearer_env_reference_name("Bearer ${ENV:GITHUB_TOKEN}") == "GITHUB_TOKEN"
    assert find_mcp_secret_literals(slot) == []


def test_mixed_case_and_composite_env_references_are_preserved():
    canonical = parse_mcp_server_json(
        json.dumps({
            "name": "composite",
            "transport": "http",
            "url": "https://example.test",
            "headers": {"Authorization": "Basic ${env:BASIC_AUTH}"},
            "auth": {
                "credentials": "${env:USER}:${env:PASSWORD}",
                "token": "${env:my_token}",
            },
        }),
        None,
        agentic_tool_name="alpha",
        secret_policy="refuse",
    )

    assert canonical["headers"]["Authorization"] == "Basic ${env:BASIC_AUTH}"
    assert canonical["auth"]["credentials"] == "${env:USER}:${env:PASSWORD}"
    assert canonical["auth"]["token"] == "${env:my_token}"
    assert "secret_redactions" not in canonical


def test_canonical_env_reference_formatter_rejects_invalid_names():
    assert format_env_reference("my_token") == "${env:my_token}"
    with pytest.raises(ValueError, match="invalid env var name"):
        format_env_reference("literal-token")
    with pytest.raises(ValueError, match="invalid env var name"):
        format_env_reference("BAD}X")


@pytest.mark.parametrize(
    "field_name",
    [
        "passphrase",
        "credential",
        "credentials",
        "dsn",
        "connection_string",
        "cookie",
        "session",
        "jwt",
        "github_pat",
        "private_key",
    ],
)
def test_mcp_secret_policy_refuse_flags_extended_secret_fields(field_name: str):
    with pytest.raises(McpSecretLeakError) as exc:
        parse_mcp_server_json(
            json.dumps({
                "name": "extended",
                "command": "extended-mcp",
                field_name: "literal-secret-value",
            }),
            None,
            agentic_tool_name="alpha",
            secret_policy="refuse",
        )

    assert [finding.field_path for finding in exc.value.findings] == [field_name]


def test_mcp_secret_policy_refuse_flags_high_confidence_secret_values():
    with pytest.raises(McpSecretLeakError) as exc:
        parse_mcp_server_json(
            json.dumps({
                "name": "value-prefix",
                "command": "value-prefix-mcp",
                "vendor_flag": "sk-" + "a" * 24,
            }),
            None,
            agentic_tool_name="alpha",
            secret_policy="refuse",
        )

    assert [finding.field_path for finding in exc.value.findings] == ["vendor_flag"]


def test_mcp_secret_policy_detects_sensitive_headers_at_any_depth():
    findings = find_mcp_secret_literals({
        "mcpServers": {
            "figma": {
                "http_headers": {"Authorization": "Bearer literal-token"},
                "env_http_headers": {"X-API-Key": "TRACE_TOKEN"},
            },
        },
    })

    assert [finding.field_path for finding in findings] == [
        "mcpServers.figma.http_headers.Authorization",
    ]


def test_bearer_and_env_http_headers_round_trip_with_dialect():
    dialect = McpServerDialect(
        render_transport_field=False,
        headers_fields=("http_headers", "headers"),
        headers_render_field="http_headers",
        env_http_headers_field="env_http_headers",
        bearer_token_env_var_field="bearer_token_env_var",
    )
    text = json.dumps({
        "name": "figma",
        "url": "https://mcp.figma.com/mcp",
        "bearer_token_env_var": "FIGMA_TOKEN",
        "env_http_headers": {"X-Trace": "TRACE_TOKEN"},
        "http_headers": {"X-Figma-Region": "us-east-1"},
    })

    canonical = parse_mcp_server_json(
        text,
        None,
        agentic_tool_name="codex",
        dialect=dialect,
    )
    rendered = json.loads(render_mcp_server_json(
        canonical,
        text,
        agentic_tool_name="codex",
        dialect=dialect,
    ))

    assert canonical["transport"] == "http"
    assert canonical["headers"] == {
        "X-Figma-Region": "us-east-1",
        "X-Trace": "${env:TRACE_TOKEN}",
        "Authorization": "Bearer ${env:FIGMA_TOKEN}",
    }
    assert rendered["bearer_token_env_var"] == "FIGMA_TOKEN"
    assert rendered["env_http_headers"] == {"X-Trace": "TRACE_TOKEN"}
    assert rendered["http_headers"] == {"X-Figma-Region": "us-east-1"}


def test_codex_env_var_fields_reject_literal_values_under_refuse():
    dialect = McpServerDialect(
        render_name_field=False,
        render_transport_field=False,
        headers_fields=("http_headers", "headers"),
        headers_render_field="http_headers",
        env_http_headers_field="env_http_headers",
        bearer_token_env_var_field="bearer_token_env_var",
        auth_render_field=None,
    )
    text = "\n".join((
        'name = "figma"',
        'url = "https://mcp.figma.com/mcp"',
        'bearer_token_env_var = "literal-token"',
        "",
        "[env_http_headers]",
        'X-Auth = "literal-token"',
        "",
    ))

    with pytest.raises(McpSecretLeakError) as exc:
        parse_mcp_server_json(
            text,
            None,
            agentic_tool_name="codex",
            dialect=dialect,
            slot_format="toml",
            secret_policy="refuse",
        )

    assert [finding.field_path for finding in exc.value.findings] == [
        "bearer_token_env_var",
        "env_http_headers.X-Auth",
    ]


def test_codex_env_var_fields_refuse_literal_values_under_secrets_refused():
    """Codex's TOML dialect exposes ``bearer_token_env_var`` and
    ``env_http_headers`` as fields that should hold env-reference *names*,
    not literals. Under the post-2026-05-22 binary policy the redact mode
    is gone; ``secrets_refused`` (default) rejects the artifact outright
    when those fields carry literals. The mixed-content case
    (``X-Trace = "TRACE_TOKEN"``, which IS a valid env-var name) is left
    alone — only the literal-bearing fields trigger the refusal.
    """
    dialect = McpServerDialect(
        render_name_field=False,
        render_transport_field=False,
        headers_fields=("http_headers", "headers"),
        headers_render_field="http_headers",
        env_http_headers_field="env_http_headers",
        bearer_token_env_var_field="bearer_token_env_var",
        auth_render_field=None,
    )
    text = "\n".join((
        'name = "figma"',
        'url = "https://mcp.figma.com/mcp"',
        'bearer_token_env_var = "literal-token"',
        "",
        "[env_http_headers]",
        'X-Auth = "literal-token"',
        'X-Trace = "TRACE_TOKEN"',
        "",
    ))

    with pytest.raises(McpSecretLeakError) as exc_info:
        parse_mcp_server_json(
            text,
            None,
            agentic_tool_name="codex",
            dialect=dialect,
            slot_format="toml",
            secret_policy="secrets_refused",
        )

    refused_fields = {f.field_path for f in exc_info.value.findings}
    assert "bearer_token_env_var" in refused_fields
    assert any(p.startswith("env_http_headers") for p in refused_fields)


def test_codex_env_var_fields_accept_valid_env_names():
    dialect = McpServerDialect(
        render_name_field=False,
        render_transport_field=False,
        headers_fields=("http_headers", "headers"),
        headers_render_field="http_headers",
        env_http_headers_field="env_http_headers",
        bearer_token_env_var_field="bearer_token_env_var",
        auth_render_field=None,
    )
    text = "\n".join((
        'name = "figma"',
        'url = "https://mcp.figma.com/mcp"',
        'bearer_token_env_var = "FIGMA_TOKEN"',
        "",
        "[env_http_headers]",
        'X-Trace = "TRACE_TOKEN"',
        "",
    ))

    canonical = parse_mcp_server_json(
        text,
        None,
        agentic_tool_name="codex",
        dialect=dialect,
        slot_format="toml",
        secret_policy="refuse",
    )

    assert canonical["headers"]["Authorization"] == "Bearer ${env:FIGMA_TOKEN}"
    assert canonical["headers"]["X-Trace"] == "${env:TRACE_TOKEN}"
    assert "secret_redactions" not in canonical


def test_invalid_secret_policy_rejected_by_config(tmp_path: Path):
    config = platform_defaults(os_name="posix", env={}, home=tmp_path)
    config["state_path"] = str(tmp_path / "state" / "state.json")
    config["secret_policy"] = "leaky"

    with pytest.raises(ConfigError, match="secret_policy"):
        validate_config(config)


def test_default_config_uses_secrets_refused_policy():
    defaults = platform_defaults(os_name="posix", env={}, home=Path("/home/tester"))

    assert defaults["secret_policy"] == "secrets_refused"


def test_secret_finding_field_path_distinguishes_list_index_from_dict_key():
    """A literal at servers[0].token renders differently from servers."0".token."""
    list_indexed = find_mcp_secret_literals(
        {"servers": [{"token": "ghp_abcdefghijkl"}]}
    )
    assert len(list_indexed) == 1
    assert list_indexed[0].field_path == "servers[0].token"

    dict_key_zero = find_mcp_secret_literals(
        {"servers": {"0": {"token": "ghp_abcdefghijkl"}}}
    )
    assert len(dict_key_zero) == 1
    assert dict_key_zero[0].field_path == "servers.0.token"


def test_apply_mcp_secret_policy_no_findings_returns_deep_copy():
    """Caller mutating the returned dict must not mutate the input."""
    from agents_sync.mcp_secret_policy import apply_mcp_secret_policy

    original = {"name": "x", "transport": "stdio", "command": "echo"}
    returned = apply_mcp_secret_policy(original, policy="refuse")
    returned["mutated"] = True
    assert "mutated" not in original


def test_apply_mcp_secret_policy_permissive_warning_cache_is_injectable():
    """A caller-provided warning_cache scopes de-duplication memory."""
    from agents_sync.mcp_secret_policy import apply_mcp_secret_policy

    data = {"env": {"GITHUB_TOKEN": "ghp_abcdefghijkl"}}
    cache: set = set()
    apply_mcp_secret_policy(
        data, policy="permissive", artifact="srv-a", warning_cache=cache,
    )
    assert len(cache) == 1
    # Second call with same artifact + fields hits the dedupe path.
    apply_mcp_secret_policy(
        data, policy="permissive", artifact="srv-a", warning_cache=cache,
    )
    assert len(cache) == 1
    # A separate cache instance does not see prior warnings.
    other_cache: set = set()
    apply_mcp_secret_policy(
        data, policy="permissive", artifact="srv-a", warning_cache=other_cache,
    )
    assert len(other_cache) == 1
