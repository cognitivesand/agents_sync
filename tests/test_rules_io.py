"""Parse/render tests for the v0.5 `rules` customization_type."""
from __future__ import annotations

import textwrap
from pathlib import Path

from agents_sync.rules_io import parse_rules_md, render_rules_md


def test_parse_rules_uses_filename_stem_as_name():
    canonical = parse_rules_md(
        "Use clear names.\n",
        artifact_path=Path("Clean-Code.md"),
    )

    assert canonical["kind"] == "rules"
    assert canonical["name"] == "Clean-Code"
    assert canonical["body"] == "Use clear names."
    assert canonical["provenance"] == "user"
    assert canonical["private"] is False
    assert canonical["pair_id"]


def test_rules_known_fields_round_trip_through_frontmatter():
    text = textwrap.dedent(
        """\
        ---
        pair_id: 00000000-0000-4000-8000-000000000001
        description: Python files
        globs:
          - "**/*.py"
        alwaysApply: true
        trigger: manual
        vendor-field: keep
        ---
        Prefer small functions.
        """
    )

    canonical = parse_rules_md(
        text,
        agentic_tool_name="alpha",
        artifact_path=Path("python-style.md"),
    )
    rendered = render_rules_md(canonical, text, agentic_tool_name="alpha")
    parsed = parse_rules_md(
        rendered,
        canonical,
        agentic_tool_name="alpha",
        artifact_path=Path("python-style.md"),
    )

    assert parsed["pair_id"] == "00000000-0000-4000-8000-000000000001"
    assert parsed["name"] == "python-style"
    assert parsed["description"] == "Python files"
    assert parsed["globs"] == ["**/*.py"]
    assert parsed["alwaysApply"] is True
    assert parsed["per_agentic_tool_only"]["alpha"] == {"trigger": "manual"}
    assert parsed["per_agentic_tool_extra"]["alpha"] == {"vendor-field": "keep"}


def test_rules_private_and_agent_provenance_are_canonical_only_on_render():
    text = textwrap.dedent(
        """\
        ---
        provenance: agent
        private: true
        ---
        Local memory.
        """
    )

    canonical = parse_rules_md(text, artifact_path=Path("memory.md"))
    rendered = render_rules_md(canonical)

    assert canonical["provenance"] == "agent"
    assert canonical["private"] is True
    assert "provenance:" not in rendered
    assert "private:" not in rendered
