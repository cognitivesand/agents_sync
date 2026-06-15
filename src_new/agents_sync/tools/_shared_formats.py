"""Shared surface-format builders for the tool data modules (pure data helpers).

The common field map (``name``/``description``) is shared by every surface; a tool's own
agent spellings (model/effort/tools, claude ``disallowedTools``/``permissionMode``, codex
``model_reasoning_effort``) are appended per tool via ``extra_known_fields`` (S20 increment
2). The mcp spellings (opencode ``environment`` + inverted ``enabled``, array command,
claude ``oauth``, env-reference styles, header carriers) are increment 3 — they need new
recipe knobs, not just an extra field map.
"""

from __future__ import annotations

from agents_sync.domain_model.tool_surface import SurfaceFormat

_COMMON_KNOWN_FIELDS = (("name", "name"), ("description", "description"))
_ID_FIELD = "pair_id"


def markdown_surface_format(
    extra_known_fields: tuple[tuple[str, str], ...] = (),
) -> SurfaceFormat:
    """A markdown front-matter surface (agents, commands, rule files).

    ``extra_known_fields`` are a tool's own (front-matter key → canonical attribute)
    spellings, appended to the shared name/description map — e.g. claude's agent surface
    adds ``permissionMode`` → ``permission_mode`` (S20 increment 2)."""
    return SurfaceFormat(
        dialect="markdown_frontmatter",
        id_field=_ID_FIELD,
        known_fields=_COMMON_KNOWN_FIELDS + extra_known_fields,
    )


def structured_text_surface_format(
    file_format: str, extra_known_fields: tuple[tuple[str, str], ...] = ()
) -> SurfaceFormat:
    """A whole-file structured-text surface (codex TOML agents, gemini TOML commands).

    ``extra_known_fields`` carry the tool's own field spellings (e.g. codex's
    ``model_reasoning_effort`` → ``effort``), appended to the shared map."""
    return SurfaceFormat(
        dialect="structured_text",
        id_field=_ID_FIELD,
        known_fields=_COMMON_KNOWN_FIELDS + extra_known_fields,
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
