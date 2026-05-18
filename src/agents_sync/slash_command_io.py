"""Parse / render helpers for v0.5 slash_command artifacts.

Slash commands are single-file prompt templates. Most tools use Markdown with
optional YAML frontmatter; Gemini CLI uses a TOML document whose ``prompt`` key
is the command body.
"""
from __future__ import annotations

import io
import json
import re
import tomllib
from pathlib import Path
from typing import Any

from agents_sync.canonical import empty_canonical, new_pair_id
from agents_sync.claude_io import (
    FRONTMATTER_RE,
    _make_yaml,
    _normalize_markdown_text,
    _strip_bom_prefix,
    _yaml_load,
)
from agents_sync.codex_io import _normalize_toml_text
from agents_sync.state import target_slug


PAIR_ID_TOML_RE = re.compile(r'^pair_id\s*=\s*"([^"]+)"', re.MULTILINE)

KNOWN_MARKDOWN_FIELDS = frozenset({
    "pair_id",
    "name",
    "description",
    "argument-hint",
    "allowed-tools",
    "model",
    "agent",
    "mode",
})

KNOWN_TOML_FIELDS = frozenset({
    "pair_id",
    "name",
    "description",
    "argument_hint",
    "argument-hint",
    "allowed_tools",
    "allowed-tools",
    "model",
    "agent",
    "mode",
    "prompt",
})


def _yaml_dump(data: Any) -> str:
    buf = io.StringIO()
    _make_yaml().dump(data, buf)
    return buf.getvalue()


def _toml_key(key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _toml_scalar(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list) and all(
        not isinstance(item, (dict, list)) for item in value
    ):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"unsupported TOML scalar: {type(value).__name__}")


def _toml_dump_top_level(data: dict[str, Any]) -> str:
    return "".join(f"{_toml_key(key)} = {_toml_scalar(value)}\n" for key, value in data.items())


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value)]


def slash_command_slug(name: str) -> str:
    """Return a filesystem target for a slash-command name.

    Namespaced command names use ``:`` in the canonical form and nested folders
    on disk: ``git:commit`` becomes ``git/commit`` before the file suffix is
    appended by the renderer.
    """
    parts = [part for part in name.split(":") if part]
    if not parts:
        return target_slug(name)
    return "/".join(target_slug(part) for part in parts)


def slash_command_name_from_path(
    artifact_path: Path,
    *,
    artifact_root: Path | None = None,
) -> str:
    """Infer the canonical command name from a file path.

    When the commands root is known, subdirectories become ``:`` namespaces.
    Without the root, only the filename stem is safe to use.
    """
    if artifact_root is None:
        return artifact_path.stem
    try:
        relative = artifact_path.relative_to(artifact_root)
    except ValueError:
        return artifact_path.stem
    parts = list(relative.with_suffix("").parts)
    return ":".join(parts) if parts else artifact_path.stem


def _apply_path_identity(
    canonical: dict[str, Any],
    artifact_path: Path | None,
    artifact_root: Path | None,
) -> None:
    if artifact_path is not None:
        canonical["name"] = slash_command_name_from_path(
            artifact_path,
            artifact_root=artifact_root,
        )


def extract_pair_id_from_slash_command_markdown(text: str) -> str | None:
    text = _normalize_markdown_text(text)
    match = FRONTMATTER_RE.match(text)
    if match is None:
        return None
    loaded = _yaml_load(match.group(1))
    if isinstance(loaded, dict) and isinstance(loaded.get("pair_id"), str):
        return loaded["pair_id"]
    return None


def parse_slash_command_markdown(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    agentic_tool_name: str,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Parse a Markdown slash command into the canonical form."""
    text = _normalize_markdown_text(text)
    match = FRONTMATTER_RE.match(text)
    if match is None:
        frontmatter_data: dict[str, Any] = {}
        body = _strip_bom_prefix(text)
    else:
        raw_frontmatter, body = match.groups()
        loaded = _yaml_load(raw_frontmatter)
        if loaded is None:
            frontmatter_data = {}
        elif not isinstance(loaded, dict):
            raise ValueError("slash_command frontmatter must be a YAML mapping")
        else:
            frontmatter_data = dict(loaded)

    canonical = (
        dict(prior_canonical)
        if prior_canonical
        else empty_canonical("slash_command")
    )
    canonical["body"] = _strip_bom_prefix(body)
    _apply_path_identity(canonical, artifact_path, artifact_root)

    if not canonical.get("name") and "name" in frontmatter_data:
        canonical["name"] = str(frontmatter_data["name"])
    if "description" in frontmatter_data:
        canonical["description"] = str(frontmatter_data["description"])
    if "argument-hint" in frontmatter_data:
        canonical["argument_hint"] = str(frontmatter_data["argument-hint"])
    if "allowed-tools" in frontmatter_data:
        canonical["allowed_tools"] = _as_string_list(frontmatter_data["allowed-tools"])
    if "model" in frontmatter_data:
        canonical["model"] = frontmatter_data["model"]

    tool_only = {
        key: frontmatter_data[key]
        for key in ("agent", "mode")
        if key in frontmatter_data
    }
    per_tool_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_tool_only[agentic_tool_name] = tool_only
    canonical["per_agentic_tool_only"] = per_tool_only

    per_tool_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_tool_extra[agentic_tool_name] = {
        key: value
        for key, value in frontmatter_data.items()
        if key not in KNOWN_MARKDOWN_FIELDS
    }
    canonical["per_agentic_tool_extra"] = per_tool_extra

    if "pair_id" in frontmatter_data:
        canonical["pair_id"] = str(frontmatter_data["pair_id"])
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical


def render_slash_command_markdown(
    canonical: dict[str, Any],
    prior_text: str | None = None,
    *,
    agentic_tool_name: str,
) -> str:
    """Render a canonical slash command as Markdown with YAML frontmatter."""
    frontmatter: dict[str, Any] = {
        "pair_id": canonical["pair_id"],
    }
    if canonical.get("description"):
        frontmatter["description"] = canonical["description"]
    if canonical.get("argument_hint"):
        frontmatter["argument-hint"] = canonical["argument_hint"]
    if canonical.get("allowed_tools"):
        frontmatter["allowed-tools"] = canonical["allowed_tools"]
    if canonical.get("model") is not None:
        frontmatter["model"] = canonical["model"]

    tool_only = canonical.get("per_agentic_tool_only", {}).get(agentic_tool_name, {})
    for key in ("agent", "mode"):
        if key in tool_only:
            frontmatter[key] = tool_only[key]

    for key, value in canonical.get("per_agentic_tool_extra", {}).get(
        agentic_tool_name, {}
    ).items():
        frontmatter[key] = value

    rendered_fm = _yaml_dump(frontmatter).rstrip("\n")
    return f"---\n{rendered_fm}\n---\n{canonical.get('body', '')}"


def extract_pair_id_from_slash_command_toml(text: str) -> str | None:
    text = _normalize_toml_text(text)
    match = PAIR_ID_TOML_RE.search(text)
    return match.group(1) if match else None


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def parse_slash_command_toml(
    text: str,
    prior_canonical: dict[str, Any] | None = None,
    *,
    agentic_tool_name: str,
    artifact_path: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Parse a Gemini-style TOML slash command into the canonical form."""
    data = tomllib.loads(_normalize_toml_text(text))
    if not isinstance(data, dict):
        raise ValueError("slash_command TOML must be a table at root")

    canonical = (
        dict(prior_canonical)
        if prior_canonical
        else empty_canonical("slash_command")
    )
    _apply_path_identity(canonical, artifact_path, artifact_root)

    if not canonical.get("name") and "name" in data:
        canonical["name"] = str(data["name"])
    if "description" in data:
        canonical["description"] = str(data["description"])
    if "prompt" in data:
        canonical["body"] = str(data["prompt"])
    argument_hint = _first_present(data, "argument_hint", "argument-hint")
    if argument_hint is not None:
        canonical["argument_hint"] = str(argument_hint)
    allowed_tools = _first_present(data, "allowed_tools", "allowed-tools")
    if allowed_tools is not None:
        canonical["allowed_tools"] = _as_string_list(allowed_tools)
    if "model" in data:
        canonical["model"] = data["model"]

    tool_only = {
        key: data[key]
        for key in ("agent", "mode")
        if key in data
    }
    per_tool_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_tool_only[agentic_tool_name] = tool_only
    canonical["per_agentic_tool_only"] = per_tool_only

    per_tool_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_tool_extra[agentic_tool_name] = {
        key: value
        for key, value in data.items()
        if key not in KNOWN_TOML_FIELDS
    }
    canonical["per_agentic_tool_extra"] = per_tool_extra

    if "pair_id" in data:
        canonical["pair_id"] = str(data["pair_id"])
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical


def render_slash_command_toml(
    canonical: dict[str, Any],
    prior_text: str | None = None,
    *,
    agentic_tool_name: str,
) -> str:
    """Render a canonical slash command as the TOML variant."""
    data: dict[str, Any] = {
        "pair_id": canonical["pair_id"],
    }
    if canonical.get("description"):
        data["description"] = canonical["description"]
    if canonical.get("argument_hint"):
        data["argument_hint"] = canonical["argument_hint"]
    if canonical.get("allowed_tools"):
        data["allowed_tools"] = canonical["allowed_tools"]
    if canonical.get("model") is not None:
        data["model"] = canonical["model"]

    tool_only = canonical.get("per_agentic_tool_only", {}).get(agentic_tool_name, {})
    for key in ("agent", "mode"):
        if key in tool_only:
            data[key] = tool_only[key]

    for key, value in canonical.get("per_agentic_tool_extra", {}).get(
        agentic_tool_name, {}
    ).items():
        data[key] = value

    data["prompt"] = canonical.get("body", "")
    return _toml_dump_top_level(data)
