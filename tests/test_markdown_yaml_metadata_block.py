from __future__ import annotations

import pytest
from ruamel.yaml.error import YAMLError

from agents_sync.markdown_yaml_metadata_block import frontmatter_for_render
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
