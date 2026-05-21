"""Parse/render tests for the v0.5 ``mcp_server`` customization_type."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from agents_sync.config import ConfigError, platform_defaults, validate_config
from agents_sync.mcp_secret_policy import (
    McpSecretLeakError,
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


def test_mcp_secret_policy_redact_rewrites_secret_extra_before_persisting():
    canonical = parse_mcp_server_json(
        json.dumps({
            "name": "licensed",
            "command": "licensed-mcp",
            "license_key": "literal-license-key",
        }),
        None,
        agentic_tool_name="alpha",
        secret_policy="redact",
    )

    placeholder = "${env:AGENTS_SYNC_REDACTED_1}"
    rendered = json.loads(render_mcp_server_json(
        canonical,
        None,
        agentic_tool_name="alpha",
        secret_policy="redact",
    ))

    assert canonical["per_agentic_tool_extra"]["alpha"] == {
        "license_key": placeholder,
    }
    assert canonical["secret_redactions"] == [{
        "field_path": "license_key",
        "original_env_var": None,
        "placeholder_env_var": "AGENTS_SYNC_REDACTED_1",
    }]
    assert rendered["license_key"] == placeholder
    assert "literal-license-key" not in json.dumps(canonical)
    assert "literal-license-key" not in json.dumps(rendered)


def test_mcp_secret_policy_redact_rewrites_and_records_redactions():
    canonical = parse_mcp_server_json(
        json.dumps({
            "name": "github",
            "command": "gh",
            "env": {"GITHUB_TOKEN": "ghp_literal"},
        }),
        None,
        agentic_tool_name="alpha",
        secret_policy="redact",
    )

    assert canonical["env"]["GITHUB_TOKEN"] == "${env:AGENTS_SYNC_REDACTED_1}"
    assert canonical["secret_redactions"] == [{
        "field_path": "env.GITHUB_TOKEN",
        "original_env_var": None,
        "placeholder_env_var": "AGENTS_SYNC_REDACTED_1",
    }]

    rendered = json.loads(render_mcp_server_json(
        canonical,
        None,
        agentic_tool_name="alpha",
        secret_policy="redact",
    ))
    assert rendered["env"]["GITHUB_TOKEN"] == "${env:AGENTS_SYNC_REDACTED_1}"


def test_mcp_secret_policy_permissive_logs_warning(caplog: pytest.LogCaptureFixture):
    with caplog.at_level("WARNING"):
        canonical = parse_mcp_server_json(
            json.dumps({
                "name": "github",
                "command": "gh",
                "env": {"GITHUB_TOKEN": "ghp_literal"},
            }),
            None,
            agentic_tool_name="alpha",
            secret_policy="permissive",
        )

    assert canonical["env"]["GITHUB_TOKEN"] == "ghp_literal"
    assert any("MCP server secret policy permissive" in r.message for r in caplog.records)


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


def test_codex_env_var_fields_redact_literal_values_as_names():
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

    canonical = parse_mcp_server_json(
        text,
        None,
        agentic_tool_name="codex",
        dialect=dialect,
        slot_format="toml",
        secret_policy="redact",
    )
    rendered = tomllib.loads(render_mcp_server_json(
        canonical,
        text,
        agentic_tool_name="codex",
        dialect=dialect,
        slot_format="toml",
        secret_policy="redact",
    ))

    assert canonical["headers"] == {
        "Authorization": "Bearer ${env:AGENTS_SYNC_REDACTED_1}",
        "X-Auth": "${env:AGENTS_SYNC_REDACTED_2}",
        "X-Trace": "${env:TRACE_TOKEN}",
    }
    assert canonical["secret_redactions"] == [
        {
            "field_path": "bearer_token_env_var",
            "original_env_var": None,
            "placeholder_env_var": "AGENTS_SYNC_REDACTED_1",
        },
        {
            "field_path": "env_http_headers.X-Auth",
            "original_env_var": None,
            "placeholder_env_var": "AGENTS_SYNC_REDACTED_2",
        },
    ]
    assert rendered["bearer_token_env_var"] == "AGENTS_SYNC_REDACTED_1"
    assert rendered["env_http_headers"] == {
        "X-Auth": "AGENTS_SYNC_REDACTED_2",
        "X-Trace": "TRACE_TOKEN",
    }


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


def test_invalid_mcp_secret_policy_rejected_by_config(tmp_path: Path):
    config = platform_defaults(os_name="posix", env={}, home=tmp_path)
    config["state_path"] = str(tmp_path / "state" / "state.json")
    config["mcp_server_secret_policy"] = "leaky"

    with pytest.raises(ConfigError, match="mcp_server_secret_policy"):
        validate_config(config)


def test_default_config_uses_refuse_policy():
    defaults = platform_defaults(os_name="posix", env={}, home=Path("/home/tester"))

    assert defaults["mcp_server_secret_policy"] == "refuse"
