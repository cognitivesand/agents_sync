"""Per-tool AgenticToolSpec factories.

Each ``build_*_spec`` returns the descriptor for one agentic tool
(claude, codex, cursor, antigravity, opencode). The factories share two
helpers — :mod:`_rules_factory` for the per-tool global-rules cell and
:mod:`_mcp_server_factory` for the JSON/TOML MCP-server cell.
"""
from __future__ import annotations

from agents_sync.tool_specs.antigravity import build_antigravity_spec
from agents_sync.tool_specs.claude import build_claude_spec
from agents_sync.tool_specs.codex import build_codex_spec
from agents_sync.tool_specs.cursor import build_cursor_spec
from agents_sync.tool_specs.gemini_cli import build_gemini_cli_spec
from agents_sync.tool_specs.opencode import build_opencode_spec

__all__ = [
    "build_antigravity_spec",
    "build_claude_spec",
    "build_codex_spec",
    "build_cursor_spec",
    "build_gemini_cli_spec",
    "build_opencode_spec",
]
