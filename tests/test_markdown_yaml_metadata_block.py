from __future__ import annotations

import pytest
from ruamel.yaml.error import YAMLError

from agents_sync.markdown_yaml_metadata_block import (
    extract_pair_id_from_md,
    frontmatter_for_render,
)
from agents_sync.parser_bounds import MAX_PARSE_BYTES, ParserBoundsExceeded
from agents_sync.rules_io import parse_rules_md, render_rules_md

PAIR_ID = "11111111-2222-4333-8444-555555555555"
MALFORMED_FRONTMATTER = "---\nname: [unclosed\n---\nbody\n"


def test_frontmatter_for_render_falls_back_on_unparseable_yaml():
    frontmatter = frontmatter_for_render(MALFORMED_FRONTMATTER)

    assert dict(frontmatter) == {}


def test_render_rules_md_falls_back_when_prior_frontmatter_is_unparseable():
    canonical = {
        "kind": "rules",
        "pair_id": PAIR_ID,
        "name": "clean-code",
        "description": "Prefer clear names",
        "body": "Use clear names.",
        "per_agentic_tool_only": {"alpha": {}},
        "per_agentic_tool_extra": {"alpha": {}},
    }

    rendered = render_rules_md(
        canonical,
        MALFORMED_FRONTMATTER,
        agentic_tool_name="alpha",
    )

    assert f"pair_id: {PAIR_ID}" in rendered
    assert "name: clean-code" in rendered
    assert "description: Prefer clear names" in rendered


def test_parse_rules_md_still_rejects_unparseable_frontmatter():
    with pytest.raises(YAMLError):
        parse_rules_md(MALFORMED_FRONTMATTER, agentic_tool_name="alpha")


def test_extract_pair_id_recovers_from_malformed_surrounding_metadata():
    # FR-11: an unquoted `: ` in the description is invalid YAML, but the
    # injected pair_id line is intact — the id must be recovered in isolation
    # rather than lost to a field we do not own (the real-world failure that
    # was `code_and_tests_quality_review/SKILL.md`).
    text = (
        f"---\npair_id: {PAIR_ID}\nname: demo\n"
        "description: source/test pair: each pair breaks the yaml\n---\nbody\n"
    )
    assert extract_pair_id_from_md(text) == PAIR_ID


def test_extract_pair_id_returns_none_when_malformed_and_no_id_tag():
    # FR-11: with no recoverable id tag, malformed metadata yields None — never
    # a raise (architecture §5.1 point 3).
    text = "---\nname: demo\ndescription: a: b: c\n---\nbody\n"
    assert extract_pair_id_from_md(text) is None


def test_extract_pair_id_enforces_global_parse_bound():
    with pytest.raises(ParserBoundsExceeded):
        extract_pair_id_from_md("x" * (MAX_PARSE_BYTES + 1))


def test_frontmatter_for_render_enforces_global_parse_bound():
    with pytest.raises(ParserBoundsExceeded):
        frontmatter_for_render("x" * (MAX_PARSE_BYTES + 1))
