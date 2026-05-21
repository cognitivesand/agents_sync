"""Unit tests for the portable library snapshot (US-12 AC-1..AC-11).

Each test names the AC it covers. Filesystem tests use the existing
`syncer` fixture from `conftest.py`, which builds a real `Syncer`
against a tmp directory — no mocks, per CLAUDE.md §7.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

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
        "ca", "cc", "cs", "cr",
        "xa", "xp", "xs", "xr",
        "as",
        "oa", "oc", "os", "or",
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


def test_import_into_empty_install_creates_canonicals_and_projects(
    syncer: Syncer, tmp_path: Path
):
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
    # Canonicals materialised
    assert len(list((target.state_dir / "canonical").glob("*.json"))) == 2
    # Tool-side files projected onto every available tool for `skill` kind
    for tool, root in (
        ("claude", target.tool_root("claude", "skill")),
        ("codex", target.tool_root("codex", "skill")),
        ("antigravity", target.tool_root("antigravity", "skill")),
        ("opencode", target.tool_root("opencode", "skill")),
    ):
        for name in ("foo", "bar"):
            assert (root / name / "SKILL.md").exists(), f"{tool}/{name}/SKILL.md missing"
    # No archive entries (no displacement)
    archive_root = target.state_dir / "archive"
    assert not archive_root.exists() or not any(archive_root.rglob("*"))


def test_import_followed_by_sync_once_is_a_noop(syncer: Syncer, tmp_path: Path):
    """NFR-05: after a synchronous import, the next sync_once writes nothing."""
    zip_path = _seed_and_export(syncer, tmp_path, "foo")
    target = _fresh_syncer(tmp_path, "target")
    import_from_zip(
        target.state_dir,
        zip_path,
        strategy="mtime_wins",
        config=target.config,
        agentic_tools=target.agentic_tools,
    )

    archive_root = target.state_dir / "archive"
    archives_before = (
        list(archive_root.rglob("*")) if archive_root.exists() else []
    )
    changed = target.sync_once()
    archives_after = (
        list(archive_root.rglob("*")) if archive_root.exists() else []
    )

    assert changed == 0
    assert archives_before == archives_after


# ---------------- AC-6: pair_id collision policies ----------------


def test_import_pair_id_collision_skip_leaves_local_intact(
    syncer: Syncer, tmp_path: Path
):
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
    assert report.archived_local  # NFR-01 displacement archive
    state_after = load_state(syncer.state_dir)
    assert state_after[pair_id].last_modified != 1.0


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


def test_import_pair_id_collision_mtime_wins_tie_keeps_local(
    syncer: Syncer, tmp_path: Path
):
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


def test_import_pair_id_collision_overwrite_archives_local(
    syncer: Syncer, tmp_path: Path
):
    zip_path = _seed_and_export(syncer, tmp_path, "foo")

    report = import_from_zip(
        syncer.state_dir,
        zip_path,
        strategy="overwrite",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )

    assert len(report.accepted) == 1
    assert report.archived_local  # every local tool-side file got archived


def test_import_overwrite_archives_shared_map_slot_not_whole_file(
    syncer: Syncer, tmp_path: Path
):
    claude_file = syncer.tool_root("claude", "mcp_server")
    claude_file.write_text(
        json.dumps({
            "mcpServers": {
                "github": {
                    "type": "stdio",
                    "command": "gh-mcp",
                },
            },
        }),
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

    report = import_from_zip(
        syncer.state_dir,
        zip_path,
        strategy="overwrite",
        config=syncer.config,
        agentic_tools=syncer.agentic_tools,
    )

    assert report.accepted == [pair_id]
    cursor_after = json.loads(cursor_file.read_text(encoding="utf-8"))
    assert cursor_after["mcpServers"]["github"]["command"] == "gh-mcp"
    assert cursor_after["mcpServers"]["local-only"]["command"] == "local-server"

    archive_dir = syncer.state_dir / "archive" / pair_id / "cursor"
    archived = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in archive_dir.iterdir()
    ]
    assert any(obj.get("command") == "local-change" for obj in archived)
    assert all("mcpServers" not in obj for obj in archived)


# ---------------- AC-7: slug collision ----------------


def test_import_slug_collision_different_pair_id_uses_strategy(
    syncer: Syncer, tmp_path: Path
):
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

    assert report.accepted == [other_pair_id]
    state_after = load_state(syncer.state_dir)
    assert other_pair_id in state_after
    assert local_pair_id not in state_after  # replaced by the imported identity


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
    zip_path = _seed_and_export(syncer, tmp_path, "foo", "bar")
    target = _fresh_syncer(tmp_path, "target")

    # Inject a failure on the second save_canonical call.
    from agents_sync import portable_archive as pa

    real_save = pa.save_canonical
    calls = {"n": 0}

    def flaky(state_dir, pair_id, canonical):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError("simulated mid-import disk error")
        return real_save(state_dir, pair_id, canonical)

    monkeypatch.setattr(pa, "save_canonical", flaky)

    with pytest.raises(OSError, match="simulated"):
        import_from_zip(
            target.state_dir,
            zip_path,
            strategy="mtime_wins",
            config=target.config,
            agentic_tools=target.agentic_tools,
        )

    assert not (target.state_dir / "state.json").exists()


# ---------------- AC-11: round-trip ----------------


def test_export_then_reimport_is_byte_identical_for_canonicals(
    syncer: Syncer, tmp_path: Path
):
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
