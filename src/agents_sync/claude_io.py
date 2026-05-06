from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z",
    re.DOTALL,
)


@dataclass(frozen=True)
class MarkdownDoc:
    path: Path
    frontmatter: dict[str, Any]
    body: str


def read_markdown(path: Path) -> MarkdownDoc:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)

    if not match:
        return MarkdownDoc(path=path, frontmatter={}, body=text.strip())

    raw_frontmatter, body = match.groups()
    data = yaml.safe_load(raw_frontmatter) or {}

    if not isinstance(data, dict):
        raise ValueError(f"{path}: YAML frontmatter must be a mapping")

    return MarkdownDoc(path=path, frontmatter=dict(data), body=body.strip())
