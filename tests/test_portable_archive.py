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
            "import_collision_strategy": "mtime_wins",
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


def test_export_attaches_last_modified_from_state(syncer: Syncer, tmp_path: Path):
    _write_claude_skill(syncer, "foo")
    syncer.sync_once()
    state = load_state(syncer.state_dir)
    (pair_id, ps) = next(iter(state.items()))

    zip_path = tmp_path / "snapshot.zip"
    export_to_zip(syncer.state_dir, zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        doc = json.loads(zf.read(f"{CANONICAL_PREFIX}{pair_id}.json"))
    assert doc["last_modified"] == ps.last_modified
    assert doc["generation"] == ps.generation


def test_import_mtime_wins_ignores_generation_uses_wall_clock(syncer: Syncer, tmp_path: Path):
    """FR-12/AC-17: the host-local generation is NOT a cross-host discriminator;
    wall-clock last_modified decides. An import with a higher generation but an
    OLDER clock must lose to a newer local artifact."""
    zip_path = _seed_and_export(syncer, tmp_path, "foo")
    state = load_state(syncer.state_dir)
    pair_id = next(iter(state.keys()))
    # Local clock is far in the future but generation is at the export value (1).
    state[pair_id].last_modified = 9_999_999_999.0
    state[pair_id].generation = 1
    from agents_sync.state import save_state

    save_state(syncer.state_dir, state)

    # Rewrite the exported zip's canonical to bump generation to 2 so the
    # imported snapshot represents "two edits later, on the same host".

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        members = {n: zf.read(n) for n in names}
    canonical_name = next(n for n in names if n.startswith(CANONICAL_PREFIX))
    doc = json.loads(members[canonical_name])
    doc["generation"] = 2
    doc["last_modified"] = 0.5  # *older* wall-clock than local
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
        strategy="mtime_wins",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )

    # Generation is ignored cross-host; the newer local wall-clock wins.
    assert report.accepted == []
    assert report.skipped == [pair_id]
    state_after = load_state(syncer.state_dir)
    assert state_after[pair_id].generation == 1  # local kept; import lost


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
        strategy="mtime_wins",
        config=target.config,
        agentic_tools=target.agentic_tools,
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
        strategy="mtime_wins",
        config=target.config,
        agentic_tools=target.agentic_tools,
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


def test_import_pair_id_collision_skip_leaves_local_intact(syncer: Syncer, tmp_path: Path):
    zip_path = _seed_and_export(syncer, tmp_path, "foo")
    # Same install as source — pair_id collision on the same pair_id.
    pre_canonical = (
        syncer.state_dir / "canonical" / next(iter(load_state(syncer.state_dir).keys()))
    ).with_suffix(".json")
    pre_bytes = pre_canonical.read_bytes()

    report = import_from_zip(
        syncer.state_dir,
        zip_path,
        strategy="skip",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )

    assert len(report.skipped) == 1
    assert report.accepted == []
    assert pre_canonical.read_bytes() == pre_bytes


@pytest.mark.xfail(
    reason="Pending amendment 008 canonical metadata model: under single-writer "
    "state, import conveys last_modified via canonical metadata (not yet built). "
    "The archive assertion also needs revising for content-only digest. Tracked in "
    "docs/amendment/008 and the backlog.",
    strict=True,
)
def test_import_pair_id_collision_mtime_wins_import_newer_overwrites(
    syncer: Syncer, tmp_path: Path
):
    zip_path = _seed_and_export(syncer, tmp_path, "foo")
    # Make the local state's last_modified older than what's in the zip.
    state = load_state(syncer.state_dir)
    pair_id = next(iter(state.keys()))
    state[pair_id].last_modified = 1.0
    from agents_sync.state import save_state

    save_state(syncer.state_dir, state)

    report = import_from_zip(
        syncer.state_dir,
        zip_path,
        strategy="mtime_wins",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )

    assert report.accepted == [pair_id]
    assert report.skipped == []
    # Canonical-only import (AC-5): import overwrites the canonical but does NOT
    # write state.json. The recorded last_modified is unchanged until the next
    # sync_once re-projects the changed canonical (FR-14), archiving displaced
    # bytes (NFR-01) and updating state.
    assert load_state(syncer.state_dir)[pair_id].last_modified == 1.0
    syncer.sync_once()
    assert load_state(syncer.state_dir)[pair_id].last_modified != 1.0
    assert any((syncer.state_dir / "archive").rglob("*"))


def test_import_pair_id_collision_mtime_wins_local_newer_keeps_local(
    syncer: Syncer, tmp_path: Path
):
    zip_path = _seed_and_export(syncer, tmp_path, "foo")
    # Force the local last_modified to the future.
    state = load_state(syncer.state_dir)
    pair_id = next(iter(state.keys()))
    state[pair_id].last_modified = 9_999_999_999.0
    from agents_sync.state import save_state

    save_state(syncer.state_dir, state)

    report = import_from_zip(
        syncer.state_dir,
        zip_path,
        strategy="mtime_wins",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )

    assert report.accepted == []
    assert report.skipped == [pair_id]
    state_after = load_state(syncer.state_dir)
    assert state_after[pair_id].last_modified == 9_999_999_999.0


def test_import_pair_id_collision_mtime_wins_tie_keeps_local(syncer: Syncer, tmp_path: Path):
    """AC-6 tiebreak: ties favour the local artifact (default-deny on rewrite)."""
    zip_path = _seed_and_export(syncer, tmp_path, "foo")

    # The export carries the local last_modified verbatim, so an
    # immediate re-import is a tie.
    report = import_from_zip(
        syncer.state_dir,
        zip_path,
        strategy="mtime_wins",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )

    assert report.accepted == []
    assert len(report.skipped) == 1


def test_import_pair_id_collision_overwrite_archives_local(syncer: Syncer, tmp_path: Path):
    zip_path = _seed_and_export(syncer, tmp_path, "foo")

    report = import_from_zip(
        syncer.state_dir,
        zip_path,
        strategy="overwrite",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )

    assert len(report.accepted) == 1
    # Canonical-only: every local tool-side file is archived when the next
    # sync_once re-projects the imported canonical (NFR-01).
    syncer.sync_once()
    assert any((syncer.state_dir / "archive").rglob("*"))


def test_import_overwrite_archives_shared_map_slot_not_whole_file(syncer: Syncer, tmp_path: Path):
    claude_file = syncer.tool_root("claude", "mcp_server")
    claude_file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {
                        "type": "stdio",
                        "command": "gh-mcp",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    syncer.sync_once()
    pair_id = next(iter(load_state(syncer.state_dir)))

    zip_path = tmp_path / "mcp.zip"
    export_to_zip(syncer.state_dir, zip_path)

    cursor_file = syncer.tool_root("cursor", "mcp_server")
    cursor_config = json.loads(cursor_file.read_text(encoding="utf-8"))
    cursor_config["mcpServers"]["github"]["command"] = "local-change"
    cursor_config["mcpServers"]["local-only"] = {
        "type": "stdio",
        "command": "local-server",
    }
    cursor_file.write_text(
        json.dumps(cursor_config, indent=2) + "\n",
        encoding="utf-8",
    )
    # Absorb the local edit into the canonical first, so the overwrite-import
    # genuinely differs from local and the post-import sync_once re-projects
    # without a concurrent tool-edit conflict.
    syncer.sync_once()

    report = import_from_zip(
        syncer.state_dir,
        zip_path,
        strategy="overwrite",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )

    assert report.accepted == [pair_id]
    # Canonical-only: the next sync_once re-projects, archiving the displaced slot.
    syncer.sync_once()
    cursor_after = json.loads(cursor_file.read_text(encoding="utf-8"))
    assert cursor_after["mcpServers"]["github"]["command"] == "gh-mcp"
    assert cursor_after["mcpServers"]["local-only"]["command"] == "local-server"

    archive_dir = syncer.state_dir / "archive" / pair_id / "cursor"
    archived = [json.loads(path.read_text(encoding="utf-8")) for path in archive_dir.iterdir()]
    assert any(obj.get("command") == "local-change" for obj in archived)
    assert all("mcpServers" not in obj for obj in archived)


# ---------------- AC-7: slug collision ----------------


def test_import_slug_collision_different_pair_id_uses_strategy(syncer: Syncer, tmp_path: Path):
    """Different pair_ids, same target_slug(name) — strategy applies identically."""
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

    # Force the source install's local entry to be older so import wins.
    state = load_state(syncer.state_dir)
    state[local_pair_id].last_modified = 1.0
    from agents_sync.state import save_state

    save_state(syncer.state_dir, state)

    report = import_from_zip(
        syncer.state_dir,
        zip_path,
        strategy="mtime_wins",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )

    # AC-17 tweak: the winning content is written under the LOCAL id; the
    # imported id is retired.
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
            strategy="mtime_wins",
            config=target.config,
            agentic_tools=target.agentic_tools,
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
            strategy="mtime_wins",
            config=target.config,
            agentic_tools=target.agentic_tools,
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
            strategy="mtime_wins",
            config=target.config,
            agentic_tools=target.agentic_tools,
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
            strategy="mtime_wins",
            config=target.config,
            agentic_tools=target.agentic_tools,
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
            strategy="mtime_wins",
            config=target.config,
            agentic_tools=target.agentic_tools,
        )


def test_import_rejects_unknown_strategy(tmp_path: Path):
    target = _fresh_syncer(tmp_path, "t")
    valid_zip = tmp_path / "v.zip"
    with zipfile.ZipFile(valid_zip, "w") as zf:
        zf.writestr(MANIFEST_NAME, json.dumps({"schema_version": 1}))

    with pytest.raises(PortableArchiveError, match="Unknown collision strategy"):
        import_from_zip(
            target.state_dir,
            valid_zip,
            strategy="nonsense",  # type: ignore[arg-type]
            config=target.config,
            agentic_tools=target.agentic_tools,
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
            strategy="mtime_wins",
            config=target.config,
            agentic_tools=target.agentic_tools,
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


# ---------------- AC-11: round-trip ----------------


def test_export_then_reimport_is_byte_identical_for_canonicals(syncer: Syncer, tmp_path: Path):
    _write_claude_skill(syncer, "foo")
    _write_claude_skill(syncer, "bar")
    syncer.sync_once()

    canonical_dir = syncer.state_dir / "canonical"
    before = {p.name: p.read_bytes() for p in canonical_dir.glob("*.json")}

    zip_path = tmp_path / "snapshot.zip"
    export_to_zip(syncer.state_dir, zip_path)
    import_from_zip(
        syncer.state_dir,
        zip_path,
        strategy="overwrite",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )

    after = {p.name: p.read_bytes() for p in canonical_dir.glob("*.json")}
    assert before == after


# ---------------- config validation ----------------


def test_validate_config_rejects_unknown_strategy(syncer: Syncer):
    from agents_sync.config import ConfigError, validate_config

    config = dict(syncer.config)
    config["import_collision_strategy"] = "wat"
    with pytest.raises(ConfigError, match="import_collision_strategy"):
        validate_config(config)


def test_validate_config_accepts_each_known_strategy(syncer: Syncer):
    from agents_sync.config import validate_config

    for strategy in ("skip", "mtime_wins", "overwrite"):
        config = dict(syncer.config)
        config["import_collision_strategy"] = strategy
        validate_config(config)  # must not raise
