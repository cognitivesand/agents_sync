"""Shared artifact-name resolution policies."""
from __future__ import annotations

from collections.abc import Iterable

CANONICAL_NAME_FIELD = "x-agents-sync-name"


def resolve_artifact_name(
    *,
    frontmatter_name: object = None,
    path_name: str | None = None,
    prior_name: object = None,
    override_name: str | None = None,
    precedence: Iterable[str],
    required_label: str | None = None,
) -> str | None:
    """Return the first available name according to ``precedence``.

    Supported precedence tokens are ``override``, ``frontmatter``, ``path``,
    and ``prior``. Empty strings are ignored so callers do not accidentally
    route artifacts to ``name=""``.
    """
    values = {
        "override": override_name,
        "frontmatter": frontmatter_name,
        "path": path_name,
        "prior": prior_name,
    }
    for source in precedence:
        if source not in values:
            raise ValueError(f"unknown name source: {source!r}")
        value = values[source]
        if value is None:
            continue
        name = str(value)
        if name:
            return name
    if required_label is not None:
        raise ValueError(f"{required_label} needs a non-empty artifact name")
    return None


__all__ = ["CANONICAL_NAME_FIELD", "resolve_artifact_name"]
