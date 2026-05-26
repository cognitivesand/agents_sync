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

import io
import json
import re
from pathlib import Path
from typing import Any

from agents_sync.canonical import empty_canonical, new_pair_id
from agents_sync.claude_io import extract_pair_id_from_md
from agents_sync.yaml_frontmatter import (
    FRONTMATTER_RE,
    make_yaml as _make_yaml,
    normalize_markdown_text as _normalize_markdown_text,
    strip_bom_prefix as _strip_bom_prefix,
    yaml_load as _yaml_load,
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


def _yaml_dump(data: Any) -> str:
    buf = io.StringIO()
    _make_yaml().dump(data, buf)
    return buf.getvalue()


def _split_frontmatter(text: str, label: str) -> tuple[dict[str, Any], str]:
    text = _normalize_markdown_text(text)
    match = FRONTMATTER_RE.match(text)
    if match is None:
        return {}, _strip_bom_prefix(text.strip())

    raw_frontmatter, body_raw = match.groups()
    loaded = _yaml_load(raw_frontmatter)
    if loaded is None:
        frontmatter: dict[str, Any] = {}
    elif not isinstance(loaded, dict):
        raise ValueError(f"{label} frontmatter must be a YAML mapping")
    else:
        frontmatter = dict(loaded)
    return frontmatter, _strip_bom_prefix(body_raw.strip())


def _frontmatter_for_render(prior_text: str | None) -> dict[str, Any]:
    yml = _make_yaml()
    if prior_text is None:
        return yml.load("{}\n")

    prior_text = _normalize_markdown_text(prior_text)
    match = FRONTMATTER_RE.match(prior_text)
    if match is None:
        return yml.load("{}\n")

    loaded = _yaml_load(match.group(1))
    return loaded if isinstance(loaded, dict) else yml.load("{}\n")


def _render_markdown(frontmatter: dict[str, Any], body: str) -> str:
    rendered_frontmatter = _yaml_dump(frontmatter).rstrip("\n")
    if body:
        return f"---\n{rendered_frontmatter}\n---\n{body}\n"
    return f"---\n{rendered_frontmatter}\n---\n"


def _set_or_pop(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None or value == "":
        target.pop(key, None)
        return
    target[key] = value


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value)]


def _frontmatter_subset(
    frontmatter: dict[str, Any],
    field_names: tuple[str, ...],
) -> dict[str, Any]:
    return {
        field_name: frontmatter[field_name]
        for field_name in field_names
        if field_name in frontmatter
    }


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
    frontmatter, body = _split_frontmatter(text, "Cursor agent")
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("agent")
    canonical["body"] = body

    if artifact_path is not None:
        canonical["name"] = artifact_path.stem
    elif "name" in frontmatter:
        canonical["name"] = str(frontmatter["name"])

    if "description" in frontmatter:
        canonical["description"] = str(frontmatter["description"])
    if "model" in frontmatter:
        canonical["model"] = frontmatter["model"]
    if "tools" in frontmatter:
        canonical["tools"] = _as_string_list(frontmatter["tools"])

    per_tool_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_tool_only["cursor"] = {}
    canonical["per_agentic_tool_only"] = per_tool_only

    per_tool_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_tool_extra["cursor"] = {
        key: value
        for key, value in frontmatter.items()
        if key not in CURSOR_AGENT_FIELDS
    }
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
    frontmatter = _frontmatter_for_render(prior_text)
    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = canonical["name"]
    _set_or_pop(frontmatter, "description", canonical.get("description"))
    _set_or_pop(frontmatter, "model", canonical.get("model"))
    tools = canonical.get("tools")
    if tools:
        frontmatter["tools"] = tools
    else:
        frontmatter.pop("tools", None)

    for key, value in canonical.get("per_agentic_tool_extra", {}).get(
        "cursor", {}
    ).items():
        if key not in CURSOR_AGENT_FIELDS:
            frontmatter[key] = value

    return _render_markdown(frontmatter, canonical.get("body", ""))


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
    frontmatter, body = _split_frontmatter(text, "Cursor SKILL.md")
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("skill")
    canonical["body"] = body

    if "name" in frontmatter:
        canonical["name"] = str(frontmatter["name"])
    elif artifact_path is not None:
        canonical["name"] = artifact_path.name
    if "description" in frontmatter:
        canonical["description"] = str(frontmatter["description"])

    per_tool_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_tool_only["cursor"] = _frontmatter_subset(
        frontmatter,
        CURSOR_SKILL_ONLY_FIELDS,
    )
    canonical["per_agentic_tool_only"] = per_tool_only

    per_tool_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_tool_extra["cursor"] = {
        key: value
        for key, value in frontmatter.items()
        if key not in CURSOR_SKILL_FIELDS
    }
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
    frontmatter = _frontmatter_for_render(prior_text)
    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = canonical["name"]
    _set_or_pop(frontmatter, "description", canonical.get("description"))

    cursor_only = canonical.get("per_agentic_tool_only", {}).get("cursor", {})
    for field_name in CURSOR_SKILL_ONLY_FIELDS:
        _set_or_pop(frontmatter, field_name, cursor_only.get(field_name))

    for key, value in canonical.get("per_agentic_tool_extra", {}).get(
        "cursor", {}
    ).items():
        if key not in CURSOR_SKILL_FIELDS:
            frontmatter[key] = value

    return _render_markdown(frontmatter, canonical.get("body", ""))


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
    secret_policy: str = "refuse",
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
    secret_policy: str = "refuse",
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
