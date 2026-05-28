"""Codex .toml and SKILL.md parse / render.

Phase 3 adds parse functions so changes on the Codex side can be folded
back into the canonical and propagated to the Claude side.
"""
from __future__ import annotations

import io
import json
import re
import tomllib
from typing import Any

from ruamel.yaml import YAML

from agents_sync.canonical import empty_canonical, new_pair_id
from agents_sync.markdown_yaml_metadata_block import split_frontmatter


READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "LS"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

PAIR_ID_RE = re.compile(r'^pair_id\s*=\s*"([^"]+)"', re.MULTILINE)
_CORRUPTED_UTF8_BOM = "\u00ef\u00bb\u00bf"

KNOWN_CODEX_TOML_KEYS = {
    "pair_id",
    "name",
    "description",
    "developer_instructions",
    "nickname_candidates",
    "sandbox_mode",
    "model",
    "model_reasoning_effort",
    "mcp_servers",
    "skills",
}

CODEX_ONLY_FIELDS: tuple[str, ...] = (
    "sandbox_mode",
    "nickname_candidates",
    "mcp_servers",
    "skills",
)
CODEX_MODEL_ALIASES = {"inherit", "sonnet", "opus", "haiku"}
CODEX_REASONING_EFFORTS = {"low", "medium", "high", "xhigh"}

# v0.1 used to append a JSON metadata blob to developer_instructions; strip it
# on parse so adopted v0.1 artifacts don't leak the marker into canonical.body.
_LEGACY_REVIEW_MARKER = "\n\n---\nConverted Claude-specific metadata for manual review:"


def _make_yaml() -> YAML:
    yml = YAML(typ="rt")
    yml.preserve_quotes = True
    yml.width = 4096
    yml.indent(mapping=2, sequence=4, offset=2)
    return yml


def _yaml_dump(data: Any) -> str:
    buf = io.StringIO()
    _make_yaml().dump(data, buf)
    return buf.getvalue()


def _normalize_toml_text(text: str) -> str:
    if text.startswith("\ufeff"):
        return text[1:]
    # Defensive handling for already-corrupted BOM bytes rendered as text.
    if text.startswith(_CORRUPTED_UTF8_BOM):
        return text[3:]
    return text


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_key(key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key
    return toml_string(key)


def _toml_scalar(value: Any) -> str:
    if isinstance(value, str):
        return toml_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list) and all(
        not isinstance(item, (dict, list)) for item in value
    ):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"unsupported TOML scalar: {type(value).__name__}")


def _toml_section_name(parts: tuple[str, ...]) -> str:
    return ".".join(_toml_key(part) for part in parts)


def _emit_toml_table(
    lines: list[str],
    table: dict[str, Any],
    *,
    path: tuple[str, ...] = (),
) -> None:
    scalar_items: list[tuple[str, Any]] = []
    table_items: list[tuple[str, dict[str, Any]]] = []
    array_table_items: list[tuple[str, list[dict[str, Any]]]] = []

    for key, value in table.items():
        if isinstance(value, dict):
            table_items.append((key, value))
        elif (
            isinstance(value, list)
            and value
            and all(isinstance(item, dict) for item in value)
        ):
            array_table_items.append((key, value))
        else:
            scalar_items.append((key, value))

    for key, value in scalar_items:
        lines.append(f"{_toml_key(key)} = {_toml_scalar(value)}")

    for key, value in table_items:
        if lines and lines[-1] != "":
            lines.append("")
        child_path = path + (key,)
        lines.append(f"[{_toml_section_name(child_path)}]")
        _emit_toml_table(lines, value, path=child_path)

    for key, values in array_table_items:
        child_path = path + (key,)
        for value in values:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[[{_toml_section_name(child_path)}]]")
            _emit_toml_table(lines, value, path=child_path)


def _toml_dump(data: dict[str, Any]) -> str:
    lines: list[str] = []
    _emit_toml_table(lines, data)
    return "\n".join(lines).rstrip() + "\n"


def _codex_only_from_toml(data: dict[str, Any]) -> dict[str, Any]:
    return {
        field_name: data[field_name]
        for field_name in CODEX_ONLY_FIELDS
        if field_name in data
    }


def _codex_extra_from_toml(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in data.items()
        if key not in KNOWN_CODEX_TOML_KEYS
    }


def _stored_codex_extra(canonical: dict[str, Any]) -> dict[str, Any]:
    extras = canonical.get("per_agentic_tool_extra", {}).get("codex", {})
    return {
        key: value
        for key, value in extras.items()
        if key not in KNOWN_CODEX_TOML_KEYS
    }


def tool_base_name(tool: str) -> str:
    return tool.split("(", 1)[0].strip()


def infer_codex_sandbox(tools: list[str], disallowed_tools: list[str]) -> str | None:
    base_tools = {tool_base_name(t) for t in tools if t}
    base_denied = {tool_base_name(t) for t in disallowed_tools if t}
    if base_tools and base_tools <= READ_ONLY_TOOLS:
        return "read-only"
    if base_denied & WRITE_TOOLS:
        return "read-only"
    return None


def extract_pair_id(toml_text: str) -> str | None:
    toml_text = _normalize_toml_text(toml_text)
    match = PAIR_ID_RE.search(toml_text)
    return match.group(1) if match else None


def _strip_legacy_review_metadata(
    body: str, *, prior_canonical: dict[str, Any] | None,
) -> str:
    """Strip the v0.1-era 'Converted Claude-specific metadata for manual review'
    block from a body — but only when the prior canonical is older than v0.4
    (schema_version < 4) or absent (first sight of the artifact).

    The marker is a free-text 75-char string a user could legitimately type
    into a v0.4+ body. Version-gating the strip (audit slice 07 · CQ-16)
    keeps the migration behaviour for legacy artifacts while letting a v0.4+
    body contain the same prose without surprise truncation.
    """
    if prior_canonical is not None:
        from agents_sync.canonical import SCHEMA_VERSION

        prior_version = prior_canonical.get("schema_version", SCHEMA_VERSION)
        try:
            if int(prior_version) >= 4:
                return body
        except (TypeError, ValueError):
            # Unparseable schema_version is treated as "modern" — refuse to
            # truncate user data we cannot positively identify as legacy.
            return body
    idx = body.find(_LEGACY_REVIEW_MARKER)
    return body[:idx] if idx >= 0 else body


# ---------- agent ----------

def render_codex_agent_toml(
    canonical: dict[str, Any],
    prior_text: str | None = None,
) -> str:
    codex_only = canonical.get("per_agentic_tool_only", {}).get("codex", {})
    data: dict[str, Any] = {
        "pair_id": canonical["pair_id"],
        "name": canonical["name"],
    }
    if canonical.get("description"):
        data["description"] = canonical["description"]

    for field_name in CODEX_ONLY_FIELDS:
        if field_name in codex_only:
            data[field_name] = codex_only[field_name]

    if "sandbox_mode" not in data:
        sandbox = infer_codex_sandbox(
            canonical.get("tools", []),
            canonical.get("disallowed_tools", []),
        )
        if sandbox:
            data["sandbox_mode"] = sandbox

    model = canonical.get("model")
    if isinstance(model, str) and model not in CODEX_MODEL_ALIASES:
        data["model"] = model

    effort = canonical.get("effort")
    if isinstance(effort, str) and effort in CODEX_REASONING_EFFORTS:
        data["model_reasoning_effort"] = effort

    for key, value in _stored_codex_extra(canonical).items():
        data[key] = value

    instructions = canonical.get("body", "")
    if instructions:
        data["developer_instructions"] = instructions
    return _toml_dump(data)


def parse_codex_agent_toml(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse a Codex agent .toml into a canonical dict.

    If `prior_canonical` is given, per-agentic-tool state for other agentic
    tools survives untouched; Codex-owned fields reflect the current TOML.
    """
    text = _normalize_toml_text(text)
    data = tomllib.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Codex agent TOML must be a table at root")

    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("agent")

    if "name" in data:
        canonical["name"] = str(data["name"])
    if "description" in data:
        canonical["description"] = str(data["description"])
    if "developer_instructions" in data:
        canonical["body"] = _strip_legacy_review_metadata(
            str(data["developer_instructions"]),
            prior_canonical=prior_canonical,
        )
    if "model" in data:
        canonical["model"] = data["model"]
    if "model_reasoning_effort" in data:
        canonical["effort"] = data["model_reasoning_effort"]

    per_agentic_tool_only = dict(canonical.get("per_agentic_tool_only") or {})
    codex_only = _codex_only_from_toml(data)
    per_agentic_tool_only["codex"] = codex_only
    canonical["per_agentic_tool_only"] = per_agentic_tool_only

    per_agentic_tool_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_agentic_tool_extra["codex"] = _codex_extra_from_toml(data)
    canonical["per_agentic_tool_extra"] = per_agentic_tool_extra

    if "pair_id" in data:
        canonical["pair_id"] = str(data["pair_id"])
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical


# ---------- skill ----------

def render_codex_skill_md(canonical: dict[str, Any]) -> str:
    """Render the SKILL.md file for the Codex side of a skill pair.

    No leading auto-comment is emitted so that parsing the rendered file
    back into a canonical is a clean fixed point (NFR-06).
    """
    frontmatter = {"pair_id": canonical["pair_id"], "name": canonical["name"]}
    if canonical.get("description"):
        frontmatter["description"] = canonical["description"]

    body = canonical.get("body", "").strip()

    parts = [
        "---",
        _yaml_dump(frontmatter).rstrip(),
        "---",
        "",
        body,
    ]
    return "\n".join(parts).rstrip() + "\n"


def parse_codex_skill_md(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse a Codex skill SKILL.md into a canonical dict."""
    frontmatter_data, body = split_frontmatter(text, label="Codex SKILL.md")

    canonical = dict(prior_canonical) if prior_canonical else empty_canonical("skill")
    canonical["body"] = body

    if "name" in frontmatter_data:
        canonical["name"] = str(frontmatter_data["name"])
    if "description" in frontmatter_data:
        canonical["description"] = str(frontmatter_data["description"])

    per_agentic_tool_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_agentic_tool_extra["codex"] = {
        key: value
        for key, value in frontmatter_data.items()
        if key not in {"pair_id", "name", "description"}
    }
    canonical["per_agentic_tool_extra"] = per_agentic_tool_extra

    if "pair_id" in frontmatter_data:
        canonical["pair_id"] = str(frontmatter_data["pair_id"])
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical
