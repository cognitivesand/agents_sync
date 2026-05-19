"""Parse/render tests for the v0.5 ``mcp_server`` customization_type."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents_sync.config import ConfigError, platform_defaults, validate_config
from agents_sync.mcp_secret_policy import McpSecretLeakError
from agents_sync.mcp_server_io import (
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
    assert extract_pair_id_from_mcp_server_json("{") is None


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

    assert field_name in [finding.field_path for finding in exc.value.findings]


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


def test_invalid_mcp_secret_policy_rejected_by_config(tmp_path: Path):
    config = platform_defaults(os_name="posix", env={}, home=tmp_path)
    config["state_path"] = str(tmp_path / "state" / "state.json")
    config["mcp_server_secret_policy"] = "leaky"

    with pytest.raises(ConfigError, match="mcp_server_secret_policy"):
        validate_config(config)


def test_default_config_uses_refuse_policy():
    defaults = platform_defaults(os_name="posix", env={}, home=Path("/home/tester"))

    assert defaults["mcp_server_secret_policy"] == "refuse"
