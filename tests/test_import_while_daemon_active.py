"""FR-15 (Import-while-active safety): an import may run while the daemon is
active; a concurrent import and daemon poll must not corrupt the shared state
record nor lose user-authored content, and the interleaving must converge to the
same managed state as running them sequentially.

Two mechanisms realise FR-15 and are pinned here:
  1. ``state.atomic_write_text`` (unique temp + ``os.replace``) — a daemon poll
     reading ``state.json`` while an import writes it never observes a torn record.
  2. canonical-as-truth idempotent reconcile (FR-14) — a poll interleaved with an
     import converges regardless of ordering.
"""

from __future__ import annotations

import json
import threading
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agents_sync.portable_archive import import_from_zip
from agents_sync.state import load_state

from ._helpers import make_syncer, skill_md


def _canonical(pair_id: str, name: str, body: str, last_modified: float) -> dict:
    return {
        "pair_id": pair_id,
        "kind": "skill",
        "name": name,
        "description": "d",
        "body": body,
        "per_agentic_tool_only": {},
        "per_agentic_tool_extra": {},
        "last_modified": last_modified,
        "generation": 1,
    }


def _build_zip(path: Path, canonicals: list[dict]) -> Path:
    out = path.parent / (path.stem + "_build")
    (out / "canonical").mkdir(parents=True, exist_ok=True)
    for c in canonicals:
        (out / "canonical" / f"{c['pair_id']}.json").write_text(json.dumps(c, sort_keys=True))
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "agents_sync_version": "0.5.6",
                "artifact_count": len(canonicals),
                "contains_secret_literals": False,
                "exported_at": "2026-05-31T00:00:00+00:00",
                "schema_version": 1,
                "source_host": "other",
                "source_platform": "Linux",
            }
        )
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.write(out / "manifest.json", "manifest.json")
        for c in canonicals:
            zf.write(out / "canonical" / f"{c['pair_id']}.json", f"canonical/{c['pair_id']}.json")
    return path


def _import(syncer, zip_path: Path):
    return import_from_zip(
        syncer.state_dir,
        zip_path,
        strategy="mtime_wins",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )


# A library large enough to widen the import's state-write window for the reader.
_IMPORTED = [
    _canonical(f"22222222-2222-4333-8444-5555555555{n:02d}", f"beta{n}", f"body-{n}", 500.0)
    for n in range(12)
]


def _seed_local_alpha(syncer) -> str:
    """Create one locally-authored managed skill and return its pair_id."""
    d = syncer.tool_root("claude", "skill") / "alpha"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(skill_md("alpha", body="local-authored"))
    syncer.sync_once()
    return next(iter(load_state(syncer.state_dir)))


def test_concurrent_read_during_import_never_sees_torn_state(tmp_path: Path) -> None:
    """FR-15: while an import rewrites state.json, a concurrent reader (standing in
    for a daemon poll's state load) only ever observes a well-formed record that
    still contains the locally-authored pair — no torn read, no lost content."""
    syncer = make_syncer(tmp_path)
    alpha_id = _seed_local_alpha(syncer)
    zip_path = _build_zip(tmp_path / "lib.zip", _IMPORTED)

    done = threading.Event()
    errors: list[BaseException] = []

    def reader() -> None:
        # Hammer load_state until the import finishes (hard-capped so a hung
        # writer can never wedge the test).
        for _ in range(200_000):
            if done.is_set():
                break
            try:
                state = load_state(syncer.state_dir)
            except BaseException as exc:  # a torn/partial read would raise here
                errors.append(exc)
                return
            # alpha's content must never vanish mid-import.
            if alpha_id not in state:
                errors.append(AssertionError("local pair disappeared during import"))
                return

    t = threading.Thread(target=reader)
    t.start()
    try:
        report = _import(syncer, zip_path)
    finally:
        done.set()
        t.join()

    assert not errors, errors[0]
    assert len(report.accepted) == len(_IMPORTED)
    final = load_state(syncer.state_dir)
    assert alpha_id in final  # local content survived
    assert len(final) == len(_IMPORTED) + 1  # alpha + every imported pair


def test_poll_interleaved_with_import_matches_sequential(tmp_path: Path) -> None:
    """FR-15: a poll before and after an import (the daemon racing the import)
    converges to exactly the managed state of the same import + poll run with no
    interleaving — same pairs, same projected bytes, no failures, idempotent."""
    # --- interleaved run: poll, import, poll ---
    (tmp_path / "interleaved").mkdir()
    (tmp_path / "sequential").mkdir()
    inter = make_syncer(tmp_path / "interleaved")
    alpha_id = _seed_local_alpha(inter)
    zip_path = _build_zip(tmp_path / "lib.zip", _IMPORTED)
    inter.sync_once()  # a daemon poll lands immediately before the import
    _import(inter, zip_path)
    poll = inter.sync_once()  # the poll that races/follows the import projects
    assert not poll.failed

    # --- sequential baseline: identical setup, import then a single poll ---
    seq = make_syncer(tmp_path / "sequential")
    _seed_local_alpha(seq)
    _import(seq, zip_path)
    seq.sync_once()

    def projected(syncer) -> dict[str, str]:
        # name -> body (the bytes after the frontmatter). A locally-authored
        # artifact is minted with a fresh random pair_id each setup, so the
        # frontmatter id is incidental; convergence is about names and content.
        root = syncer.tool_root("claude", "skill")
        return {
            p.parent.name: p.read_text().split("\n---\n", 1)[-1] for p in root.glob("*/SKILL.md")
        }

    assert projected(inter) == projected(seq)
    assert set(load_state(inter.state_dir)) >= {alpha_id}
    assert len(load_state(inter.state_dir)) == len(load_state(seq.state_dir))
    assert inter.sync_once().changed == 0  # converged + idempotent (NFR-05)
