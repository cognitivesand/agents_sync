"""Generic Markdown parse/render helpers for v0.5 `rules` artifacts."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agents_sync.artifact_names import resolve_artifact_name
from agents_sync.canonical import (
    apply_per_tool_partition,
    empty_canonical,
    new_pair_id,
)
from agents_sync.markdown_yaml_metadata_block import (
    extract_pair_id_from_md,
    frontmatter_for_render,
    render_markdown_with_metadata_block,
    set_or_remove_empty_metadata_field,
    split_frontmatter,
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

# US-15: tool-private directory path tokens. A `rules` body that references
# any agentic_tool's own home/config directory is treated as framework-specific
# and must not propagate to other tools (the whole file is held back). Matched
# as case-insensitive, slash-normalised path substrings, so `~/.claude/skills`
# trips `.claude/`. Derived from the per-tool config roots in config.py; extend
# here when a new tool's private root is added.
FRAMEWORK_SPECIFIC_PATH_TOKENS: tuple[str, ...] = (
    ".claude/",
    ".codex/",
    ".cursor/",
    ".gemini/",
    ".opencode/",
    ".copilot/",
    ".config/opencode/",
    ".config/github-copilot/",
)

# US-15: a global-rules `@import` directive — Claude Code's `@path` include
# syntax — on its own line (optionally indented). Inline @mentions are not
# treated as imports.
_IMPORT_LINE_RE = re.compile(r"^\s*@(\S+)\s*$")
_MAX_IMPORT_DEPTH = 10


class RulesImportError(ValueError):
    """A `rules` `@import` directive could not be resolved.

    Raised for a missing / unreadable target, a target escaping the tool's
    rules root, or an import cycle. The per-pair handler catches it (fail
    closed: the artifact is skipped, logged, never partially synced) — US-15
    AC-4.
    """


def detect_framework_specific(text: str) -> str | None:
    """Return the first tool-private path token present in ``text``, or None.

    Case-insensitive and separator-agnostic (Windows backslashes are
    normalised), so the same content trips on every platform.
    """
    normalized = text.replace("\\", "/").lower()
    for token in FRAMEWORK_SPECIFIC_PATH_TOKENS:
        if token in normalized:
            return token
    return None


def resolve_rules_imports(
    body: str,
    root: Path,
    *,
    _seen: frozenset[Path] = frozenset(),
    _depth: int = 0,
) -> tuple[str, bool]:
    """Inline `@import` directives in ``body`` (depth-first, in order).

    Returns ``(effective_body, had_import)``. When no directive is present the
    original ``body`` is returned verbatim (no reformatting). Imports resolve
    only within ``root``; an escaping target, a missing/unreadable target, or a
    cycle raises :class:`RulesImportError`.
    """
    if _depth > _MAX_IMPORT_DEPTH:
        raise RulesImportError("rules @import nesting exceeds maximum depth")
    root_resolved = root.resolve()
    out_lines: list[str] = []
    had_import = False
    for line in body.splitlines():
        match = _IMPORT_LINE_RE.match(line)
        if match is None:
            out_lines.append(line)
            continue
        had_import = True
        rel = match.group(1)
        target = (root / rel).resolve()
        if target != root_resolved and root_resolved not in target.parents:
            raise RulesImportError(f"rules @import escapes rules root: {rel}")
        if target in _seen:
            raise RulesImportError(f"rules @import cycle detected: {rel}")
        try:
            imported = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise RulesImportError(f"rules @import target unreadable: {rel}") from exc
        nested, _ = resolve_rules_imports(
            imported, root, _seen=_seen | {target}, _depth=_depth + 1,
        )
        out_lines.append(nested)
    if not had_import:
        return body, False
    result = "\n".join(out_lines)
    if body.endswith("\n"):
        result += "\n"
    return result, True


def extract_pair_id_from_rules_md(text: str) -> str | None:
    return extract_pair_id_from_md(text)


def parse_rules_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    agentic_tool_name: str = "rules",
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
    canonical_name: str | None = None,
    provenance: str = "user",
    private: bool = False,
) -> dict[str, Any]:
    """Parse a Markdown rule file into the canonical rules shape.

    The filename stem is the stable user-facing identity. A frontmatter
    `name` is accepted for synthetic tests and importer-style callers, but
    `artifact_path` wins whenever it is available.

    When ``artifact_root`` is supplied, `@import` directives in the body are
    resolved into an *effective* body used for propagation (US-15); the
    original directive-bearing body is preserved under ``rules_source_body``
    keyed to ``agentic_tool_name`` so re-rendering to the source tool keeps the
    user's pointer intact (US-15 AC-2). The effective body is scanned for
    tool-private path tokens; a match sets ``framework_specific`` so the egress
    guard holds the whole file back from other tools.
    """
    frontmatter_data, body = split_frontmatter(text, label="Rules")
    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("rules")

    effective_body = body
    if artifact_root is not None:
        effective_body, had_imports = resolve_rules_imports(body, artifact_root)
        if had_imports:
            canonical["rules_source_body"] = body
            canonical["rules_import_origin"] = agentic_tool_name
        elif canonical.get("rules_import_origin") == agentic_tool_name:
            canonical.pop("rules_source_body", None)
            canonical.pop("rules_import_origin", None)
    canonical["body"] = effective_body

    framework_token = detect_framework_specific(effective_body)
    canonical["framework_specific"] = framework_token is not None
    if framework_token is not None:
        canonical["framework_specific_token"] = framework_token
    else:
        canonical.pop("framework_specific_token", None)

    name = resolve_artifact_name(
        override_name=canonical_name,
        path_name=artifact_path.stem if artifact_path is not None else None,
        frontmatter_name=frontmatter_data.get("name"),
        prior_name=canonical.get("name"),
        precedence=("override", "path", "frontmatter", "prior"),
    )
    if name is not None:
        canonical["name"] = name

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
    set_or_remove_empty_metadata_field(
        frontmatter, "description", canonical.get("description"),
    )

    for field_name in CANONICAL_RULE_FIELDS:
        set_or_remove_empty_metadata_field(
            frontmatter, field_name, canonical.get(field_name),
        )

    tool_only = canonical.get("per_agentic_tool_only", {}).get(agentic_tool_name, {})
    for field_name in TOOL_ONLY_RULE_FIELDS:
        set_or_remove_empty_metadata_field(
            frontmatter, field_name, tool_only.get(field_name),
        )

    for key, value in canonical.get("per_agentic_tool_extra", {}).get(
        agentic_tool_name, {}
    ).items():
        if key not in KNOWN_RULE_FIELDS:
            frontmatter[key] = value

    # US-15 AC-2: render the original directive-bearing body back to the tool
    # that authored the @import structure; every other tool receives the
    # resolved effective body.
    body = canonical.get("body", "")
    if (
        canonical.get("rules_import_origin") == agentic_tool_name
        and canonical.get("rules_source_body") is not None
    ):
        body = canonical["rules_source_body"]

    return render_markdown_with_metadata_block(frontmatter, body)


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
    "FRAMEWORK_SPECIFIC_PATH_TOKENS",
    "RulesImportError",
    "detect_framework_specific",
    "resolve_rules_imports",
    "extract_pair_id_from_rules_md",
    "parse_rules_md",
    "render_rules_md",
]
