"""Unit tests for the global-rules pure helper (S12).

Whole-file global rules fold through the ``markdown_frontmatter`` dialect — they
differ from any other front-matter artifact only by recipe *data*, not wire code —
so this module owns just one rules-specific *pure* helper: ``detect_framework_specific``.
It is the tool-private-path text scan the read-phase egress guard consumes to hold a
framework-specific rules file back from other tools (US-15 AC-6). ``@import``
resolution (filesystem I/O) and the hold-back *enforcement* live in the read phase
(S17-S19), not here, so they are out of this step's scope.

The scan is separator-agnostic (Windows backslashes normalise) and case-insensitive,
and it returns the *matched token* (not just a bool) so the guard can name it in the
``rules_framework_specific_held_back`` warning. Pure in-memory tests; no I/O, no boundary.
"""

from __future__ import annotations

import pytest

from agents_sync.dialects.global_rules import detect_framework_specific


@pytest.mark.parametrize(
    ("body", "expected_token"),
    [
        ("See ~/.claude/skills for details.", ".claude/"),
        ("edit .codex/prompts/foo", ".codex/"),
        ("rules live in ~/.cursor/rules", ".cursor/"),
        ("put it in ~/.gemini/commands", ".gemini/"),
        ("opencode config at ~/.opencode/agent", ".opencode/"),
        ("copilot dir ~/.copilot/config", ".copilot/"),
        ("see ~/.config/opencode/opencode.json", ".config/opencode/"),
        ("look under ~/.config/github-copilot/", ".config/github-copilot/"),
    ],
)
def test_flags_each_tool_private_root_with_its_token(body: str, expected_token: str) -> None:
    """Each tool-private directory trips the scan and the matched token is returned by name."""
    assert detect_framework_specific(body) == expected_token


def test_normalises_windows_backslash_separators() -> None:
    """A backslash path trips the same as its forward-slash form, so content flags on every OS."""
    assert detect_framework_specific(r"on windows: C:\Users\me\.cursor\rules") == ".cursor/"


def test_scan_is_case_insensitive() -> None:
    """An upper-cased private path still trips — detection must not be defeated by casing."""
    assert detect_framework_specific("Edit ~/.CLAUDE/Skills now.") == ".claude/"


def test_returns_none_for_generic_instructions() -> None:
    """Ordinary guidance carrying no tool-private path is propagatable (returns None)."""
    assert detect_framework_specific("Always write small, tested functions.") is None


@pytest.mark.parametrize(
    "ide_or_repo_dir",
    ["config in .github/workflows", "open .vscode/settings", "in .git/hooks"],
)
def test_ignores_ide_and_repo_directories(ide_or_repo_dir: str) -> None:
    """Detection is tool-private dirs only — IDE and repo dirs are not held back."""
    assert detect_framework_specific(ide_or_repo_dir) is None


def test_returns_none_for_empty_text() -> None:
    """An empty rules body carries no private path, so it is not framework-specific."""
    assert detect_framework_specific("") is None


def test_dash_copilot_does_not_falsely_trip_dot_copilot_token() -> None:
    """``github-copilot/`` must match its own ``.config/github-copilot/`` token, not ``.copilot/``.

    The ``-copilot/`` substring is not the ``.copilot/`` token, so a github-copilot path is
    not mis-attributed to the bare copilot root — the returned token names the real match.
    """
    token = detect_framework_specific("~/.config/github-copilot/mcp.json")
    assert token == ".config/github-copilot/"
