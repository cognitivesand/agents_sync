"""The mcp_server dialect — one keyed-map slot interpreted as an MCP server (pure, no I/O).

An mcp_server artifact is one slot in a shared keyed-map file, so this dialect reuses
``keyed_map_slot``'s ``read_slot`` / ``write_slot`` for the navigate-and-reassemble (sibling
preservation) and adds the wire interpretation a flat field map cannot express: transport
canonicalization + an alias map (``local``→``stdio``), transport inference (``command``→stdio),
the stdio fields (``command``/``args`` with array-form split, ``env``, ``cwd``, ``timeout``,
``disabled``, ``always_allow``), and preservation of each tool's own field spelling under
``per_tool_only`` (unknown keys under ``per_tool_extra``).

Package layout (split at S13b to respect the 300-line limit and set up http):
- ``_shared`` — the field-spelling vocabulary + transport canonicalization both sides use.
- ``parse`` — fold a slot into the canonical (plus ``extract_id``, the id-in-isolation probe).
- ``render`` — render the canonical back onto its slot.

stdio is S13a; http/sse (url/headers/auth) is S13c. The env-reference syntax conversion, the
per-tool ``env_reference_style``, and the dedicated header carriers are per-tool recipe data
(S20); the mcp secret policy runs in the read phase (S18). Neither is in the dialect.
"""

from __future__ import annotations

from agents_sync.dialects.mcp_server.parse import extract_id, parse
from agents_sync.dialects.mcp_server.render import render

__all__ = ["extract_id", "parse", "render"]
