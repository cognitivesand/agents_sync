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

from pathlib import Path
from typing import Any

from agents_sync.artifact_names import resolve_artifact_name
from agents_sync.canonical import empty_canonical, new_pair_id
from agents_sync.markdown_yaml_metadata_block import (
    as_string_list,
    extract_pair_id_from_md,
    frontmatter_for_render,
    metadata_subset,
    render_markdown_with_metadata_block,
    set_or_remove_empty_metadata_field,
    split_frontmatter,
    unknown_metadata_fields,
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
    "tools",
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
    frontmatter_data, body = split_frontmatter(
        text, label="Gemini CLI agent",
    )
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("agent")
    canonical["body"] = body

    name = resolve_artifact_name(
        frontmatter_name=frontmatter_data.get("name"),
        path_name=artifact_path.stem if artifact_path is not None else None,
        prior_name=canonical.get("name"),
        precedence=("frontmatter", "path", "prior"),
    )
    if name is not None:
        canonical["name"] = name

    if "description" in frontmatter_data:
        canonical["description"] = str(frontmatter_data["description"])
    if "model" in frontmatter_data:
        canonical["model"] = frontmatter_data["model"]

    per_only = dict(canonical.get("per_agentic_tool_only") or {})
    gemini_only = metadata_subset(
        frontmatter_data,
        OPTIONAL_GEMINI_AGENT_FIELDS,
    )
    if "tools" in gemini_only:
        gemini_only["tools"] = as_string_list(gemini_only["tools"])
    per_only["gemini_cli"] = gemini_only
    canonical["per_agentic_tool_only"] = per_only

    per_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_extra["gemini_cli"] = unknown_metadata_fields(
        frontmatter_data,
        KNOWN_GEMINI_AGENT_FIELDS,
        FOREIGN_AGENT_FIELDS,
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
    frontmatter = frontmatter_for_render(prior_text)
    for key in FOREIGN_AGENT_FIELDS:
        frontmatter.pop(key, None)

    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = canonical["name"]
    set_or_remove_empty_metadata_field(
        frontmatter, "description", canonical.get("description"),
    )
    set_or_remove_empty_metadata_field(frontmatter, "model", canonical.get("model"))

    gemini_only = canonical.get("per_agentic_tool_only", {}).get("gemini_cli", {})
    set_or_remove_empty_metadata_field(
        frontmatter, "kind", gemini_only.get("kind") or "local",
    )
    set_or_remove_empty_metadata_field(frontmatter, "tools", gemini_only.get("tools"))
    for field_name in ("temperature", "max_turns", "mcpServers"):
        set_or_remove_empty_metadata_field(
            frontmatter, field_name, gemini_only.get(field_name),
        )

    for key, value in canonical.get("per_agentic_tool_extra", {}).get(
        "gemini_cli", {}
    ).items():
        if key not in FOREIGN_AGENT_FIELDS:
            frontmatter[key] = value

    return render_markdown_with_metadata_block(frontmatter, canonical.get("body", ""))


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
    frontmatter_data, body = split_frontmatter(
        text, label="Gemini CLI SKILL.md",
    )
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("skill")
    canonical["body"] = body

    if "name" in frontmatter_data:
        canonical["name"] = str(frontmatter_data["name"])
    if "description" in frontmatter_data:
        canonical["description"] = str(frontmatter_data["description"])

    per_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_only["gemini_cli"] = metadata_subset(
        frontmatter_data,
        OPTIONAL_GEMINI_SKILL_FIELDS,
    )
    canonical["per_agentic_tool_only"] = per_only

    per_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_extra["gemini_cli"] = unknown_metadata_fields(
        frontmatter_data,
        KNOWN_GEMINI_SKILL_FIELDS,
        FOREIGN_SKILL_FIELDS,
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
    frontmatter = frontmatter_for_render(prior_text)
    for key in FOREIGN_SKILL_FIELDS:
        frontmatter.pop(key, None)

    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = canonical["name"]
    set_or_remove_empty_metadata_field(
        frontmatter, "description", canonical.get("description"),
    )

    gemini_only = canonical.get("per_agentic_tool_only", {}).get("gemini_cli", {})
    for field_name in OPTIONAL_GEMINI_SKILL_FIELDS:
        set_or_remove_empty_metadata_field(
            frontmatter, field_name, gemini_only.get(field_name),
        )

    for key, value in canonical.get("per_agentic_tool_extra", {}).get(
        "gemini_cli", {}
    ).items():
        if key not in FOREIGN_SKILL_FIELDS:
            frontmatter[key] = value

    return render_markdown_with_metadata_block(frontmatter, canonical.get("body", ""))


def extract_pair_id_from_gemini_rules_md(text: str) -> str | None:
    return extract_pair_id_from_rules_md(text)


def parse_gemini_rules_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
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
