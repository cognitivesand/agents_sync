"""End-to-end coverage for real Claude/Codex/OpenCode MCP adapters."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration  # audit slice 10 · TQ-01

import json
import tomllib
from pathlib import Path

from agents_sync.sync import Syncer


def _config(tmp_path: Path) -> dict[str, object]:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for sub in (
        "ca", "cc", "cs", "cr",
        "xa", "xp", "xs", "xr",
        "as",
        "ga", "gc", "gs", "gr",
        "oa", "oc", "os", "or",
    ):
        (tmp_path / sub).mkdir()
    return {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "ca"),
        "claude_commands_dir": str(tmp_path / "cc"),
        "claude_skills_dir": str(tmp_path / "cs"),
        "claude_rules_dir": str(tmp_path / "cr"),
        "claude_mcp_servers_file": str(tmp_path / "claude-mcp.json"),
        "codex_agents_dir": str(tmp_path / "xa"),
        "codex_prompts_dir": str(tmp_path / "xp"),
        "codex_skills_dir": str(tmp_path / "xs"),
        "codex_rules_dir": str(tmp_path / "xr"),
        "codex_config_file": str(tmp_path / "codex-config.toml"),
        "antigravity_skills_dir": str(tmp_path / "as"),
        "antigravity_enabled": True,
        "gemini_cli_agents_dir": str(tmp_path / "ga"),
        "gemini_cli_commands_dir": str(tmp_path / "gc"),
        "gemini_cli_skills_dir": str(tmp_path / "gs"),
        "gemini_cli_rules_dir": str(tmp_path / "gr"),
        "gemini_cli_settings_file": str(tmp_path / "gemini-settings.json"),
        "gemini_cli_enabled": True,
        "opencode_agents_dir": str(tmp_path / "oa"),
        "opencode_commands_dir": str(tmp_path / "oc"),
        "opencode_skills_dir": str(tmp_path / "os"),
        "opencode_rules_dir": str(tmp_path / "or"),
        "opencode_config_file": str(tmp_path / "opencode.json"),
        "opencode_enabled": True,
        "mcp_server_secret_policy": "refuse",
    }


def test_claude_mcp_servers_project_to_codex_gemini_and_opencode(tmp_path: Path):
    config = _config(tmp_path)
    claude_file = Path(str(config["claude_mcp_servers_file"]))
    claude_file.write_text(
        json.dumps({
            "mcpServers": {
                "docs": {
                    "type": "http",
                    "url": "https://developers.openai.com/mcp",
                },
                "everything": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-everything"],
                },
            },
        }),
        encoding="utf-8",
    )

    Syncer(config).sync_once()

    codex = tomllib.loads(Path(str(config["codex_config_file"])).read_text())
    gemini = json.loads(Path(str(config["gemini_cli_settings_file"])).read_text())
    opencode = json.loads(Path(str(config["opencode_config_file"])).read_text())

    assert codex["mcp_servers"]["docs"]["url"] == "https://developers.openai.com/mcp"
    assert codex["mcp_servers"]["everything"]["command"] == "npx"
    assert codex["mcp_servers"]["everything"]["args"] == [
        "-y",
        "@modelcontextprotocol/server-everything",
    ]
    assert gemini["mcpServers"]["docs"]["httpUrl"] == "https://developers.openai.com/mcp"
    assert gemini["mcpServers"]["everything"]["command"] == "npx"
    assert gemini["mcpServers"]["everything"]["args"] == [
        "-y",
        "@modelcontextprotocol/server-everything",
    ]
    assert opencode["mcp"]["docs"]["type"] == "remote"
    assert opencode["mcp"]["docs"]["url"] == "https://developers.openai.com/mcp"
    assert opencode["mcp"]["everything"]["type"] == "local"
    assert opencode["mcp"]["everything"]["command"] == [
        "npx",
        "-y",
        "@modelcontextprotocol/server-everything",
    ]


def test_claude_http_headers_project_to_codex_and_opencode(tmp_path: Path):
    config = _config(tmp_path)
    claude_file = Path(str(config["claude_mcp_servers_file"]))
    claude_file.write_text(
        json.dumps({
            "mcpServers": {
                "figma": {
                    "type": "http",
                    "url": "https://mcp.figma.com/mcp",
                    "headers": {
                        "Authorization": "Bearer ${FIGMA_OAUTH_TOKEN}",
                        "X-Figma-Region": "us-east-1",
                    },
                },
            },
        }),
        encoding="utf-8",
    )

    Syncer(config).sync_once()

    codex = tomllib.loads(Path(str(config["codex_config_file"])).read_text())
    gemini = json.loads(Path(str(config["gemini_cli_settings_file"])).read_text())
    opencode = json.loads(Path(str(config["opencode_config_file"])).read_text())

    codex_figma = codex["mcp_servers"]["figma"]
    assert codex_figma["bearer_token_env_var"] == "FIGMA_OAUTH_TOKEN"
    assert codex_figma["http_headers"]["X-Figma-Region"] == "us-east-1"
    gemini_headers = gemini["mcpServers"]["figma"]["headers"]
    assert gemini_headers["Authorization"] == "Bearer ${FIGMA_OAUTH_TOKEN}"
    assert gemini_headers["X-Figma-Region"] == "us-east-1"
    opencode_headers = opencode["mcp"]["figma"]["headers"]
    assert opencode_headers["Authorization"] == "Bearer {env:FIGMA_OAUTH_TOKEN}"
    assert opencode_headers["X-Figma-Region"] == "us-east-1"


def test_codex_http_headers_project_to_claude_and_opencode(tmp_path: Path):
    config = _config(tmp_path)
    codex_file = Path(str(config["codex_config_file"]))
    codex_file.write_text(
        "\n".join((
            "[mcp_servers.figma]",
            'url = "https://mcp.figma.com/mcp"',
            'bearer_token_env_var = "FIGMA_OAUTH_TOKEN"',
            "",
            "[mcp_servers.figma.http_headers]",
            'X-Figma-Region = "us-east-1"',
            "",
            "[mcp_servers.figma.env_http_headers]",
            'X-Trace = "TRACE_TOKEN"',
            "",
        )),
        encoding="utf-8",
    )

    Syncer(config).sync_once()

    claude = json.loads(Path(str(config["claude_mcp_servers_file"])).read_text())
    gemini = json.loads(Path(str(config["gemini_cli_settings_file"])).read_text())
    opencode = json.loads(Path(str(config["opencode_config_file"])).read_text())

    claude_headers = claude["mcpServers"]["figma"]["headers"]
    assert claude_headers["Authorization"] == "Bearer ${FIGMA_OAUTH_TOKEN}"
    assert claude_headers["X-Figma-Region"] == "us-east-1"
    assert claude_headers["X-Trace"] == "${TRACE_TOKEN}"
    gemini_headers = gemini["mcpServers"]["figma"]["headers"]
    assert gemini_headers["Authorization"] == "Bearer ${FIGMA_OAUTH_TOKEN}"
    assert gemini_headers["X-Figma-Region"] == "us-east-1"
    assert gemini_headers["X-Trace"] == "${TRACE_TOKEN}"
    opencode_headers = opencode["mcp"]["figma"]["headers"]
    assert opencode_headers["Authorization"] == "Bearer {env:FIGMA_OAUTH_TOKEN}"
    assert opencode_headers["X-Figma-Region"] == "us-east-1"
    assert opencode_headers["X-Trace"] == "{env:TRACE_TOKEN}"


def test_opencode_local_mcp_command_array_projects_to_claude_and_codex(tmp_path: Path):
    config = _config(tmp_path)
    opencode_file = Path(str(config["opencode_config_file"]))
    opencode_file.write_text(
        json.dumps({
            "mcp": {
                "everything": {
                    "type": "local",
                    "command": ["npx", "-y", "@modelcontextprotocol/server-everything"],
                    "environment": {"SAFE_MODE": "${env:SAFE_MODE}"},
                    "enabled": True,
                },
            },
        }),
        encoding="utf-8",
    )

    Syncer(config).sync_once()

    claude = json.loads(Path(str(config["claude_mcp_servers_file"])).read_text())
    codex = tomllib.loads(Path(str(config["codex_config_file"])).read_text())
    gemini = json.loads(Path(str(config["gemini_cli_settings_file"])).read_text())

    assert claude["mcpServers"]["everything"]["command"] == "npx"
    assert claude["mcpServers"]["everything"]["args"] == [
        "-y",
        "@modelcontextprotocol/server-everything",
    ]
    assert claude["mcpServers"]["everything"]["env"] == {
        "SAFE_MODE": "${SAFE_MODE}",
    }
    assert codex["mcp_servers"]["everything"]["command"] == "npx"
    assert codex["mcp_servers"]["everything"]["args"] == [
        "-y",
        "@modelcontextprotocol/server-everything",
    ]
    assert gemini["mcpServers"]["everything"]["command"] == "npx"
    assert gemini["mcpServers"]["everything"]["args"] == [
        "-y",
        "@modelcontextprotocol/server-everything",
    ]
    assert gemini["mcpServers"]["everything"]["env"] == {
        "SAFE_MODE": "${SAFE_MODE}",
    }


def test_opencode_jsonc_mcp_file_projects_to_claude_and_codex(tmp_path: Path):
    config = _config(tmp_path)
    opencode_file = Path(str(config["opencode_config_file"]))
    opencode_file.write_text(
        """
        {
          // OpenCode accepts JSONC config files.
          "mcp": {
            "context7": {
              "type": "remote",
              "url": "https://mcp.context7.com/mcp",
            },
          },
        }
        """,
        encoding="utf-8",
    )

    Syncer(config).sync_once()

    claude = json.loads(Path(str(config["claude_mcp_servers_file"])).read_text())
    codex = tomllib.loads(Path(str(config["codex_config_file"])).read_text())
    gemini = json.loads(Path(str(config["gemini_cli_settings_file"])).read_text())
    assert claude["mcpServers"]["context7"]["url"] == "https://mcp.context7.com/mcp"
    assert codex["mcp_servers"]["context7"]["url"] == "https://mcp.context7.com/mcp"
    assert gemini["mcpServers"]["context7"]["httpUrl"] == "https://mcp.context7.com/mcp"


def test_gemini_mcp_servers_project_to_claude_codex_and_opencode(tmp_path: Path):
    config = _config(tmp_path)
    gemini_file = Path(str(config["gemini_cli_settings_file"]))
    gemini_file.write_text(
        json.dumps({
            "ui": {"theme": "GitHub"},
            "mcpServers": {
                "docs": {
                    "httpUrl": "https://example.test/mcp",
                    "headers": {"Authorization": "Bearer $DOCS_TOKEN"},
                    "trust": False,
                    "includeTools": ["search"],
                },
                "events": {
                    "url": "https://example.test/sse",
                },
            },
        }),
        encoding="utf-8",
    )

    Syncer(config).sync_once()

    gemini = json.loads(gemini_file.read_text(encoding="utf-8"))
    claude = json.loads(Path(str(config["claude_mcp_servers_file"])).read_text())
    codex = tomllib.loads(Path(str(config["codex_config_file"])).read_text())
    opencode = json.loads(Path(str(config["opencode_config_file"])).read_text())

    assert gemini["ui"] == {"theme": "GitHub"}
    assert gemini["mcpServers"]["docs"]["httpUrl"] == "https://example.test/mcp"
    assert gemini["mcpServers"]["docs"]["headers"]["Authorization"] == (
        "Bearer ${DOCS_TOKEN}"
    )
    assert gemini["mcpServers"]["docs"]["trust"] is False
    assert gemini["mcpServers"]["docs"]["includeTools"] == ["search"]
    assert gemini["mcpServers"]["events"]["url"] == "https://example.test/sse"
    assert "httpUrl" not in gemini["mcpServers"]["events"]

    assert claude["mcpServers"]["docs"]["type"] == "http"
    assert claude["mcpServers"]["docs"]["url"] == "https://example.test/mcp"
    assert claude["mcpServers"]["events"]["type"] == "sse"
    assert claude["mcpServers"]["events"]["url"] == "https://example.test/sse"
    assert codex["mcp_servers"]["docs"]["url"] == "https://example.test/mcp"
    assert opencode["mcp"]["docs"]["type"] == "remote"
    assert opencode["mcp"]["docs"]["url"] == "https://example.test/mcp"


def test_real_adapters_honor_configured_secret_policy(tmp_path: Path):
    """Under the post-2026-05-22 binary policy, ``secrets_refused`` (the
    default) blocks any cross-tool projection of a literal-bearing MCP
    server artifact. The redact mode is gone — its legacy in-place
    placeholder mutation is replaced by full refusal at parse time, so the
    literal never enters the canonical store and downstream adapters never
    see it.
    """
    config = _config(tmp_path)
    config["mcp_server_secret_policy"] = "secrets_refused"
    claude_file = Path(str(config["claude_mcp_servers_file"]))
    claude_file.write_text(
        json.dumps({
            "mcpServers": {
                "github": {
                    "type": "stdio",
                    "command": "github-mcp",
                    "env": {"GITHUB_TOKEN": "literal-token"},
                },
            },
        }),
        encoding="utf-8",
    )

    Syncer(config).sync_once()

    codex_file = Path(str(config["codex_config_file"]))
    gemini_file = Path(str(config["gemini_cli_settings_file"]))
    opencode_file = Path(str(config["opencode_config_file"]))
    state_path = Path(str(config["state_path"]))

    # The artifact must be refused, so no downstream projection happens
    # and no canonical is written.
    assert not codex_file.exists()
    assert not gemini_file.exists()
    assert not opencode_file.exists()
    canonical_dir = state_path.parent / "canonical"
    canonical_files = list(canonical_dir.glob("*.json")) if canonical_dir.exists() else []
    assert canonical_files == []

    # The source file is left untouched; the literal stays where the user
    # wrote it (this is the point of refusal — no destructive rewrite).
    claude_after = json.loads(claude_file.read_text())
    assert (
        claude_after["mcpServers"]["github"]["env"]["GITHUB_TOKEN"]
        == "literal-token"
    )
    # And the literal never landed in any tool's persisted state.
    state_text = state_path.read_text() if state_path.exists() else ""
    assert "literal-token" not in state_text
