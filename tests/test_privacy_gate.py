from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agents_sync.adoption.privacy_gate import PrivacyGateMixin


class _RecordingIO:
    def __init__(self) -> None:
        self.seen_prior: dict[str, Any] | None = None

    def parse(
        self,
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        self.seen_prior = prior_canonical
        return {
            "kind": "agent",
            "pair_id": "00000000-0000-4000-8000-000000000001",
            "name": "demo",
            "body": text,
        }


def test_privacy_gate_parses_target_with_prior_canonical_context():
    io = _RecordingIO()
    target_spec = SimpleNamespace(io={"agent": io})
    prior = {"kind": "agent", "name": "prior-name"}
    gate = PrivacyGateMixin()

    result = gate._load_target_canonical_for_privacy(
        "00000000-0000-4000-8000-000000000001",
        target_spec,  # type: ignore[arg-type]
        "agent",
        Path("target.md"),
        "body",
        prior,
    )

    assert result is not None
    assert io.seen_prior is prior
