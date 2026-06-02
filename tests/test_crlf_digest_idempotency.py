"""Change detection must be line-ending-insensitive.

A skill ``SKILL.md`` authored with CRLF line endings (e.g. edited by a Windows
editor) must not be seen as perpetually "changed". The daemon reads artifact
text with universal-newline normalization, so the recorded digest and the
discovery digest must hash the *same* normalized text — otherwise every poll
detects a phantom change and re-projects forever (regression: the digest write
path hashed raw bytes while discovery hashed normalized text).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from ._helpers import make_syncer, skill_md


def _write_crlf(path: Path, text: str) -> None:
    """Write ``text`` with CRLF endings, as Path.write_text does on Windows."""
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))


def test_crlf_authored_skill_does_not_reproject_forever(tmp_path: Path) -> None:
    syncer = make_syncer(tmp_path)

    demo = syncer.tool_root("claude", "skill") / "demo"
    demo.mkdir(parents=True)
    _write_crlf(demo / "SKILL.md", skill_md("demo", body="v1"))
    syncer.sync_once()  # adopt + project

    md = demo / "SKILL.md"
    _write_crlf(md, md.read_text().replace("v1", "v2"))
    syncer.sync_once()  # project the edit

    # The CRLF source must not be perceived as changed on the next poll.
    assert syncer.sync_once().changed == 0
