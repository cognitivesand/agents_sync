"""JSON parse / render helpers for v0.5 ``mcp_server`` artifacts.

Public API re-exported from the per-concern submodules:
- :mod:`dialect`  — :class:`McpServerDialect`, ``DEFAULT_MCP_SERVER_DIALECT``
- :mod:`parse`    — :func:`parse_mcp_server_json`,
                    :func:`extract_pair_id_from_mcp_server_json`
- :mod:`render`   — :func:`render_mcp_server_json`
"""
from __future__ import annotations

from agents_sync.mcp_server_io.dialect import (
    DEFAULT_MCP_SERVER_DIALECT,
    McpServerDialect,
)
from agents_sync.mcp_server_io.parse import (
    extract_pair_id_from_mcp_server_json,
    parse_mcp_server_json,
)
from agents_sync.mcp_server_io.render import render_mcp_server_json


__all__ = [
    "DEFAULT_MCP_SERVER_DIALECT",
    "McpServerDialect",
    "extract_pair_id_from_mcp_server_json",
    "parse_mcp_server_json",
    "render_mcp_server_json",
]
