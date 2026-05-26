"""Generic Markdown parse/render helpers for v0.5 `rules` artifacts."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agents_sync.canonical import (
    apply_per_tool_partition,
    empty_canonical,
    new_pair_id,
)
from agents_sync.yaml_frontmatter import (
    extract_pair_id_from_md,
    frontmatter_for_render,
    split_frontmatter,
    yaml_dump,
)


KNOWN_RULE_FIELDS = frozenset({
    "pair_id",
    "name",
    "description",
    "globs",
    "applyTo",
    "alwaysApply",
    "trigger",
    "provenance",
    "private",
})
CANONICAL_RULE_FIELDS: tuple[str, ...] = ("globs", "applyTo", "alwaysApply")
TOOL_ONLY_RULE_FIELDS: tuple[str, ...] = ("trigger",)
VALID_PROVENANCES = frozenset({"user", "agent"})
GLOBAL_RULE_NAME = "global"


def extract_pair_id_from_rules_md(text: str) -> str | None:
    return extract_pair_id_from_md(text)


def parse_rules_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    agentic_tool_name: str = "rules",
    artifact_path: Path | None = None,
    canonical_name: str | None = None,
    provenance: str = "user",
    private: bool = False,
) -> dict[str, Any]:
    """Parse a Markdown rule file into the canonical rules shape.

    The filename stem is the stable user-facing identity. A frontmatter
    `name` is accepted for synthetic tests and importer-style callers, but
    `artifact_path` wins whenever it is available.
    """
    frontmatter_data, body = split_frontmatter(text, label="Rules")
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("rules")
    canonical["body"] = body

    if canonical_name is not None:
        canonical["name"] = canonical_name
    elif artifact_path is not None:
        canonical["name"] = artifact_path.stem
    elif "name" in frontmatter_data:
        canonical["name"] = str(frontmatter_data["name"])

    if "description" in frontmatter_data:
        canonical["description"] = str(frontmatter_data["description"])

    for field_name in CANONICAL_RULE_FIELDS:
        if field_name in frontmatter_data:
            canonical[field_name] = frontmatter_data[field_name]

    canonical["provenance"] = _coerce_provenance(
        frontmatter_data.get("provenance", provenance)
    )
    canonical["private"] = _coerce_bool(frontmatter_data.get("private", private))

    apply_per_tool_partition(
        canonical,
        agentic_tool_name=agentic_tool_name,
        frontmatter_data=frontmatter_data,
        tool_only_fields=TOOL_ONLY_RULE_FIELDS,
        known_fields=KNOWN_RULE_FIELDS,
    )

    if "pair_id" in frontmatter_data:
        canonical["pair_id"] = str(frontmatter_data["pair_id"])
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical


def render_rules_md(
    canonical: dict[str, Any],
    prior_text: str | None = None,
    *,
    agentic_tool_name: str = "rules",
) -> str:
    """Render a canonical rule to Markdown with YAML frontmatter."""
    frontmatter = frontmatter_for_render(prior_text)
    frontmatter.pop("provenance", None)
    frontmatter.pop("private", None)

    frontmatter["pair_id"] = canonical["pair_id"]
    frontmatter["name"] = canonical["name"]
    _set_or_pop(frontmatter, "description", canonical.get("description"))

    for field_name in CANONICAL_RULE_FIELDS:
        _set_or_pop(frontmatter, field_name, canonical.get(field_name))

    tool_only = canonical.get("per_agentic_tool_only", {}).get(agentic_tool_name, {})
    for field_name in TOOL_ONLY_RULE_FIELDS:
        _set_or_pop(frontmatter, field_name, tool_only.get(field_name))

    for key, value in canonical.get("per_agentic_tool_extra", {}).get(
        agentic_tool_name, {}
    ).items():
        if key not in KNOWN_RULE_FIELDS:
            frontmatter[key] = value

    return _render_markdown(frontmatter, canonical.get("body", ""))


def _render_markdown(frontmatter: dict[str, Any], body: str) -> str:
    rendered_frontmatter = yaml_dump(frontmatter).rstrip("\n")
    if body:
        return f"---\n{rendered_frontmatter}\n---\n{body}\n"
    return f"---\n{rendered_frontmatter}\n---\n"


def _set_or_pop(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None or value == "":
        target.pop(key, None)
        return
    target[key] = value


def _coerce_provenance(value: Any) -> str:
    provenance = str(value)
    if provenance not in VALID_PROVENANCES:
        raise ValueError("rules provenance must be 'user' or 'agent'")
    return provenance


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return bool(value)


__all__ = [
    "KNOWN_RULE_FIELDS",
    "GLOBAL_RULE_NAME",
    "extract_pair_id_from_rules_md",
    "parse_rules_md",
    "render_rules_md",
]
