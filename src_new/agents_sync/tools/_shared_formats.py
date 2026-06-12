"""Shared surface-format builders for the tool data modules (pure data helpers).

The common field map (``name``/``description``) is the S20 increment-1 baseline;
per-tool field maps and spellings (model/effort/tools, opencode ``environment`` +
inverted ``enabled``, env-reference styles, header carriers) are the next
increments — each will move format details into the owning tool module.
"""

from __future__ import annotations

from agents_sync.domain_model.tool_surface import SurfaceFormat

_COMMON_KNOWN_FIELDS = (("name", "name"), ("description", "description"))
_ID_FIELD = "pair_id"


def markdown_surface_format() -> SurfaceFormat:
    """A markdown front-matter surface (agents, commands, rule files)."""
    return SurfaceFormat(
        dialect="markdown_frontmatter",
        id_field=_ID_FIELD,
        known_fields=_COMMON_KNOWN_FIELDS,
    )


def structured_text_surface_format(file_format: str) -> SurfaceFormat:
    """A whole-file structured-text surface (codex TOML agents, gemini TOML commands)."""
    return SurfaceFormat(
        dialect="structured_text",
        id_field=_ID_FIELD,
        known_fields=_COMMON_KNOWN_FIELDS,
        file_format=file_format,
    )


def mcp_surface_format(map_key_path: tuple[str, ...], file_format: str) -> SurfaceFormat:
    """One mcp-server slot in the tool's shared config file."""
    return SurfaceFormat(
        dialect="mcp_server",
        id_field=_ID_FIELD,
        map_key_path=map_key_path,
        file_format=file_format,
    )
