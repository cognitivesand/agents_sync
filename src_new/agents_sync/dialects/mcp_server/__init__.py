"""The mcp_server dialect — one keyed-map slot interpreted as an MCP server (pure, no I/O).

An mcp_server artifact is one slot in a shared keyed-map file, so this dialect reuses
``keyed_map_slot``'s ``read_slot`` / ``write_slot`` for the navigate-and-reassemble (sibling
preservation) and adds the wire interpretation a flat field map cannot express: transport
canonicalization + an alias map (``local``→``stdio``), transport inference (``command``→stdio,
``url``→http, or — for a transport-field-less tool — the url-field SPELLING via
``transport_by_url_field``: gemini's ``httpUrl``→http, ``url``→sse), the stdio fields
(``command``/``args`` with array-form split, ``env``, ``cwd``), the http/sse fields (``url``
with alias detection, verbatim ``headers``/``auth`` maps), the transport-independent fields
(``timeout``, ``disabled``, ``always_allow``), suppression of the transport and inner-name
fields a tool does not carry (``transport_render_field``/``name_render_field`` = ``None``), and
preservation of each tool's own field spelling under ``per_tool_only`` (unknown keys under
``per_tool_extra``).

Package layout (split to respect the 300-line limit):
- ``_shared`` — the field-spelling vocabulary, transport canonicalization, env-reference
  helpers, and value coercion that the other modules share.
- ``_carriers`` — codex's http auth carrier transform (``http_headers`` / ``env_http_headers``
  / ``bearer_token_env_var`` ↔ one canonical ``headers`` map), recipe-gated (S20 increment 5).
- ``parse`` — fold a slot into the canonical (plus ``extract_id``, the id-in-isolation probe).
- ``render`` — render the canonical back onto its slot.

The header carriers (S20 increment 5) and the per-tool inline ``env_reference_style`` (the
``${env:NAME}``↔``${NAME}``↔``{env:NAME}`` conversion across env/auth/headers, S20 increment 7)
are now handled here as per-tool recipe DATA (``McpSpellingRecipe``). The mcp secret policy
runs in the read phase (S18), not the dialect.
"""

from __future__ import annotations

from agents_sync.dialects.mcp_server.parse import extract_id, parse
from agents_sync.dialects.mcp_server.render import render

__all__ = ["extract_id", "parse", "render"]
