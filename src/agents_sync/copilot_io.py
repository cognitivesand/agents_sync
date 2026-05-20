"""GitHub Copilot Markdown parse / render helpers.

Copilot exposes several local, file-backed customization surfaces. This module
keeps their Markdown/YAML dialects thin and explicit so the registry can wire
them into the existing agent / skill / rules / slash_command sync paths.
"""
from __future__ import annotations

import io
import re
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
from agents_sync.state import target_slug


KNOWN_AGENT_FIELDS = frozenset({
    "pair_id",
    "name",
    "description",
    "model",
    "tools",
    "argument-hint",
    "agents",
    "user-invocable",
    "disable-model-invocation",
    "infer",
    "target",
    "mcp-servers",
    "metadata",
    "handoffs",
    "hooks",
})

KNOWN_SKILL_FIELDS = frozenset({
    "pair_id",
    "name",
    "description",
    "argument-hint",
    "user-invocable",
    "disable-model-invocation",
    "context",
})

KNOWN_INSTRUCTION_FIELDS = frozenset({
    "pair_id",
    "name",
    "description",
    "applyTo",
    "paths",
    "globs",
    "mode",
    "provenance",
    "private",
})

KNOWN_PROMPT_FIELDS = frozenset({
    "pair_id",
    "name",
    "description",
    "argument-hint",
    "agent",
    "model",
    "tools",
})

AGENT_TOOL_ONLY_FIELDS: tuple[str, ...] = (
    "argument-hint",
    "agents",
    "user-invocable",
    "disable-model-invocation",
    "infer",
    "target",
    "mcp-servers",
    "metadata",
    "handoffs",
    "hooks",
)

SKILL_TOOL_ONLY_FIELDS: tuple[str, ...] = (
    "argument-hint",
    "user-invocable",
    "disable-model-invocation",
    "context",
)

INSTRUCTION_CANONICAL_FIELDS: tuple[str, ...] = (
    "applyTo",
    "paths",
    "globs",
    "mode",
)

PROMPT_TOOL_ONLY_FIELDS: tuple[str, ...] = ("agent",)


def _yaml_dump(data: Any) -> str:
    buffer = io.StringIO()
    _make_yaml().dump(data, buffer)
    return buffer.getvalue()


def _split_frontmatter(
    text: str,
    label: str,
    *,
    strip_body: bool = True,
) -> tuple[dict[str, Any], str]:
    text = _normalize_markdown_text(text)
    match = FRONTMATTER_RE.match(text)
    if match is None:
        body = _strip_bom_prefix(text)
        return {}, body.strip() if strip_body else body

    raw_frontmatter, body_raw = match.groups()
    loaded = _yaml_load(raw_frontmatter)
    if loaded is None:
        frontmatter_data: dict[str, Any] = {}
    elif not isinstance(loaded, dict):
        raise ValueError(f"Copilot {label} frontmatter must be a YAML mapping")
    else:
        frontmatter_data = dict(loaded)

    body = _strip_bom_prefix(body_raw)
    return frontmatter_data, body.strip() if strip_body else body


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


def _render_markdown(frontmatter: dict[str, Any], body: str, *, final_newline: bool = True) -> str:
    rendered_frontmatter = _yaml_dump(frontmatter).rstrip("\n")
    suffix = "\n" if final_newline and body else ""
    if body:
        return f"---\n{rendered_frontmatter}\n---\n{body}{suffix}"
    return f"---\n{rendered_frontmatter}\n---\n"


def _set_or_pop(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None or value == "" or value == []:
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


def _unknown_fields(
    frontmatter: dict[str, Any],
    known_fields: frozenset[str],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in frontmatter.items()
        if key not in known_fields
    }


def _strip_suffix(name: str, *suffixes: str) -> str:
    for suffix in suffixes:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _agent_name_from_path(artifact_path: Path | None) -> str | None:
    if artifact_path is None:
        return None
    return _strip_suffix(
        artifact_path.name,
        ".agent.md",
        ".chatmode.md",
        ".md",
    )


def _instruction_name_from_path(artifact_path: Path | None) -> str | None:
    if artifact_path is None:
        return None
    return _strip_suffix(artifact_path.name, ".instructions.md", ".md")


def _prompt_name_from_path(
    artifact_path: Path | None,
    artifact_root: Path | None,
) -> str | None:
    if artifact_path is None:
        return None
    try:
        relative = artifact_path.relative_to(artifact_root) if artifact_root else artifact_path.name
    except ValueError:
        relative = artifact_path.name
    if isinstance(relative, str):
        parts = [relative]
    else:
        parts = list(relative.parts)
    if not parts:
        return None
    parts[-1] = _strip_suffix(parts[-1], ".prompt.md", ".md")
    return ":".join(part for part in parts if part)


def copilot_skill_slug(value: str) -> str:
    """Return a Copilot Agent Skill-compatible directory slug."""
    slug = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        slug = target_slug(value)
    return slug[:64].rstrip("-") or "converted"


def _set_pair_id(canonical: dict[str, Any], frontmatter: dict[str, Any], prior: dict[str, Any] | None) -> None:
    if "pair_id" in frontmatter:
        canonical["pair_id"] = str(frontmatter["pair_id"])
    elif prior is None:
        canonical["pair_id"] = new_pair_id()


def _set_per_tool_data(
    canonical: dict[str, Any],
    *,
    only: dict[str, Any],
    extra: dict[str, Any],
) -> None:
    per_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_only["copilot"] = only
    canonical["per_agentic_tool_only"] = per_only

    per_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_extra["copilot"] = extra
    canonical["per_agentic_tool_extra"] = per_extra


# ---------- agents ----------


def extract_pair_id_from_copilot_agent_md(text: str) -> str | None:
    return extract_pair_id_from_md(text)


def parse_copilot_agent_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    frontmatter, body = _split_frontmatter(text, "agent")
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("agent")
    canonical["body"] = body

    path_name = _agent_name_from_path(artifact_path)
    if "name" in frontmatter:
        canonical["name"] = str(frontmatter["name"])
    elif path_name:
        canonical["name"] = path_name

    if "description" in frontmatter:
        canonical["description"] = str(frontmatter["description"])
    if "model" in frontmatter:
        canonical["model"] = frontmatter["model"]
    if "tools" in frontmatter:
        canonical["tools"] = _as_string_list(frontmatter["tools"])

    _set_per_tool_data(
        canonical,
        only=_frontmatter_subset(frontmatter, AGENT_TOOL_ONLY_FIELDS),
        extra=_unknown_fields(frontmatter, KNOWN_AGENT_FIELDS),
    )
    _set_pair_id(canonical, frontmatter, prior_canonical)
    return canonical


def render_copilot_agent_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    frontmatter = _frontmatter_for_render(prior_text)
    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = canonical["name"]
    _set_or_pop(frontmatter, "description", canonical.get("description"))
    _set_or_pop(frontmatter, "model", canonical.get("model"))
    _set_or_pop(frontmatter, "tools", canonical.get("tools"))

    tool_only = canonical.get("per_agentic_tool_only", {}).get("copilot", {})
    for field_name in AGENT_TOOL_ONLY_FIELDS:
        _set_or_pop(frontmatter, field_name, tool_only.get(field_name))

    for key, value in canonical.get("per_agentic_tool_extra", {}).get("copilot", {}).items():
        if key not in KNOWN_AGENT_FIELDS:
            frontmatter[key] = value

    return _render_markdown(frontmatter, canonical.get("body", ""))


# ---------- skills ----------


def extract_pair_id_from_copilot_skill_md(text: str) -> str | None:
    return extract_pair_id_from_md(text)


def parse_copilot_skill_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    frontmatter, body = _split_frontmatter(text, "skill")
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("skill")
    canonical["body"] = body

    if "name" in frontmatter:
        canonical["name"] = str(frontmatter["name"])
    elif artifact_path is not None:
        canonical["name"] = artifact_path.name
    if "description" in frontmatter:
        canonical["description"] = str(frontmatter["description"])

    _set_per_tool_data(
        canonical,
        only=_frontmatter_subset(frontmatter, SKILL_TOOL_ONLY_FIELDS),
        extra=_unknown_fields(frontmatter, KNOWN_SKILL_FIELDS),
    )
    _set_pair_id(canonical, frontmatter, prior_canonical)
    return canonical


def render_copilot_skill_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    frontmatter = _frontmatter_for_render(prior_text)
    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = copilot_skill_slug(canonical["name"])
    _set_or_pop(frontmatter, "description", canonical.get("description"))

    tool_only = canonical.get("per_agentic_tool_only", {}).get("copilot", {})
    for field_name in SKILL_TOOL_ONLY_FIELDS:
        _set_or_pop(frontmatter, field_name, tool_only.get(field_name))

    for key, value in canonical.get("per_agentic_tool_extra", {}).get("copilot", {}).items():
        if key not in KNOWN_SKILL_FIELDS:
            frontmatter[key] = value

    return _render_markdown(frontmatter, canonical.get("body", ""))


# ---------- VS Code user-profile instructions / rules ----------


def extract_pair_id_from_copilot_instruction_md(text: str) -> str | None:
    return extract_pair_id_from_md(text)


def parse_copilot_instruction_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    frontmatter, body = _split_frontmatter(text, "instruction", strip_body=False)
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("rules")
    canonical["body"] = body

    path_name = _instruction_name_from_path(artifact_path)
    if "name" in frontmatter:
        canonical["name"] = str(frontmatter["name"])
    elif path_name:
        canonical["name"] = path_name
    if "description" in frontmatter:
        canonical["description"] = str(frontmatter["description"])
    for field_name in INSTRUCTION_CANONICAL_FIELDS:
        if field_name in frontmatter:
            canonical[field_name] = frontmatter[field_name]
    if "provenance" in frontmatter:
        canonical["provenance"] = str(frontmatter["provenance"])
    if "private" in frontmatter:
        canonical["private"] = bool(frontmatter["private"])

    _set_per_tool_data(
        canonical,
        only={},
        extra=_unknown_fields(frontmatter, KNOWN_INSTRUCTION_FIELDS),
    )
    _set_pair_id(canonical, frontmatter, prior_canonical)
    return canonical


def render_copilot_instruction_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    frontmatter = _frontmatter_for_render(prior_text)
    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = canonical["name"]
    _set_or_pop(frontmatter, "description", canonical.get("description"))
    for field_name in INSTRUCTION_CANONICAL_FIELDS:
        _set_or_pop(frontmatter, field_name, canonical.get(field_name))

    for key, value in canonical.get("per_agentic_tool_extra", {}).get("copilot", {}).items():
        if key not in KNOWN_INSTRUCTION_FIELDS:
            frontmatter[key] = value

    return _render_markdown(frontmatter, canonical.get("body", ""))


# ---------- VS Code user-profile prompts / slash commands ----------


def extract_pair_id_from_copilot_prompt_md(text: str) -> str | None:
    return extract_pair_id_from_md(text)


def parse_copilot_prompt_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    frontmatter, body = _split_frontmatter(text, "prompt", strip_body=False)
    canonical = (
        dict(prior_canonical)
        if prior_canonical
        else empty_canonical("slash_command")
    )
    canonical["body"] = body

    path_name = _prompt_name_from_path(artifact_path, artifact_root)
    if "name" in frontmatter:
        canonical["name"] = str(frontmatter["name"])
    elif path_name:
        canonical["name"] = path_name
    if "description" in frontmatter:
        canonical["description"] = str(frontmatter["description"])
    if "argument-hint" in frontmatter:
        canonical["argument_hint"] = str(frontmatter["argument-hint"])
    if "model" in frontmatter:
        canonical["model"] = frontmatter["model"]
    if "tools" in frontmatter:
        canonical["tools"] = _as_string_list(frontmatter["tools"])

    _set_per_tool_data(
        canonical,
        only=_frontmatter_subset(frontmatter, PROMPT_TOOL_ONLY_FIELDS),
        extra=_unknown_fields(frontmatter, KNOWN_PROMPT_FIELDS),
    )
    _set_pair_id(canonical, frontmatter, prior_canonical)
    return canonical


def render_copilot_prompt_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    frontmatter = _frontmatter_for_render(prior_text)
    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = canonical["name"]
    _set_or_pop(frontmatter, "description", canonical.get("description"))
    _set_or_pop(frontmatter, "argument-hint", canonical.get("argument_hint"))
    _set_or_pop(frontmatter, "model", canonical.get("model"))
    _set_or_pop(
        frontmatter,
        "tools",
        canonical.get("tools") or canonical.get("allowed_tools"),
    )

    tool_only = canonical.get("per_agentic_tool_only", {}).get("copilot", {})
    for field_name in PROMPT_TOOL_ONLY_FIELDS:
        _set_or_pop(frontmatter, field_name, tool_only.get(field_name))

    for key, value in canonical.get("per_agentic_tool_extra", {}).get("copilot", {}).items():
        if key not in KNOWN_PROMPT_FIELDS:
            frontmatter[key] = value

    return _render_markdown(
        frontmatter,
        canonical.get("body", ""),
        final_newline=False,
    )


__all__ = [
    "copilot_skill_slug",
    "extract_pair_id_from_copilot_agent_md",
    "extract_pair_id_from_copilot_instruction_md",
    "extract_pair_id_from_copilot_prompt_md",
    "extract_pair_id_from_copilot_skill_md",
    "parse_copilot_agent_md",
    "parse_copilot_instruction_md",
    "parse_copilot_prompt_md",
    "parse_copilot_skill_md",
    "render_copilot_agent_md",
    "render_copilot_instruction_md",
    "render_copilot_prompt_md",
    "render_copilot_skill_md",
]
