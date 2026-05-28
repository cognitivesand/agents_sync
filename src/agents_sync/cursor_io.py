"""Cursor parse / render helpers.

Cursor exposes a file-backed user-level subset that fits the v0.5 adapter
protocol:

- subagents under ``~/.cursor/agents/*.md``;
- Agent Skills under ``~/.cursor/skills/<name>/SKILL.md``;
- rules under ``~/.cursor/rules/*.mdc``;
- slash commands under ``~/.cursor/commands/*.md``;
- MCP servers under ``~/.cursor/mcp.json[mcpServers]``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agents_sync.artifact_names import resolve_artifact_name
from agents_sync.canonical import empty_canonical, new_pair_id
from agents_sync.markdown_yaml_metadata_block import (
    as_string_list,
    extract_pair_id_from_md,
    frontmatter_for_render,
    metadata_subset,
    normalize_markdown_text as _normalize_markdown_text,
    render_markdown_with_metadata_block,
    set_or_remove_empty_metadata_field,
    split_frontmatter,
    strip_bom_prefix as _strip_bom_prefix,
    unknown_metadata_fields,
)
from agents_sync.mcp_server_io import (
    McpServerDialect,
    extract_pair_id_from_mcp_server_json,
    parse_mcp_server_json,
    render_mcp_server_json,
)
from agents_sync.rules_io import (
    extract_pair_id_from_rules_md,
    parse_rules_md,
    render_rules_md,
)
from agents_sync.slash_command_io import slash_command_name_from_path


CURSOR_AGENT_FIELDS = frozenset({
    "pair_id",
    "name",
    "description",
    "model",
    "tools",
})

CURSOR_SKILL_FIELDS = frozenset({
    "pair_id",
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
})

CURSOR_SKILL_ONLY_FIELDS: tuple[str, ...] = (
    "license",
    "compatibility",
    "metadata",
)

CURSOR_COMMAND_PAIR_ID_RE = re.compile(
    r"\A(?:\ufeff)?<!--[ \t]*agents_sync:pair_id=([^ \t>]+)[ \t]*-->"
    r"(?:\r?\n)?"
)

CURSOR_MCP_DIALECT = McpServerDialect(
    render_name_field=False,
    transport_fields=("type", "transport", "transportType"),
    auth_fields=("auth", "oauth"),
    auth_render_field="auth",
    env_reference_style="canonical",
)


# ---------- agents ----------

def extract_pair_id_from_cursor_agent_md(text: str) -> str | None:
    return extract_pair_id_from_md(text)


def parse_cursor_agent_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    del artifact_root
    frontmatter, body = split_frontmatter(text, label="Cursor agent")
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("agent")
    canonical["body"] = body

    name = resolve_artifact_name(
        frontmatter_name=frontmatter.get("name"),
        path_name=artifact_path.stem if artifact_path is not None else None,
        prior_name=canonical.get("name"),
        precedence=("frontmatter", "path", "prior"),
    )
    if name is not None:
        canonical["name"] = name

    if "description" in frontmatter:
        canonical["description"] = str(frontmatter["description"])
    if "model" in frontmatter:
        canonical["model"] = frontmatter["model"]
    if "tools" in frontmatter:
        canonical["tools"] = as_string_list(frontmatter["tools"])

    per_tool_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_tool_only["cursor"] = {}
    canonical["per_agentic_tool_only"] = per_tool_only

    per_tool_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_tool_extra["cursor"] = unknown_metadata_fields(
        frontmatter,
        CURSOR_AGENT_FIELDS,
    )
    canonical["per_agentic_tool_extra"] = per_tool_extra

    if "pair_id" in frontmatter:
        canonical["pair_id"] = str(frontmatter["pair_id"])
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical


def render_cursor_agent_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    frontmatter = frontmatter_for_render(prior_text)
    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = canonical["name"]
    set_or_remove_empty_metadata_field(
        frontmatter, "description", canonical.get("description"),
    )
    set_or_remove_empty_metadata_field(frontmatter, "model", canonical.get("model"))
    set_or_remove_empty_metadata_field(frontmatter, "tools", canonical.get("tools"))

    for key, value in canonical.get("per_agentic_tool_extra", {}).get(
        "cursor", {}
    ).items():
        if key not in CURSOR_AGENT_FIELDS:
            frontmatter[key] = value

    return render_markdown_with_metadata_block(frontmatter, canonical.get("body", ""))


# ---------- skills ----------

def extract_pair_id_from_cursor_skill_md(text: str) -> str | None:
    return extract_pair_id_from_md(text)


def parse_cursor_skill_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    del artifact_root
    frontmatter, body = split_frontmatter(text, label="Cursor SKILL.md")
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("skill")
    canonical["body"] = body

    if "name" in frontmatter:
        canonical["name"] = str(frontmatter["name"])
    elif artifact_path is not None:
        canonical["name"] = artifact_path.name
    if "description" in frontmatter:
        canonical["description"] = str(frontmatter["description"])

    per_tool_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_tool_only["cursor"] = metadata_subset(
        frontmatter,
        CURSOR_SKILL_ONLY_FIELDS,
    )
    canonical["per_agentic_tool_only"] = per_tool_only

    per_tool_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_tool_extra["cursor"] = unknown_metadata_fields(
        frontmatter,
        CURSOR_SKILL_FIELDS,
    )
    canonical["per_agentic_tool_extra"] = per_tool_extra

    if "pair_id" in frontmatter:
        canonical["pair_id"] = str(frontmatter["pair_id"])
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical


def render_cursor_skill_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    frontmatter = frontmatter_for_render(prior_text)
    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = canonical["name"]
    set_or_remove_empty_metadata_field(
        frontmatter, "description", canonical.get("description"),
    )

    cursor_only = canonical.get("per_agentic_tool_only", {}).get("cursor", {})
    for field_name in CURSOR_SKILL_ONLY_FIELDS:
        set_or_remove_empty_metadata_field(
            frontmatter, field_name, cursor_only.get(field_name),
        )

    for key, value in canonical.get("per_agentic_tool_extra", {}).get(
        "cursor", {}
    ).items():
        if key not in CURSOR_SKILL_FIELDS:
            frontmatter[key] = value

    return render_markdown_with_metadata_block(frontmatter, canonical.get("body", ""))


# ---------- rules ----------

def extract_pair_id_from_cursor_rule_mdc(text: str) -> str | None:
    return extract_pair_id_from_rules_md(text)


def parse_cursor_rule_mdc(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    del artifact_root
    return parse_rules_md(
        text,
        prior_canonical,
        agentic_tool_name="cursor",
        artifact_path=artifact_path,
    )


def render_cursor_rule_mdc(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    return render_rules_md(
        canonical,
        prior_text,
        agentic_tool_name="cursor",
    )


# ---------- slash commands ----------

def extract_pair_id_from_cursor_command_md(text: str) -> str | None:
    match = CURSOR_COMMAND_PAIR_ID_RE.match(_normalize_markdown_text(text))
    return match.group(1) if match else None


def parse_cursor_command_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    normalized = _normalize_markdown_text(text)
    match = CURSOR_COMMAND_PAIR_ID_RE.match(normalized)
    pair_id = match.group(1) if match else None
    body = normalized[match.end():] if match else _strip_bom_prefix(normalized)

    canonical = (
        dict(prior_canonical)
        if prior_canonical
        else empty_canonical("slash_command")
    )
    canonical["body"] = body

    if artifact_path is not None:
        canonical["name"] = slash_command_name_from_path(
            artifact_path,
            artifact_root=artifact_root,
        )

    per_tool_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_tool_only["cursor"] = {}
    canonical["per_agentic_tool_only"] = per_tool_only

    per_tool_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_tool_extra["cursor"] = {}
    canonical["per_agentic_tool_extra"] = per_tool_extra

    if pair_id is not None:
        canonical["pair_id"] = pair_id
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical


def render_cursor_command_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    del prior_text
    return (
        f"<!-- agents_sync:pair_id={canonical['pair_id']} -->\n"
        f"{canonical.get('body', '')}"
    )


# ---------- MCP servers ----------

def _slot_text_with_cursor_transport_default(slot_text: str) -> str:
    obj = json.loads(slot_text)
    if not isinstance(obj, dict):
        raise ValueError("Cursor MCP server slot must be an object")
    has_transport = any(
        field in obj for field in CURSOR_MCP_DIALECT.transport_fields
    )
    has_url = any(field in obj for field in CURSOR_MCP_DIALECT.url_fields)
    if not has_transport and has_url:
        obj = dict(obj)
        obj["type"] = "streamable-http"
    return json.dumps(obj)


def extract_pair_id_from_cursor_mcp_server_json(slot_text: str) -> str | None:
    return extract_pair_id_from_mcp_server_json(
        slot_text,
        dialect=CURSOR_MCP_DIALECT,
    )


def parse_cursor_mcp_server_json(
    slot_text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
    secret_policy: str = "secrets_refused",
) -> dict[str, Any]:
    return parse_mcp_server_json(
        _slot_text_with_cursor_transport_default(slot_text),
        prior_canonical,
        agentic_tool_name="cursor",
        artifact_path=artifact_path,
        artifact_root=artifact_root,
        dialect=CURSOR_MCP_DIALECT,
        secret_policy=secret_policy,
    )


def render_cursor_mcp_server_json(
    canonical: dict[str, Any],
    prior_text: str | None = None,
    *,
    secret_policy: str = "secrets_refused",
) -> str:
    return render_mcp_server_json(
        canonical,
        prior_text,
        agentic_tool_name="cursor",
        dialect=CURSOR_MCP_DIALECT,
        secret_policy=secret_policy,
    )


__all__ = [
    "CURSOR_MCP_DIALECT",
    "extract_pair_id_from_cursor_agent_md",
    "extract_pair_id_from_cursor_command_md",
    "extract_pair_id_from_cursor_mcp_server_json",
    "extract_pair_id_from_cursor_rule_mdc",
    "extract_pair_id_from_cursor_skill_md",
    "parse_cursor_agent_md",
    "parse_cursor_command_md",
    "parse_cursor_mcp_server_json",
    "parse_cursor_rule_mdc",
    "parse_cursor_skill_md",
    "render_cursor_agent_md",
    "render_cursor_command_md",
    "render_cursor_mcp_server_json",
    "render_cursor_rule_mdc",
    "render_cursor_skill_md",
]
