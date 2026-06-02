"""opencode .md and SKILL.md parse / render.

opencode agents are Markdown files with YAML frontmatter and the same shared
agent-name policy as the other Markdown adapters. opencode skills use the open
SKILL.md folder format.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agents_sync.artifact_names import CANONICAL_NAME_FIELD, resolve_artifact_name
from agents_sync.canonical import empty_canonical, new_pair_id
from agents_sync.markdown_yaml_metadata_block import (
    frontmatter_for_render,
    metadata_subset,
    render_markdown_with_metadata_block,
    set_or_remove_empty_metadata_field,
    split_frontmatter,
    unknown_metadata_fields,
)

KNOWN_OPENCODE_AGENT_FIELDS = frozenset({
    "pair_id",
    "description",
    "mode",
    "model",
    "temperature",
    "top_p",
    "steps",
    "maxSteps",
    "permission",
    "tools",
    "color",
    "hidden",
    "disable",
    "options",
})

KNOWN_OPENCODE_SKILL_FIELDS = frozenset({
    "pair_id",
    "name",
    CANONICAL_NAME_FIELD,
    "description",
    "license",
    "compatibility",
    "metadata",
})

OPTIONAL_OPENCODE_AGENT_FIELDS: tuple[str, ...] = (
    "mode",
    "temperature",
    "top_p",
    "steps",
    "permission",
    "color",
    "hidden",
    "disable",
    "options",
)

OPTIONAL_OPENCODE_SKILL_FIELDS: tuple[str, ...] = (
    "license",
    "compatibility",
    "metadata",
)

FOREIGN_AGENT_FIELDS = frozenset({
    "name",
    "effort",
    "tools",
    "disallowedTools",
    "permissionMode",
    "hooks",
    "mcpServers",
    "sandbox_mode",
    "developer_instructions",
    "nickname_candidates",
    "mcp_servers",
})

FOREIGN_SKILL_FIELDS = frozenset({
    CANONICAL_NAME_FIELD,
    "model",
    "effort",
    "tools",
    "disallowedTools",
    "permissionMode",
    "hooks",
    "mcpServers",
    "sandbox_mode",
    "developer_instructions",
    "nickname_candidates",
    "mcp_servers",
})


def _normalise_deprecated_tools(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    permission: dict[str, str] = {}
    for key, enabled in value.items():
        permission[str(key)] = "allow" if bool(enabled) else "deny"
    return permission


def _split_model_provider(model: Any) -> tuple[str | None, str | None]:
    if not isinstance(model, str) or not model:
        return None, None
    provider, sep, model_id = model.partition("/")
    if sep and provider and model_id:
        return provider, model_id
    return None, model


def _join_model_provider(model: Any, provider: Any) -> str | None:
    if not isinstance(model, str) or not model:
        return None
    if "/" in model:
        return model
    if isinstance(provider, str) and provider:
        return f"{provider}/{model}"
    return model


def opencode_skill_slug(value: str) -> str:
    """Return an opencode-compatible skill slug.

    opencode skills require lowercase kebab-case names. This stricter slugger
    is used only for the opencode skill path and rendered SKILL.md name.
    """
    slug = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        slug = "converted"
    return slug[:64].rstrip("-") or "converted"


# ---------- agent ----------

def parse_opencode_agent_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
) -> dict[str, Any]:
    """Parse an opencode agent .md document into a canonical dict.

    Agent Markdown parsers share the same name policy: frontmatter wins,
    then filename, then prior canonical. When none of those sources can
    produce a non-empty name, this raises rather than minting ``name=''``.
    """
    frontmatter_data, body = split_frontmatter(text, label="opencode agent")
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("agent")
    canonical["body"] = body

    canonical["name"] = resolve_artifact_name(
        frontmatter_name=frontmatter_data.get("name"),
        path_name=artifact_path.stem if artifact_path is not None else None,
        prior_name=canonical.get("name"),
        precedence=("frontmatter", "path", "prior"),
        required_label=(
            "parse_opencode_agent_md with artifact_path, prior canonical, "
            "or frontmatter name"
        ),
    )

    if "description" in frontmatter_data:
        canonical["description"] = str(frontmatter_data["description"])

    opencode_only = metadata_subset(
        frontmatter_data,
        OPTIONAL_OPENCODE_AGENT_FIELDS,
    )
    if "maxSteps" in frontmatter_data and "steps" not in opencode_only:
        opencode_only["steps"] = frontmatter_data["maxSteps"]
    if "permission" not in opencode_only and "tools" in frontmatter_data:
        normalised = _normalise_deprecated_tools(frontmatter_data["tools"])
        if normalised is not None:
            opencode_only["permission"] = normalised

    provider, model_id = _split_model_provider(frontmatter_data.get("model"))
    if model_id is not None:
        canonical["model"] = model_id
    if provider is not None:
        opencode_only["model_provider"] = provider

    per_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_only["opencode"] = opencode_only
    canonical["per_agentic_tool_only"] = per_only

    per_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_extra["opencode"] = unknown_metadata_fields(
        frontmatter_data,
        KNOWN_OPENCODE_AGENT_FIELDS,
        FOREIGN_AGENT_FIELDS,
    )
    canonical["per_agentic_tool_extra"] = per_extra

    if "pair_id" in frontmatter_data:
        canonical["pair_id"] = str(frontmatter_data["pair_id"])
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical


def render_opencode_agent_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    frontmatter = frontmatter_for_render(prior_text)
    for key in FOREIGN_AGENT_FIELDS:
        frontmatter.pop(key, None)

    frontmatter["pair_id"] = canonical["pair_id"]
    set_or_remove_empty_metadata_field(
        frontmatter, "description", canonical.get("description"),
    )

    opencode_only = canonical.get("per_agentic_tool_only", {}).get("opencode", {})
    model = _join_model_provider(canonical.get("model"), opencode_only.get("model_provider"))
    if model is not None:
        frontmatter["model"] = model
    else:
        frontmatter.pop("model", None)

    frontmatter.pop("maxSteps", None)
    for field_name in OPTIONAL_OPENCODE_AGENT_FIELDS:
        set_or_remove_empty_metadata_field(
            frontmatter, field_name, opencode_only.get(field_name),
        )

    for key, value in canonical.get("per_agentic_tool_extra", {}).get("opencode", {}).items():
        if key not in FOREIGN_AGENT_FIELDS:
            frontmatter[key] = value

    return render_markdown_with_metadata_block(frontmatter, canonical.get("body", ""))


# ---------- skill ----------

def parse_opencode_skill_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
) -> dict[str, Any]:
    frontmatter_data, body = split_frontmatter(text, label="opencode SKILL.md")
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("skill")
    canonical["body"] = body

    name = resolve_artifact_name(
        frontmatter_name=frontmatter_data.get(CANONICAL_NAME_FIELD),
        prior_name=canonical.get("name"),
        override_name=frontmatter_data.get("name"),
        path_name=artifact_path.name if artifact_path is not None else None,
        precedence=("frontmatter", "prior", "override", "path"),
    )
    if name is not None:
        canonical["name"] = name
    if "description" in frontmatter_data:
        canonical["description"] = str(frontmatter_data["description"])

    opencode_only = metadata_subset(
        frontmatter_data,
        OPTIONAL_OPENCODE_SKILL_FIELDS,
    )
    per_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_only["opencode"] = opencode_only
    canonical["per_agentic_tool_only"] = per_only

    per_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_extra["opencode"] = unknown_metadata_fields(
        frontmatter_data,
        KNOWN_OPENCODE_SKILL_FIELDS,
        FOREIGN_SKILL_FIELDS,
    )
    canonical["per_agentic_tool_extra"] = per_extra

    if "pair_id" in frontmatter_data:
        canonical["pair_id"] = str(frontmatter_data["pair_id"])
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical


def render_opencode_skill_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    frontmatter = frontmatter_for_render(prior_text)
    for key in FOREIGN_SKILL_FIELDS:
        frontmatter.pop(key, None)

    frontmatter["pair_id"] = canonical["pair_id"]
    canonical_name = str(canonical["name"])
    skill_slug = opencode_skill_slug(canonical_name)
    frontmatter["name"] = skill_slug
    set_or_remove_empty_metadata_field(
        frontmatter,
        CANONICAL_NAME_FIELD,
        canonical_name if canonical_name != skill_slug else None,
    )
    set_or_remove_empty_metadata_field(
        frontmatter, "description", canonical.get("description"),
    )

    opencode_only = canonical.get("per_agentic_tool_only", {}).get("opencode", {})
    for field_name in OPTIONAL_OPENCODE_SKILL_FIELDS:
        set_or_remove_empty_metadata_field(
            frontmatter, field_name, opencode_only.get(field_name),
        )

    for key, value in canonical.get("per_agentic_tool_extra", {}).get("opencode", {}).items():
        if key not in FOREIGN_SKILL_FIELDS:
            frontmatter[key] = value

    return render_markdown_with_metadata_block(frontmatter, canonical.get("body", ""))


__all__ = [
    "KNOWN_OPENCODE_AGENT_FIELDS",
    "KNOWN_OPENCODE_SKILL_FIELDS",
    "opencode_skill_slug",
    "parse_opencode_agent_md",
    "parse_opencode_skill_md",
    "render_opencode_agent_md",
    "render_opencode_skill_md",
]
