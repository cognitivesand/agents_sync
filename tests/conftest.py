"""Shared test fixtures.

The actual wiring lives in :mod:`tests._helpers` (Phase 2.7 extraction) so a
test that needs a Syncer with non-default tool enablement can call
``make_syncer(tmp_path, opencode_enabled=False)`` instead of copying the
fixture's body inline.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.sync import Syncer

from ._helpers import make_syncer


@pytest.fixture
def syncer(tmp_path: Path) -> Syncer:
    return make_syncer(tmp_path)
