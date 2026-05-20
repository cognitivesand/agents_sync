"""Gemini CLI parse / render helpers.

Gemini CLI uses separate user-level surfaces from Google Antigravity:

- subagents: ``~/.gemini/agents/*.md``
- skills: ``~/.gemini/skills/<name>/SKILL.md``
- rules: ``~/.gemini/GEMINI.md``
- slash commands: ``~/.gemini/commands/**/*.toml``

Antigravity remains a distinct adapter rooted at
``~/.gemini/antigravity/skills``; this module intentionally never reads or
writes that path.
"""
from __future__ import annotations

import io as _io
from pathlib import Path
from typing import Any

from agents_sync.canonical import empty_canonical, new_pair_id
from agents_sync.claude_io import (
    FRONTMATTER_RE,
    _make_yaml,
    _normalize_markdown_text,
    _strip_bom_prefix,
    _yaml_load,
    extract_pair_id_from_md,
)
from agents_sync.rules_io import (
    GLOBAL_RULE_NAME,
    extract_pair_id_from_rules_md,
    parse_rules_md,
    render_rules_md,
)
from agents_sync.slash_command_io import (
    extract_pair_id_from_slash_command_toml,
    parse_slash_command_toml,
    render_slash_command_toml,
)


KNOWN_GEMINI_AGENT_FIELDS = frozenset({
    "pair_id",
    "name",
    "description",
    "kind",
    "tools",
    "mcpServers",
    "model",
    "temperature",
    "max_turns",
})

KNOWN_GEMINI_SKILL_FIELDS = frozenset({
    "pair_id",
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
})

OPTIONAL_GEMINI_AGENT_FIELDS: tuple[str, ...] = (
    "kind",
    "temperature",
    "max_turns",
    "mcpServers",
)

OPTIONAL_GEMINI_SKILL_FIELDS: tuple[str, ...] = (
    "license",
    "compatibility",
    "metadata",
)

FOREIGN_AGENT_FIELDS = frozenset({
    "effort",
    "disallowedTools",
    "permissionMode",
    "hooks",
    "sandbox_mode",
    "developer_instructions",
    "nickname_candidates",
    "mcp_servers",
    "mode",
    "top_p",
    "steps",
    "maxSteps",
    "permission",
    "color",
    "hidden",
    "disable",
    "options",
})

FOREIGN_SKILL_FIELDS = frozenset({
    "model",
    "effort",
    "tools",
    "disallowedTools",
    "permissionMode",
    "hooks",
    "mcpServers",
    "allowed-tools",
    "sandbox_mode",
    "developer_instructions",
    "nickname_candidates",
    "mcp_servers",
})


def _yaml_dump(data: Any) -> str:
    buffer = _io.StringIO()
    _make_yaml().dump(data, buffer)
    return buffer.getvalue()


def _split_frontmatter(text: str, label: str) -> tuple[dict[str, Any], str]:
    text = _normalize_markdown_text(text)
    match = FRONTMATTER_RE.match(text)
    if match is None:
        return {}, _strip_bom_prefix(text.strip())

    raw_frontmatter, body_raw = match.groups()
    loaded = _yaml_load(raw_frontmatter)
    if loaded is None:
        frontmatter_data: dict[str, Any] = {}
    elif not isinstance(loaded, dict):
        raise ValueError(f"{label} frontmatter must be a YAML mapping")
    else:
        frontmatter_data = dict(loaded)
    return frontmatter_data, _strip_bom_prefix(body_raw.strip())


def _frontmatter_for_render(prior_text: str | None) -> dict[str, Any]:
    yml = _make_yaml()
    if prior_text is None:
        return yml.load("{}\n")

    prior_text = _normalize_markdown_text(prior_text)
    prior_match = FRONTMATTER_RE.match(prior_text)
    if prior_match is None:
        return yml.load("{}\n")

    loaded = _yaml_load(prior_match.group(1))
    return loaded if isinstance(loaded, dict) else yml.load("{}\n")


def _render_markdown(frontmatter: dict[str, Any], body: str) -> str:
    rendered_frontmatter = _yaml_dump(frontmatter).rstrip("\n")
    if body:
        return f"---\n{rendered_frontmatter}\n---\n{body}\n"
    return f"---\n{rendered_frontmatter}\n---\n"


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


def _unknown_frontmatter_fields(
    frontmatter: dict[str, Any],
    *,
    known_fields: frozenset[str],
    foreign_fields: frozenset[str],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in frontmatter.items()
        if key not in known_fields and key not in foreign_fields
    }


def _set_or_pop(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None or value == "" or value == []:
        target.pop(key, None)
        return
    target[key] = value


def extract_pair_id_from_gemini_agent_md(text: str) -> str | None:
    return extract_pair_id_from_md(text)


def parse_gemini_agent_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Parse a Gemini CLI subagent Markdown file."""
    del artifact_root

    frontmatter_data, body = _split_frontmatter(text, "Gemini CLI agent")
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("agent")
    canonical["body"] = body

    if "name" in frontmatter_data:
        canonical["name"] = str(frontmatter_data["name"])
    elif artifact_path is not None:
        canonical["name"] = artifact_path.stem

    if "description" in frontmatter_data:
        canonical["description"] = str(frontmatter_data["description"])
    if "model" in frontmatter_data:
        canonical["model"] = frontmatter_data["model"]
    if "tools" in frontmatter_data:
        canonical["tools"] = _as_string_list(frontmatter_data["tools"])

    per_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_only["gemini_cli"] = _frontmatter_subset(
        frontmatter_data,
        OPTIONAL_GEMINI_AGENT_FIELDS,
    )
    canonical["per_agentic_tool_only"] = per_only

    per_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_extra["gemini_cli"] = _unknown_frontmatter_fields(
        frontmatter_data,
        known_fields=KNOWN_GEMINI_AGENT_FIELDS,
        foreign_fields=FOREIGN_AGENT_FIELDS,
    )
    canonical["per_agentic_tool_extra"] = per_extra

    if "pair_id" in frontmatter_data:
        canonical["pair_id"] = str(frontmatter_data["pair_id"])
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical


def render_gemini_agent_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    """Render a canonical agent as a Gemini CLI subagent file."""
    frontmatter = _frontmatter_for_render(prior_text)
    for key in FOREIGN_AGENT_FIELDS:
        frontmatter.pop(key, None)

    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = canonical["name"]
    _set_or_pop(frontmatter, "description", canonical.get("description"))
    _set_or_pop(frontmatter, "model", canonical.get("model"))
    _set_or_pop(frontmatter, "tools", canonical.get("tools"))

    gemini_only = canonical.get("per_agentic_tool_only", {}).get("gemini_cli", {})
    _set_or_pop(frontmatter, "kind", gemini_only.get("kind") or "subagent")
    for field_name in ("temperature", "max_turns", "mcpServers"):
        _set_or_pop(frontmatter, field_name, gemini_only.get(field_name))

    for key, value in canonical.get("per_agentic_tool_extra", {}).get(
        "gemini_cli", {}
    ).items():
        if key not in FOREIGN_AGENT_FIELDS:
            frontmatter[key] = value

    return _render_markdown(frontmatter, canonical.get("body", ""))


def extract_pair_id_from_gemini_skill_md(text: str) -> str | None:
    return extract_pair_id_from_md(text)


def parse_gemini_skill_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Parse a Gemini CLI Agent Skill ``SKILL.md`` file."""
    del artifact_path, artifact_root

    frontmatter_data, body = _split_frontmatter(text, "Gemini CLI SKILL.md")
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("skill")
    canonical["body"] = body

    if "name" in frontmatter_data:
        canonical["name"] = str(frontmatter_data["name"])
    if "description" in frontmatter_data:
        canonical["description"] = str(frontmatter_data["description"])

    per_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_only["gemini_cli"] = _frontmatter_subset(
        frontmatter_data,
        OPTIONAL_GEMINI_SKILL_FIELDS,
    )
    canonical["per_agentic_tool_only"] = per_only

    per_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_extra["gemini_cli"] = _unknown_frontmatter_fields(
        frontmatter_data,
        known_fields=KNOWN_GEMINI_SKILL_FIELDS,
        foreign_fields=FOREIGN_SKILL_FIELDS,
    )
    canonical["per_agentic_tool_extra"] = per_extra

    if "pair_id" in frontmatter_data:
        canonical["pair_id"] = str(frontmatter_data["pair_id"])
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical


def render_gemini_skill_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    """Render a canonical skill as a Gemini CLI ``SKILL.md`` file."""
    frontmatter = _frontmatter_for_render(prior_text)
    for key in FOREIGN_SKILL_FIELDS:
        frontmatter.pop(key, None)

    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = canonical["name"]
    _set_or_pop(frontmatter, "description", canonical.get("description"))

    gemini_only = canonical.get("per_agentic_tool_only", {}).get("gemini_cli", {})
    for field_name in OPTIONAL_GEMINI_SKILL_FIELDS:
        _set_or_pop(frontmatter, field_name, gemini_only.get(field_name))

    for key, value in canonical.get("per_agentic_tool_extra", {}).get(
        "gemini_cli", {}
    ).items():
        if key not in FOREIGN_SKILL_FIELDS:
            frontmatter[key] = value

    return _render_markdown(frontmatter, canonical.get("body", ""))


def extract_pair_id_from_gemini_rules_md(text: str) -> str | None:
    return extract_pair_id_from_rules_md(text)


def parse_gemini_rules_md(
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
        agentic_tool_name="gemini_cli",
        artifact_path=artifact_path,
        canonical_name=GLOBAL_RULE_NAME,
    )


def render_gemini_rules_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    return render_rules_md(
        canonical,
        prior_text,
        agentic_tool_name="gemini_cli",
    )


def extract_pair_id_from_gemini_command_toml(text: str) -> str | None:
    return extract_pair_id_from_slash_command_toml(text)


def parse_gemini_command_toml(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    return parse_slash_command_toml(
        text,
        prior_canonical,
        agentic_tool_name="gemini_cli",
        artifact_path=artifact_path,
        artifact_root=artifact_root,
    )


def render_gemini_command_toml(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    return render_slash_command_toml(
        canonical,
        prior_text,
        agentic_tool_name="gemini_cli",
    )


__all__ = [
    "KNOWN_GEMINI_AGENT_FIELDS",
    "KNOWN_GEMINI_SKILL_FIELDS",
    "extract_pair_id_from_gemini_agent_md",
    "extract_pair_id_from_gemini_command_toml",
    "extract_pair_id_from_gemini_rules_md",
    "extract_pair_id_from_gemini_skill_md",
    "parse_gemini_agent_md",
    "parse_gemini_command_toml",
    "parse_gemini_rules_md",
    "parse_gemini_skill_md",
    "render_gemini_agent_md",
    "render_gemini_command_toml",
    "render_gemini_rules_md",
    "render_gemini_skill_md",
]
