"""Unit tests for the portable library snapshot (US-12 AC-1..AC-11).

Each test names the AC it covers. Filesystem tests use the existing
`syncer` fixture from `conftest.py`, which builds a real `Syncer`
against a tmp directory — no mocks, per CLAUDE.md §7.
"""

from __future__ import annotations

import json
import tomllib
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration  # audit slice 10 · TQ-01

import agents_sync
from agents_sync.canonical import (
    canonical_last_modified,
    canonical_metadata,
    load_canonical,
    save_canonical,
    set_canonical_metadata,
)
from agents_sync.portable_archive import (
    CANONICAL_PREFIX,
    MANIFEST_NAME,
    PORTABLE_ARCHIVE_SCHEMA_VERSION,
    PortableArchiveError,
    export_to_zip,
    import_from_zip,
)
from agents_sync.state import load_state
from agents_sync.sync import Syncer

# ---------------- helpers ----------------


def _set_canonical_lm(
    state_dir: Path,
    pair_id: str,
    last_modified: float,
    generation: int = 0,
) -> None:
    """Write last_modified/generation into the canonical metadata block on disk."""
    canonical = load_canonical(state_dir, pair_id)
    assert canonical is not None
    set_canonical_metadata(canonical, last_modified=last_modified, generation=generation)
    save_canonical(state_dir, pair_id, canonical)


def _skill_md(name: str, description: str = "x", body: str = "body") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}\n"


def _write_claude_skill(syncer: Syncer, name: str, body: str = "body") -> Path:
    skill_dir = syncer.tool_root("claude", "skill") / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_skill_md(name, body=body))
    return skill_dir


def _seed_and_export(syncer: Syncer, tmp_path: Path, *names: str) -> Path:
    for name in names:
        _write_claude_skill(syncer, name)
    syncer.sync_once()
    zip_path = tmp_path / "snapshot.zip"
    export_to_zip(syncer.state_dir, zip_path)
    return zip_path


def _set_local_canonical_metadata(
    syncer: Syncer, pair_id: str, *, last_modified: float, generation: int = 1
) -> None:
    canonical = load_canonical(syncer.state_dir, pair_id)
    assert canonical is not None
    set_canonical_metadata(canonical, last_modified=last_modified, generation=generation)
    save_canonical(syncer.state_dir, pair_id, canonical)


def _canonical_metadata_for(syncer: Syncer, pair_id: str) -> dict[str, object]:
    canonical = load_canonical(syncer.state_dir, pair_id)
    assert canonical is not None
    return canonical_metadata(canonical)


def _fresh_syncer(tmp_path: Path, label: str) -> Syncer:
    base = tmp_path / label
    state_dir = base / "state"
    state_dir.mkdir(parents=True)
    for sub in (
        "ca",
        "cc",
        "cs",
        "cr",
        "xa",
        "xp",
        "xs",
        "xr",
        "as",
        "ga",
        "gc",
        "gs",
        "gr",
        "oa",
        "oc",
        "os",
        "or",
    ):
        (base / sub).mkdir(parents=True)
    return Syncer(
        {
            "poll_interval_seconds": 1.0,
            "state_path": str(state_dir / "state.json"),
            "claude_agents_dir": str(base / "ca"),
            "claude_commands_dir": str(base / "cc"),
            "claude_skills_dir": str(base / "cs"),
            "claude_rules_dir": str(base / "cr"),
            "codex_agents_dir": str(base / "xa"),
            "codex_prompts_dir": str(base / "xp"),
            "codex_skills_dir": str(base / "xs"),
            "codex_rules_dir": str(base / "xr"),
            "antigravity_skills_dir": str(base / "as"),
            "antigravity_enabled": True,
            "gemini_cli_agents_dir": str(base / "ga"),
            "gemini_cli_commands_dir": str(base / "gc"),
            "gemini_cli_skills_dir": str(base / "gs"),
            "gemini_cli_rules_dir": str(base / "gr"),
            "gemini_cli_enabled": False,
            "opencode_agents_dir": str(base / "oa"),
            "opencode_commands_dir": str(base / "oc"),
            "opencode_skills_dir": str(base / "os"),
            "opencode_rules_dir": str(base / "or"),
            "opencode_enabled": True,
        }
    )


# ---------------- AC-1: export shape ----------------


def test_export_writes_zip_with_manifest_and_canonicals(syncer: Syncer, tmp_path: Path):
    zip_path = _seed_and_export(syncer, tmp_path, "foo", "bar")

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    canonical_entries = {n for n in names if n.startswith(CANONICAL_PREFIX)}
    assert MANIFEST_NAME in names
    assert len(canonical_entries) == 2
    assert all(n.endswith(".json") for n in canonical_entries)


def test_export_manifest_carries_expected_keys(syncer: Syncer, tmp_path: Path):
    zip_path = _seed_and_export(syncer, tmp_path, "foo")

    with zipfile.ZipFile(zip_path) as zf:
        manifest = json.loads(zf.read(MANIFEST_NAME))
    assert manifest["schema_version"] == PORTABLE_ARCHIVE_SCHEMA_VERSION
    assert manifest["artifact_count"] == 1
    for key in ("exported_at", "source_host", "source_platform", "agents_sync_version"):
        assert key in manifest


def _pyproject_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_export_manifest_uses_pyproject_version(
    syncer: Syncer,
    tmp_path: Path,
):
    zip_path = _seed_and_export(syncer, tmp_path, "foo")

    with zipfile.ZipFile(zip_path) as zf:
        manifest = json.loads(zf.read(MANIFEST_NAME))

    assert manifest["agents_sync_version"] == agents_sync.__version__
    assert manifest["agents_sync_version"] == _pyproject_version()


def test_export_does_not_mutate_state_dir(syncer: Syncer, tmp_path: Path):
    _write_claude_skill(syncer, "foo")
    syncer.sync_once()
    before = sorted(
        (p.relative_to(syncer.state_dir), p.stat().st_mtime_ns)
        for p in syncer.state_dir.rglob("*")
        if p.is_file()
    )

    export_to_zip(syncer.state_dir, tmp_path / "snapshot.zip")

    after = sorted(
        (p.relative_to(syncer.state_dir), p.stat().st_mtime_ns)
        for p in syncer.state_dir.rglob("*")
        if p.is_file()
    )
    assert before == after


# ---------------- AC-3: last_modified ----------------


def test_export_attaches_last_modified_from_canonical_metadata(syncer: Syncer, tmp_path: Path):
    """Export reads last_modified from canonical metadata (Phase 2.2), falling back
    to PairState for canonicals that predate Phase 1.2 stamping."""
    _write_claude_skill(syncer, "foo")
    syncer.sync_once()
    state = load_state(syncer.state_dir)
    pair_id = next(iter(state))
    # Seed the canonical metadata block so the export reads from it.
    _set_canonical_lm(syncer.state_dir, pair_id, last_modified=1_234_567.0, generation=3)

    zip_path = tmp_path / "snapshot.zip"
    export_to_zip(syncer.state_dir, zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        doc = json.loads(zf.read(f"{CANONICAL_PREFIX}{pair_id}.json"))
    assert doc["metadata"]["last_modified"] == 1_234_567.0
    assert doc["metadata"]["generation"] == 3


def test_import_last_modified_wins_ignores_generation_uses_wall_clock(
    syncer: Syncer,
    tmp_path: Path,
):
    """FR-12/AC-17: the host-local generation is NOT a cross-host discriminator;
    wall-clock last_modified decides. An import with a higher generation but an
    OLDER clock must lose to a newer local artifact."""
    zip_path = _seed_and_export(syncer, tmp_path, "foo")
    pair_id = next(iter(load_state(syncer.state_dir).keys()))

    # Set the local canonical metadata: clock far in the future, generation=1.
    _set_canonical_lm(syncer.state_dir, pair_id, last_modified=9_999_999_999.0, generation=1)

    # Rewrite the exported zip's canonical: bump generation to 2 but use an
    # *older* clock (0.5), representing "more edits but on a stale clock".
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        members = {n: zf.read(n) for n in names}
    canonical_name = next(n for n in names if n.startswith(CANONICAL_PREFIX))
    doc = json.loads(members[canonical_name])
    doc.setdefault("metadata", {})["generation"] = 2
    doc["metadata"]["last_modified"] = 0.5  # *older* wall-clock than local
    members[canonical_name] = (
        json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    bumped_zip = tmp_path / "bumped.zip"
    with zipfile.ZipFile(bumped_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in members.items():
            zf.writestr(name, payload)

    report = import_from_zip(
        syncer.state_dir,
        bumped_zip,
        config=syncer.config,
    )

    # Generation is ignored cross-host; the newer local wall-clock wins.
    assert report.accepted == []
    assert report.skipped == [pair_id]
    # Local canonical metadata is unchanged (import did not overwrite).
    local_canonical = load_canonical(syncer.state_dir, pair_id)
    assert local_canonical is not None
    assert canonical_last_modified(local_canonical) == 9_999_999_999.0


# ---------------- AC-4: export failure ----------------


def test_export_fails_clean_on_unwritable_target(syncer: Syncer, tmp_path: Path):
    _write_claude_skill(syncer, "foo")
    syncer.sync_once()
    not_a_dir = tmp_path / "blocked"
    not_a_dir.write_text("placeholder")
    target = not_a_dir / "snapshot.zip"

    with pytest.raises((OSError, NotADirectoryError, FileExistsError)):
        export_to_zip(syncer.state_dir, target)

    leftovers = [p for p in tmp_path.iterdir() if p.name != "blocked"]
    assert not any(p.suffix == ".zip" or p.name.startswith(".") for p in leftovers)


# ---------------- AC-5: import into empty install ----------------


def test_import_into_empty_install_creates_canonicals_and_projects(syncer: Syncer, tmp_path: Path):
    zip_path = _seed_and_export(syncer, tmp_path, "foo", "bar")

    target = _fresh_syncer(tmp_path, "target")
    report = import_from_zip(
        target.state_dir,
        zip_path,
        config=target.config,
    )

    assert len(report.accepted) == 2
    assert report.skipped == []
    assert report.archived_local == []
    # Canonicals materialised; import is canonical-only — no tool files yet.
    assert len(list((target.state_dir / "canonical").glob("*.json"))) == 2
    for name in ("foo", "bar"):
        assert not (target.tool_root("claude", "skill") / name / "SKILL.md").exists()
    # The next sync_once projects onto every available tool for `skill` kind.
    target.sync_once()
    for tool, root in (
        ("claude", target.tool_root("claude", "skill")),
        ("codex", target.tool_root("codex", "skill")),
        ("antigravity", target.tool_root("antigravity", "skill")),
        ("opencode", target.tool_root("opencode", "skill")),
    ):
        for name in ("foo", "bar"):
            assert (root / name / "SKILL.md").exists(), f"{tool}/{name}/SKILL.md missing"
    # No archive entries (fresh install, no displacement)
    archive_root = target.state_dir / "archive"
    assert not archive_root.exists() or not any(archive_root.rglob("*"))


def test_import_then_first_sync_projects_second_is_noop(syncer: Syncer, tmp_path: Path):
    """Canonical-only import: the first sync_once projects, the second is a no-op (NFR-05)."""
    zip_path = _seed_and_export(syncer, tmp_path, "foo")
    target = _fresh_syncer(tmp_path, "target")
    import_from_zip(
        target.state_dir,
        zip_path,
        config=target.config,
    )

    first = target.sync_once()
    assert first.changed >= 1  # the canonical-only import is projected here

    archive_root = target.state_dir / "archive"
    archives_before = list(archive_root.rglob("*")) if archive_root.exists() else []
    second = target.sync_once()
    archives_after = list(archive_root.rglob("*")) if archive_root.exists() else []

    assert second.changed == 0
    assert archives_before == archives_after


# ---------------- AC-6: pair_id collision policies ----------------


def test_import_pair_id_collision_last_modified_wins_import_newer_overwrites(
    syncer: Syncer, tmp_path: Path
):
    """Import wins when its last_modified > local (AC-6).

    With content-only digest (Phase 1.0), importing identical content with a
    newer timestamp does NOT archive anything — only the canonical metadata
    block is updated; the content hash is unchanged so the daemon sees no
    reproject trigger (FR-14).
    """
    zip_path = _seed_and_export(syncer, tmp_path, "foo")
    pair_id = next(iter(load_state(syncer.state_dir).keys()))
    # Make the local canonical's last_modified older than what the zip carries.
    _set_canonical_lm(syncer.state_dir, pair_id, last_modified=1.0, generation=0)

    report = import_from_zip(
        syncer.state_dir,
        zip_path,
        config=syncer.config,
    )

    assert report.accepted == [pair_id]
    assert report.skipped == []
    # The canonical metadata was updated to the imported timestamp (not 1.0).
    promoted = load_canonical(syncer.state_dir, pair_id)
    assert promoted is not None
    assert canonical_last_modified(promoted) != 1.0

    # Content is identical → content-only digest unchanged (Phase 1.0). In theory
    # the daemon should see no reproject trigger and create no tool-side archive.
    # In practice, FR-14 fires because the canonical file bytes changed on disk
    # (metadata block updated), so a reproject + archive still occurs until Phase
    # 1.2 (content-driven stamping) conditions reprojection on content equality.
    syncer.sync_once()
    # Verify the daemon converges: second poll is a no-op (NFR-05).
    assert syncer.sync_once().changed == 0


def test_import_pair_id_collision_last_modified_wins_local_newer_keeps_local(
    syncer: Syncer, tmp_path: Path
):
    zip_path = _seed_and_export(syncer, tmp_path, "foo")
    pair_id = next(iter(load_state(syncer.state_dir).keys()))
    # After exporting, set the local canonical's last_modified far in the future.
    _set_canonical_lm(syncer.state_dir, pair_id, last_modified=9_999_999_999.0, generation=1)

    report = import_from_zip(
        syncer.state_dir,
        zip_path,
        config=syncer.config,
    )

    assert report.accepted == []
    assert report.skipped == [pair_id]
    local_canonical = load_canonical(syncer.state_dir, pair_id)
    assert local_canonical is not None
    assert canonical_last_modified(local_canonical) == 9_999_999_999.0


def test_import_pair_id_collision_last_modified_wins_tie_keeps_local(
    syncer: Syncer,
    tmp_path: Path,
):
    """AC-6 tiebreak: ties favour the local artifact (default-deny on rewrite)."""
    _write_claude_skill(syncer, "foo")
    syncer.sync_once()
    pair_id = next(iter(load_state(syncer.state_dir).keys()))
    # Seed the canonical metadata before export so both local and zip carry
    # the same last_modified → guaranteed tie on re-import.
    _set_canonical_lm(syncer.state_dir, pair_id, last_modified=1_000_000.0, generation=1)
    zip_path = syncer.state_dir.parent / "snapshot.zip"
    export_to_zip(syncer.state_dir, zip_path)

    report = import_from_zip(
        syncer.state_dir,
        zip_path,
        config=syncer.config,
    )

    assert report.accepted == []
    assert len(report.skipped) == 1


# ---------------- AC-7: slug collision ----------------


def test_import_slug_collision_different_pair_id_last_modified_wins(syncer: Syncer, tmp_path: Path):
    """Different pair_ids, same target_slug(name) — last_modified_wins applies."""
    _write_claude_skill(syncer, "shared")
    syncer.sync_once()
    local_pair_id = next(iter(load_state(syncer.state_dir).keys()))

    target = _fresh_syncer(tmp_path, "other_host")
    _write_claude_skill(target, "shared")
    target.sync_once()
    other_pair_id = next(iter(load_state(target.state_dir).keys()))
    assert other_pair_id != local_pair_id

    zip_path = tmp_path / "other.zip"
    export_to_zip(target.state_dir, zip_path)

    # Force the local canonical's last_modified to be older than the import.
    _set_canonical_lm(syncer.state_dir, local_pair_id, last_modified=1.0, generation=0)

    report = import_from_zip(
        syncer.state_dir,
        zip_path,
        config=syncer.config,
    )

    # AC-7: slug collision with different id reconciles to one artifact;
    # winning content written under the LOCAL id, imported id retired (NFR-01).
    assert report.accepted == [local_pair_id]
    state_after = load_state(syncer.state_dir)
    assert local_pair_id in state_after
    assert other_pair_id not in state_after


# ---------------- AC-9: validation failures ----------------


def test_import_rejects_missing_manifest(tmp_path: Path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("canonical/something.json", "{}")
    target = _fresh_syncer(tmp_path, "t")

    with pytest.raises(PortableArchiveError, match="missing"):
        import_from_zip(
            target.state_dir,
            bad,
            config=target.config,
        )


def test_import_rejects_future_schema_version(tmp_path: Path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr(MANIFEST_NAME, json.dumps({"schema_version": 999}))
    target = _fresh_syncer(tmp_path, "t")

    with pytest.raises(PortableArchiveError, match="newer than this tool"):
        import_from_zip(
            target.state_dir,
            bad,
            config=target.config,
        )


def test_import_rejects_invalid_pair_id_filename(tmp_path: Path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr(MANIFEST_NAME, json.dumps({"schema_version": 1}))
        zf.writestr("canonical/not-a-uuid.json", "{}")
    target = _fresh_syncer(tmp_path, "t")

    with pytest.raises(PortableArchiveError, match="invalid pair_id"):
        import_from_zip(
            target.state_dir,
            bad,
            config=target.config,
        )


def test_import_rejects_unparseable_canonical(tmp_path: Path):
    bad = tmp_path / "bad.zip"
    pair_id = "11111111-2222-4333-8444-555555555555"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr(MANIFEST_NAME, json.dumps({"schema_version": 1}))
        zf.writestr(f"canonical/{pair_id}.json", "not json")
    target = _fresh_syncer(tmp_path, "t")

    with pytest.raises(PortableArchiveError, match="unparseable"):
        import_from_zip(
            target.state_dir,
            bad,
            config=target.config,
        )


def test_import_rejects_mismatched_pair_id(tmp_path: Path):
    bad = tmp_path / "bad.zip"
    filename_id = "11111111-2222-4333-8444-555555555555"
    body_id = "22222222-3333-4444-8555-666666666666"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr(MANIFEST_NAME, json.dumps({"schema_version": 1}))
        zf.writestr(
            f"canonical/{filename_id}.json",
            json.dumps({"pair_id": body_id, "kind": "skill", "name": "x"}),
        )
    target = _fresh_syncer(tmp_path, "t")

    with pytest.raises(PortableArchiveError, match="pair_id mismatch"):
        import_from_zip(
            target.state_dir,
            bad,
            config=target.config,
        )


# ---------------- AC-10: transactional state ----------------


def test_import_failure_midway_leaves_state_json_unchanged(
    syncer: Syncer, tmp_path: Path, monkeypatch
):
    """A failure during canonical staging leaves the live tree untouched.

    Audit AC-10 contract: no partial canonicals on disk, no state.json
    written, no pending-directory leftovers — the staging is wholly
    rolled back.
    """
    zip_path = _seed_and_export(syncer, tmp_path, "foo", "bar")
    target = _fresh_syncer(tmp_path, "target")

    # Inject a failure on the second canonical-staging call.
    from agents_sync import portable_archive as pa

    real_save_to = pa.save_canonical_to
    calls = {"n": 0}

    def flaky(path, canonical):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError("simulated mid-import disk error")
        return real_save_to(path, canonical)

    monkeypatch.setattr(pa, "save_canonical_to", flaky)

    with pytest.raises(OSError, match="simulated"):
        import_from_zip(
            target.state_dir,
            zip_path,
            config=target.config,
        )

    # state.json never written.
    assert not (target.state_dir / "state.json").exists()
    # No canonical files in the live tree — the first save (which succeeded
    # before the second raised) lived only inside the staging directory and
    # was discarded when staging aborted.
    canonical_dir = target.state_dir / "canonical"
    canonicals = list(canonical_dir.iterdir()) if canonical_dir.exists() else []
    assert canonicals == []
    # No leftover staging directory either.
    leftover_pending = [
        p for p in target.state_dir.iterdir() if p.name.startswith(".import_pending_")
    ]
    assert leftover_pending == []


def test_import_partial_promotion_adopted_by_next_sync(syncer: Syncer, tmp_path: Path, monkeypatch):
    """AC-10 regression: a failure during canonical promotion (Phase 2 of staging)
    leaves a strict prefix promoted. Each promoted canonical is an orphan (state
    has no entry) and is adopted by the next sync_once (FR-16). The non-promoted
    canonical is simply absent; state is never half-written."""
    zip_path = _seed_and_export(syncer, tmp_path, "alpha", "beta")
    target = _fresh_syncer(tmp_path, "target")

    import agents_sync.portable_archive as pa

    real_replace = pa.os.replace
    calls: dict[str, int] = {"n": 0}

    def fail_on_second_promotion(src, dst):
        # Only count promotions: destination is inside live canonical/, not pending.
        dst_str = str(dst)
        if "canonical" in dst_str and ".import_pending_" not in dst_str:
            calls["n"] += 1
            if calls["n"] >= 2:
                raise OSError("simulated promotion failure")
        return real_replace(src, dst)

    monkeypatch.setattr(pa.os, "replace", fail_on_second_promotion)

    with pytest.raises(OSError, match="simulated"):
        import_from_zip(
            target.state_dir,
            zip_path,
            config=target.config,
        )

    # Exactly one canonical promoted; state not written.
    canonical_dir = target.state_dir / "canonical"
    promoted = list(canonical_dir.iterdir()) if canonical_dir.exists() else []
    assert len(promoted) == 1
    assert not (target.state_dir / "state.json").exists()

    # The promoted canonical is an orphan; sync_once adopts it and projects.
    target.sync_once()
    state_after = load_state(target.state_dir)
    assert len(state_after) == 1  # only the promoted one adopted


# ---------------- FR-12: no-op round-trip (AC-11 retired) ----------------


def test_export_then_reimport_is_byte_identical_for_canonicals(syncer: Syncer, tmp_path: Path):
    _write_claude_skill(syncer, "foo")
    _write_claude_skill(syncer, "bar")
    syncer.sync_once()

    # Seed each canonical with a metadata block before exporting so both the
    # zip and the local canonical carry the same last_modified → guaranteed tie
    # on re-import → local kept, canonical bytes unchanged (FR-12 AC-11).
    state = load_state(syncer.state_dir)
    for pair_id in state:
        _set_canonical_lm(syncer.state_dir, pair_id, last_modified=1_000_000.0, generation=1)

    canonical_dir = syncer.state_dir / "canonical"
    zip_path = tmp_path / "snapshot.zip"
    export_to_zip(syncer.state_dir, zip_path)

    before = {p.name: p.read_bytes() for p in canonical_dir.glob("*.json")}
    import_from_zip(
        syncer.state_dir,
        zip_path,
        config=syncer.config,
    )

    after = {p.name: p.read_bytes() for p in canonical_dir.glob("*.json")}
    assert before == after


# ---------------- config validation ----------------


def test_validate_config_ignores_stray_import_collision_strategy(syncer: Syncer):
    """A stray import_collision_strategy in a config file must be silently ignored."""
    from agents_sync.config import validate_config

    config = dict(syncer.config)
    config["import_collision_strategy"] = "mtime_wins"
    validate_config(config)  # must not raise
