"""Regression tests for SEC-B-01: archive_text path-traversal closure.

Slot names come from raw user-supplied keys in MCP server maps and were
previously interpolated into the archive target filename unchanged,
letting a slot key like ``"../../../tmp/pwned"`` escape the per-pair
archive directory. archive_text now sanitises the slot component and
defends in depth with an ``is_relative_to`` assertion on the resolved
path. These tests pin both layers.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from agents_sync import archive


def _new_pair_id() -> str:
    return str(uuid.uuid4())


def test_archive_text_neutralises_dotdot_traversal(tmp_path: Path) -> None:
    pair_id = _new_pair_id()
    side = "claude"
    archive.archive_text(
        tmp_path,
        pair_id,
        side,
        slot_name="../../../tmp/pwned",
        extension=".json",
        content="{}",
    )
    archive_dir = archive.archive_dir_for(tmp_path, pair_id, side)
    written = list(archive_dir.iterdir())
    assert len(written) == 1
    name = written[0].name
    assert ".." not in name
    assert "/" not in name
    assert "\\" not in name
    assert written[0].resolve().is_relative_to(archive_dir.resolve())
    assert not (tmp_path.parent / "tmp" / "pwned.json").exists()


def test_archive_text_neutralises_separator_in_slot_name(tmp_path: Path) -> None:
    pair_id = _new_pair_id()
    archive.archive_text(
        tmp_path,
        pair_id,
        "codex",
        slot_name="foo/bar/baz",
        extension=".json",
        content="{}",
    )
    archive_dir = archive.archive_dir_for(tmp_path, pair_id, "codex")
    children = list(archive_dir.iterdir())
    assert len(children) == 1
    assert "/" not in children[0].name
    assert children[0].resolve().parent == archive_dir.resolve()


def test_archive_text_neutralises_backslash_traversal(tmp_path: Path) -> None:
    pair_id = _new_pair_id()
    archive.archive_text(
        tmp_path,
        pair_id,
        "opencode",
        slot_name="..\\..\\evil",
        extension=".json",
        content="{}",
    )
    archive_dir = archive.archive_dir_for(tmp_path, pair_id, "opencode")
    children = list(archive_dir.iterdir())
    assert len(children) == 1
    assert "\\" not in children[0].name
    assert ".." not in children[0].name


def test_archive_text_neutralises_nul_byte(tmp_path: Path) -> None:
    pair_id = _new_pair_id()
    archive.archive_text(
        tmp_path,
        pair_id,
        "claude",
        slot_name="poison\x00here",
        extension=".json",
        content="{}",
    )
    archive_dir = archive.archive_dir_for(tmp_path, pair_id, "claude")
    children = list(archive_dir.iterdir())
    assert len(children) == 1
    assert "\x00" not in children[0].name


def test_archive_text_falls_back_when_slot_name_is_empty(tmp_path: Path) -> None:
    pair_id = _new_pair_id()
    archive.archive_text(
        tmp_path,
        pair_id,
        "claude",
        slot_name="",
        extension=".json",
        content="{}",
    )
    archive_dir = archive.archive_dir_for(tmp_path, pair_id, "claude")
    children = list(archive_dir.iterdir())
    assert len(children) == 1
    assert children[0].name.startswith("converted.json.")


def test_archive_text_falls_back_when_slot_name_is_whitespace(tmp_path: Path) -> None:
    pair_id = _new_pair_id()
    archive.archive_text(
        tmp_path,
        pair_id,
        "claude",
        slot_name="   ",
        extension=".json",
        content="{}",
    )
    archive_dir = archive.archive_dir_for(tmp_path, pair_id, "claude")
    children = list(archive_dir.iterdir())
    assert len(children) == 1
    assert children[0].name.startswith("converted.json.")


def test_archive_text_caps_overlong_slot_name(tmp_path: Path) -> None:
    pair_id = _new_pair_id()
    long_name = "a" * 5000
    archive.archive_text(
        tmp_path,
        pair_id,
        "claude",
        slot_name=long_name,
        extension=".json",
        content="{}",
    )
    archive_dir = archive.archive_dir_for(tmp_path, pair_id, "claude")
    children = list(archive_dir.iterdir())
    assert len(children) == 1
    stem = children[0].name.split(".json.", 1)[0]
    assert len(stem) <= 128


def test_archive_text_preserves_benign_slot_name(tmp_path: Path) -> None:
    pair_id = _new_pair_id()
    archive.archive_text(
        tmp_path,
        pair_id,
        "claude",
        slot_name="github",
        extension=".json",
        content='{"command": "gh-mcp"}',
    )
    archive_dir = archive.archive_dir_for(tmp_path, pair_id, "claude")
    children = list(archive_dir.iterdir())
    assert len(children) == 1
    assert children[0].name.startswith("github.json.")
    assert children[0].read_text(encoding="utf-8") == '{"command": "gh-mcp"}'


def test_archive_text_writes_inside_per_pair_directory(tmp_path: Path) -> None:
    """End-to-end: every adversarial slot name we can think of still lands
    inside the per-pair archive directory."""
    pair_id = _new_pair_id()
    side = "codex"
    archive_dir = archive.archive_dir_for(tmp_path, pair_id, side)
    adversarial = [
        "../../../tmp/pwned",
        "foo/../bar",
        "..\\..\\..\\windows\\System32\\evil",
        "/absolute/path",
        "//double/slash",
        "a/b/c/d",
        "\x00\x01\x02",
        "name with spaces",
        "中文-name",
    ]
    for slot in adversarial:
        archive.archive_text(
            tmp_path, pair_id, side,
            slot_name=slot, extension=".json", content="{}",
        )
    for written in archive_dir.iterdir():
        assert written.resolve().is_relative_to(archive_dir.resolve()), (
            f"{written} escaped the per-pair archive directory"
        )
