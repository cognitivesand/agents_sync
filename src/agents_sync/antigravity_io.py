"""Antigravity SKILL.md parse / render.

Antigravity uses the same open SKILL.md spec as Claude skills (YAML
frontmatter + Markdown body), with its own field allow-list:

- Required: name, description.
- Optional (Antigravity-known): license, compatibility, metadata, allowed-tools.
- Unknown frontmatter keys ride in canonical["per_agentic_tool_extra"]["antigravity"]
  as opaque YAML so user-authored fields the project does not model are not
  silently dropped.

Claude-specific fields (model, tools, hooks, mcpServers, permissionMode,
disallowedTools, effort) are NEVER emitted on the Antigravity side. They
survive in per_agentic_tool_extra["claude"] / per_agentic_tool_only["claude"]
and round-trip only through the Claude projection.
"""
from __future__ import annotations

import io as _io
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


# Frontmatter keys the Antigravity canonical maps explicitly. Anything else
# is preserved in canonical["per_agentic_tool_extra"]["antigravity"].
KNOWN_ANTIGRAVITY_FIELDS = frozenset({
    "pair_id",
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
})

# Antigravity-known optional fields. Parsing copies these into
# canonical["per_agentic_tool_only"]["antigravity"]; rendering emits them
# from the same location.
OPTIONAL_ANTIGRAVITY_FIELDS: tuple[str, ...] = (
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
)


def _yaml_dump(data: Any) -> str:
    buf = _io.StringIO()
    _make_yaml().dump(data, buf)
    return buf.getvalue()


def parse_antigravity_skill_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse an Antigravity SKILL.md file into a canonical dict.

    If `prior_canonical` is given, canonical state for other agentic tools
    (per_agentic_tool_only / per_agentic_tool_extra for non-antigravity keys)
    is preserved untouched. Unmapped passthrough fields not present in the
    new frontmatter are dropped from the antigravity-extra bag (the user's
    Antigravity frontmatter is the source of truth for that bag).
    """
    text = _normalize_markdown_text(text)
    match = FRONTMATTER_RE.match(text)
    if match is None:
        frontmatter_data: dict[str, Any] = {}
        body = _strip_bom_prefix(text.strip())
    else:
        raw_frontmatter, body_raw = match.groups()
        body = _strip_bom_prefix(body_raw.strip())
        loaded = _yaml_load(raw_frontmatter)
        if loaded is None:
            frontmatter_data = {}
        elif not isinstance(loaded, dict):
            raise ValueError("Antigravity SKILL.md frontmatter must be a YAML mapping")
        else:
            frontmatter_data = dict(loaded)

    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("skill")
    canonical["body"] = body

    if "name" in frontmatter_data:
        canonical["name"] = str(frontmatter_data["name"])
    if "description" in frontmatter_data:
        canonical["description"] = str(frontmatter_data["description"])

    antigravity_only: dict[str, Any] = {}
    for field_name in OPTIONAL_ANTIGRAVITY_FIELDS:
        if field_name in frontmatter_data:
            antigravity_only[field_name] = frontmatter_data[field_name]
    per_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_only["antigravity"] = antigravity_only
    canonical["per_agentic_tool_only"] = per_only

    per_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_extra["antigravity"] = {
        key: value
        for key, value in frontmatter_data.items()
        if key not in KNOWN_ANTIGRAVITY_FIELDS
    }
    canonical["per_agentic_tool_extra"] = per_extra

    if "pair_id" in frontmatter_data:
        canonical["pair_id"] = str(frontmatter_data["pair_id"])
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical


def render_antigravity_skill_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    """Render an Antigravity SKILL.md from canonical.

    When `prior_text` is provided, the prior frontmatter is loaded with
    ruamel.yaml and mutated in place so existing key order, comments, and
    quoting style are preserved across writes.

    Emits:
      - pair_id, name, description (always)
      - optional Antigravity-known fields from per_agentic_tool_only["antigravity"]
      - opaque passthrough from per_agentic_tool_extra["antigravity"]

    Does NOT emit Claude-side fields (model, tools, hooks, mcpServers,
    permissionMode, disallowedTools, effort) — those belong to the Claude
    projection only.
    """
    yml = _make_yaml()

    prior_text = _normalize_markdown_text(prior_text) if prior_text is not None else None
    prior_match = FRONTMATTER_RE.match(prior_text) if prior_text is not None else None

    if prior_match is not None:
        raw, _ = prior_match.groups()
        loaded = _yaml_load(raw)
        frontmatter = loaded if isinstance(loaded, dict) else yml.load("{}\n")
    else:
        frontmatter = yml.load("{}\n")

    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = canonical["name"]
    if canonical.get("description"):
        frontmatter["description"] = canonical["description"]

    antigravity_only = canonical.get("per_agentic_tool_only", {}).get("antigravity", {})
    for field_name in OPTIONAL_ANTIGRAVITY_FIELDS:
        if field_name in antigravity_only:
            frontmatter[field_name] = antigravity_only[field_name]

    extras = canonical.get("per_agentic_tool_extra", {}).get("antigravity", {})
    for key, value in extras.items():
        frontmatter[key] = value

    body = canonical.get("body", "")
    rendered_fm = _yaml_dump(frontmatter).rstrip("\n")
    if body:
        return f"---\n{rendered_fm}\n---\n{body}\n"
    return f"---\n{rendered_fm}\n---\n"


__all__ = [
    "KNOWN_ANTIGRAVITY_FIELDS",
    "OPTIONAL_ANTIGRAVITY_FIELDS",
    "extract_pair_id_from_md",
    "parse_antigravity_skill_md",
    "render_antigravity_skill_md",
]
