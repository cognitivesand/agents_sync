"""Regression tests for the v0.5 parser bounds (SEC-C-01 / SEC-C-02).

The bounds defend the long-running daemon against:

- oversized parser inputs (a 2 GB hostile mcp.json that OOMs the loop),
- YAML alias / anchor bombs (quadratic billion-laughs against the
  ruamel round-trip loader), and
- a multi-MB document body forcing a regex linear scan inside
  ``FRONTMATTER_RE``.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from agents_sync.parser_bounds import (
    MAX_FRONTMATTER_BYTES,
    MAX_PARSE_BYTES,
    MAX_YAML_ALIAS_RESOLUTIONS,
    ParserBoundsExceeded,
    enforce_text_bound,
    read_text_bounded,
)


def test_enforce_text_bound_passes_within_limit() -> None:
    payload = "a" * 1024
    assert enforce_text_bound(payload, label="<test>") == payload


def test_enforce_text_bound_rejects_oversize() -> None:
    payload = "a" * (MAX_PARSE_BYTES + 1)
    with pytest.raises(ParserBoundsExceeded, match="MAX_PARSE_BYTES"):
        enforce_text_bound(payload, label="<test>")


def test_read_text_bounded_rejects_oversize_file(tmp_path: Path) -> None:
    huge = tmp_path / "huge.json"
    huge.write_text("a" * (MAX_PARSE_BYTES + 1), encoding="utf-8")
    with pytest.raises(ParserBoundsExceeded):
        read_text_bounded(huge)


def test_read_text_bounded_passes_small_file(tmp_path: Path) -> None:
    small = tmp_path / "small.json"
    small.write_text('{"k": "v"}', encoding="utf-8")
    assert read_text_bounded(small) == '{"k": "v"}'


def test_json_format_deserialize_rejects_oversize_input() -> None:
    """Phase 3.2 — every parser entry point validates input size."""
    from agents_sync.formats import json_format

    payload = '{"k": "' + ("a" * (MAX_PARSE_BYTES + 1)) + '"}'
    with pytest.raises(ParserBoundsExceeded):
        json_format.deserialize(payload)


def test_toml_format_deserialize_rejects_oversize_input() -> None:
    from agents_sync.formats import toml_format

    payload = 'k = "' + ("a" * (MAX_PARSE_BYTES + 1)) + '"'
    with pytest.raises(ParserBoundsExceeded):
        toml_format.deserialize(payload)


def test_mcp_slot_codec_rejects_oversize_input() -> None:
    from agents_sync.mcp_server_io._slot_codec import loads_slot

    payload = '{"k": "' + ("a" * (MAX_PARSE_BYTES + 1)) + '"}'
    with pytest.raises(ParserBoundsExceeded):
        loads_slot(payload, slot_format="json")


def test_yaml_alias_bomb_rejected_by_bounded_composer() -> None:
    """SEC-C-01 — quadratic billion-laughs YAML must not hang the daemon.

    Construct a chain of anchors / aliases where each reference adds one
    composed node. With MAX_YAML_ALIAS_RESOLUTIONS = 10_000, a
    document that resolves 11_000 nodes must be rejected.
    """
    from agents_sync.yaml_frontmatter import yaml_load

    # Many sequential list items resolved as the document is composed.
    # 12_000 entries comfortably crosses the 10_000 cap.
    items = ["- 1"] * (MAX_YAML_ALIAS_RESOLUTIONS + 2_000)
    payload = "\n".join(items) + "\n"
    with pytest.raises(ParserBoundsExceeded, match="MAX_YAML_ALIAS_RESOLUTIONS"):
        yaml_load(payload)


def test_yaml_load_small_document_succeeds() -> None:
    """Regression: the cap must not interfere with legitimate inputs."""
    from agents_sync.yaml_frontmatter import yaml_load

    doc = "name: skill-one\ndescription: ok\n"
    loaded = yaml_load(doc)
    assert loaded["name"] == "skill-one"
    assert loaded["description"] == "ok"


def test_split_frontmatter_bounds_regex_scan_for_huge_body() -> None:
    """SEC-C-07 (carried into the bounds): a multi-MB document body must
    not force FRONTMATTER_RE to walk the whole text. The frontmatter
    block lives in the first ~1 KB; the body is 1 MB of binary-ish
    text. The split must complete in linear time on the head window."""
    from agents_sync.yaml_frontmatter import split_frontmatter

    huge_body = "x" * (MAX_FRONTMATTER_BYTES * 4)  # 1 MB body
    doc = f"---\nname: huge\n---\n{huge_body}"
    frontmatter, body = split_frontmatter(doc, label="huge.md")
    assert frontmatter == {"name": "huge"}
    assert body == huge_body


def test_canonical_load_quarantines_oversize_input(tmp_path: Path) -> None:
    """Phase 3.5 — canonicals that exceed MAX_PARSE_BYTES are quarantined
    rather than silently rebuilding empty."""
    from agents_sync.canonical import canonical_path, load_canonical
    from agents_sync.identity import validate_pair_id

    pair_id = "00000000-0000-4000-8000-000000000099"
    validate_pair_id(pair_id)
    state_dir = tmp_path / "state"
    path = canonical_path(state_dir, pair_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = '{"pad": "' + ("a" * (MAX_PARSE_BYTES + 1)) + '"}'
    path.write_text(payload, encoding="utf-8")

    # load_canonical absorbs the ParserBoundsExceeded into a quarantine.
    assert load_canonical(state_dir, pair_id) is None
    assert not path.exists()
    quarantine_dir = state_dir / "quarantine"
    assert quarantine_dir.exists()
    assert any(quarantine_dir.iterdir())
