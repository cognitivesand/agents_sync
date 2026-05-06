"""Claude .md parsing and rendering.

Uses ruamel.yaml for round-trip preservation when injecting fields into
an existing user-authored frontmatter (e.g., a fresh `pair_id`).
"""
from __future__ import annotations

import io
import re
from typing import Any

from ruamel.yaml import YAML

from agents_sync.canonical import empty_canonical, new_pair_id


FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z",
    re.DOTALL,
)

# Frontmatter keys the canonical maps explicitly. Anything else is preserved
# in canonical["claude_extra"] so user-set fields we don't yet model are not
# silently dropped.
KNOWN_CLAUDE_FIELDS = {
    "pair_id",
    "name",
    "description",
    "model",
    "effort",
    "tools",
    "disallowedTools",
    "permissionMode",
    "hooks",
    "mcpServers",
}


def _make_yaml() -> YAML:
    yml = YAML(typ="rt")
    yml.preserve_quotes = True
    yml.width = 4096
    yml.indent(mapping=2, sequence=4, offset=2)
    return yml


def _yaml_load(text: str) -> Any:
    if not text.strip():
        return None
    return _make_yaml().load(io.StringIO(text))


def _yaml_dump(data: Any) -> str:
    buf = io.StringIO()
    _make_yaml().dump(data, buf)
    return buf.getvalue()


def _split_csv(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value)]


def extract_pair_id_from_md(text: str) -> str | None:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    loaded = _yaml_load(match.group(1))
    if isinstance(loaded, dict) and isinstance(loaded.get("pair_id"), str):
        return loaded["pair_id"]
    return None


def parse_claude_md(text: str, prior_canonical: dict[str, Any] | None = None,
                    *, kind: str = "agent") -> dict[str, Any]:
    """Parse a Claude .md file into a canonical dict.

    If `prior_canonical` is given, fields the user has not changed retain
    their canonical state, and unmapped passthrough fields not present in
    the new frontmatter are dropped (since the user's frontmatter is the
    source of truth on the Claude side for Phase 2).
    """
    match = FRONTMATTER_RE.match(text)
    if match is None:
        frontmatter_data: dict[str, Any] = {}
        body = text.strip()
    else:
        raw_frontmatter, body_raw = match.groups()
        body = body_raw.strip()
        loaded = _yaml_load(raw_frontmatter)
        if loaded is None:
            frontmatter_data = {}
        elif not isinstance(loaded, dict):
            raise ValueError("Claude frontmatter must be a YAML mapping")
        else:
            frontmatter_data = dict(loaded)

    canonical = dict(prior_canonical) if prior_canonical else empty_canonical(kind)
    canonical["body"] = body

    if "name" in frontmatter_data:
        canonical["name"] = str(frontmatter_data["name"])
    if "description" in frontmatter_data:
        canonical["description"] = str(frontmatter_data["description"])
    if "model" in frontmatter_data:
        canonical["model"] = frontmatter_data["model"]
    if "effort" in frontmatter_data:
        canonical["effort"] = frontmatter_data["effort"]

    raw_tools = frontmatter_data.get("tools")
    if raw_tools is not None:
        canonical["tools"] = (
            list(raw_tools) if isinstance(raw_tools, list) else _split_csv(raw_tools)
        )

    raw_dis = frontmatter_data.get("disallowedTools")
    if raw_dis is not None:
        canonical["disallowed_tools"] = (
            list(raw_dis) if isinstance(raw_dis, list) else _split_csv(raw_dis)
        )

    if "permissionMode" in frontmatter_data:
        canonical["permission_mode"] = str(frontmatter_data["permissionMode"])

    claude_only: dict[str, Any] = {}
    if "hooks" in frontmatter_data:
        claude_only["hooks"] = frontmatter_data["hooks"]
    if "mcpServers" in frontmatter_data:
        claude_only["mcp_servers"] = frontmatter_data["mcpServers"]
    canonical["claude_only"] = claude_only

    canonical["claude_extra"] = {
        key: value
        for key, value in frontmatter_data.items()
        if key not in KNOWN_CLAUDE_FIELDS
    }

    if "pair_id" in frontmatter_data:
        canonical["pair_id"] = str(frontmatter_data["pair_id"])
    elif prior_canonical is None:
        canonical["pair_id"] = new_pair_id()

    return canonical


def render_claude_md(canonical: dict[str, Any], prior_text: str | None = None) -> str:
    """Render a canonical to Claude .md text.

    When `prior_text` is provided, the prior frontmatter is loaded with
    ruamel and mutated in place so existing key order, comments, and
    quoting style are preserved across writes.
    """
    yml = _make_yaml()

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

    if canonical.get("model") is not None:
        frontmatter["model"] = canonical["model"]
    if canonical.get("effort") is not None:
        frontmatter["effort"] = canonical["effort"]
    if canonical.get("tools"):
        frontmatter["tools"] = canonical["tools"]
    if canonical.get("disallowed_tools"):
        frontmatter["disallowedTools"] = canonical["disallowed_tools"]
    if canonical.get("permission_mode") is not None:
        frontmatter["permissionMode"] = canonical["permission_mode"]

    claude_only = canonical.get("claude_only", {})
    if "hooks" in claude_only:
        frontmatter["hooks"] = claude_only["hooks"]
    if "mcp_servers" in claude_only:
        frontmatter["mcpServers"] = claude_only["mcp_servers"]

    for key, value in canonical.get("claude_extra", {}).items():
        frontmatter[key] = value

    body = canonical.get("body", "")
    rendered_fm = _yaml_dump(frontmatter).rstrip("\n")
    if body:
        return f"---\n{rendered_fm}\n---\n{body}\n"
    return f"---\n{rendered_fm}\n---\n"
