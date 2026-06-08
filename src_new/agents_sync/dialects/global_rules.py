"""Global-rules pure helper — framework-specificity detection (no I/O).

Whole-file global rules (``AGENTS.md`` / ``CLAUDE.md``) are translated by the
``markdown_frontmatter`` dialect: they are front-matter + body like any other
markdown artifact and differ only by *recipe data*, not wire code, so they need no
dialect of their own. What is genuinely rules-specific and *pure* is this one
predicate, which this module owns.

``detect_framework_specific`` scans a rules body for a token that names an agentic
tool's own private directory (``~/.claude/skills``, ``.codex/prompts``, …). The read
phase's egress guard (S17-S19) calls it to **hold a framework-specific rules file
back** from other tools — a Claude-only path must not be projected onto Codex (US-15
AC-6). The scan is separator-agnostic (Windows ``\\`` normalises) and case-insensitive
so the same content trips on every platform, and it returns the *matched token* so the
guard can name it in the ``rules_framework_specific_held_back`` warning.

The ``@import`` resolution and the hold-back *enforcement* are read-phase concerns
(filesystem I/O and the planner) and live there, not here.
"""

from __future__ import annotations

# Tool-private directory path tokens. A rules body that references any agentic tool's
# own home/config directory is framework-specific and must not propagate (the whole
# file is held back). Matched as case-insensitive, slash-normalised substrings, so
# ``~/.claude/skills`` trips ``.claude/``. Scope is tool-private dirs only (not IDE or
# repo dirs like ``.github/``), keeping the false-positive rate low. When tools become
# data (S20) these derive from the per-tool roots; until then they live here, per YAGNI.
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


def detect_framework_specific(text: str) -> str | None:
    """Return the first tool-private path token present in ``text``, else ``None``.

    Case-insensitive and separator-agnostic (Windows backslashes are normalised), so
    the same content trips on every platform. A return value is the matched token,
    which the egress guard names in its hold-back warning (US-15 AC-6).
    """
    normalized = text.replace("\\", "/").lower()
    for token in FRAMEWORK_SPECIFIC_PATH_TOKENS:
        if token in normalized:
            return token
    return None


__all__ = ["FRAMEWORK_SPECIFIC_PATH_TOKENS", "detect_framework_specific"]
