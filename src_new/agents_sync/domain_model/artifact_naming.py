"""Artifact naming — slug derivation and the candidate key (pure, no I/O).

``slugify_name`` derives the filesystem-safe basename an artifact projects to on
every tool (sync is symmetric, so an artifact named *X* lives at the same slug on
every tool). ``candidate_key`` pairs a customization_type with that slug to group
id-less candidate surfaces that should be adopted as one artifact (US-03).
"""

from __future__ import annotations

import re

# A reconciliation key: the (customization_type, slug) pair an artifact resolves to. It is
# the identity two surfaces must share to be the same logical artifact (US-03), and the
# key the planner's collision and absorb guards group managed artifacts and candidates by.
type ReconciliationKey = tuple[str, str]

# Bare device names Windows refuses as file basenames, regardless of extension.
_WINDOWS_RESERVED_BASENAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{digit}" for digit in range(1, 10)}
    | {f"LPT{digit}" for digit in range(1, 10)}
)
_UNSAFE_RUN = re.compile(r"[^a-z0-9_-]+")
_HYPHEN_RUN = re.compile(r"-{2,}")
_PLACEHOLDER_SLUG = "converted"


def slugify_name(name: str) -> str:
    """Return the filesystem-safe slug for an artifact ``name``.

    Lowercased; any run of characters outside ``[a-z0-9_-]`` becomes a single
    hyphen; repeated hyphens collapse and edge hyphens are trimmed. A name with no
    safe characters yields a placeholder, and a slug that collides with a
    Windows-reserved basename is disambiguated with a ``-item`` suffix.
    """
    slug = _UNSAFE_RUN.sub("-", name.lower())
    slug = _HYPHEN_RUN.sub("-", slug).strip("-")
    if not slug:
        return _PLACEHOLDER_SLUG
    if slug.upper() in _WINDOWS_RESERVED_BASENAMES:
        return f"{slug}-item"
    return slug


def candidate_key(kind: str, name: str) -> ReconciliationKey:
    """Pair a customization_type with the slug, to group id-less candidates."""
    return (kind, slugify_name(name))
