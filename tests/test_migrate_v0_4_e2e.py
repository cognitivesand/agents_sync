"""End-to-end test for the v0.4 migration against a real v0.3 layout.

Audit slice 10 · CQ-03: the existing :mod:`tests.test_migrate_v0_4` only
exercises ``_run_phase`` plumbing. It does not prove that
``run_migration`` actually moves ``-skill`` duplicates aside, strips
injected ``pair_id`` frontmatter from user files, and wipes state.json
+ canonical/ into the backup directory. This module materializes a
realistic v0.3 layout under ``tmp_path``, points every module-level
constant the migration script reads at the temporary tree, runs the
real :func:`run_migration`, and asserts the post-migration filesystem
state.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration  # audit slice 10 · TQ-01


@pytest.fixture
def migrate_mod():
    path = Path(__file__).resolve().parent.parent / "scripts" / "migrate_v0.4.py"
    spec = importlib.util.spec_from_file_location("migrate_v0_4_e2e_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _retarget_module(module, home: Path) -> None:
    """Repoint every module-level path constant the migration script reads at
    a temporary home so :func:`run_migration` does not touch the real user
    tree. The script captures these at import time, so we mutate them in
    place after loading the module."""
    module.HOME = home
    module.STATE_DIR = home / ".local/state/agents-sync"
    module.STATE_FILE = module.STATE_DIR / "state.json"
    module.CANONICAL_DIR = module.STATE_DIR / "canonical"
    module.CONFIG_FILE = home / ".config/agents-sync/config.toml"
    module.SKILL_ROOTS = (
        home / ".claude/skills",
        home / ".codex/skills",
        home / ".agents/skills",
        home / ".gemini/antigravity/skills",
    )
    module.AGENT_ROOTS = (home / ".claude/agents",)


def _materialize_v0_3_layout(home: Path) -> None:
    """Build a believable pre-fix layout under ``home``:

    - state.json carries ``-skill`` suffixes on managed-artifact basenames
      and references the stale ``.agents/skills`` root for codex.
    - Daemon-projected ``foo-skill/`` directory sits next to the user's
      ``foo/`` directory on both claude and codex sides.
    - A user SKILL.md has an injected ``pair_id:`` frontmatter line that
      v0.4 reconciliation must strip.
    - The config.toml still spells codex_skills_dir as ``~/.agents/skills``.
    """
    (home / ".local/state/agents-sync").mkdir(parents=True, exist_ok=True)
    (home / ".config/agents-sync").mkdir(parents=True, exist_ok=True)

    config_text = (
        '# v0.3 config under test\n'
        'codex_skills_dir = "~/.agents/skills"\n'
        'state_path = "~/.local/state/agents-sync/state.json"\n'
    )
    (home / ".config/agents-sync/config.toml").write_text(
        config_text, encoding="utf-8",
    )

    pair_id = "00000000-0000-4000-8000-000000000001"
    state_payload = {
        "schema_version": 3,
        "customization_artifacts": {
            pair_id: {
                "agentic_tools": {
                    "claude": {
                        "path": str(home / ".claude/skills/foo"),
                        "last_written": "abc",
                    },
                    "codex": {
                        "path": str(home / ".agents/skills/foo-skill"),
                        "last_written": "def",
                    },
                },
            },
        },
    }
    (home / ".local/state/agents-sync/state.json").write_text(
        json.dumps(state_payload, indent=2), encoding="utf-8",
    )

    claude_user = home / ".claude/skills/foo"
    claude_user.mkdir(parents=True)
    (claude_user / "SKILL.md").write_text(
        f"---\npair_id: {pair_id}\nname: foo\n---\nUser content for foo.\n",
        encoding="utf-8",
    )

    claude_projected = home / ".claude/skills/foo-skill"
    claude_projected.mkdir(parents=True)
    (claude_projected / "SKILL.md").write_text(
        f"---\npair_id: {pair_id}\nname: foo\n---\nDaemon-projected duplicate.\n",
        encoding="utf-8",
    )

    codex_projected = home / ".agents/skills/foo-skill"
    codex_projected.mkdir(parents=True)
    (codex_projected / "SKILL.md").write_text(
        f"---\npair_id: {pair_id}\nname: foo\n---\nDaemon-projected duplicate.\n",
        encoding="utf-8",
    )


def test_run_migration_against_real_v0_3_layout(migrate_mod, tmp_path: Path):
    home = tmp_path / "home"
    _retarget_module(migrate_mod, home)
    _materialize_v0_3_layout(home)

    # Sanity: the script detects this as needing migration.
    assert migrate_mod.detect_pre_v04_fix_state() is True

    backup_dir = home / ".local/state/agents-sync/backups/v0.4-migration-test"
    migrate_mod.stop_daemon = lambda: None  # tests run without a daemon
    results = migrate_mod.run_migration(backup_dir)

    # 1. The stale codex_skills_dir line was rewritten in place.
    new_config = (home / ".config/agents-sync/config.toml").read_text(encoding="utf-8")
    assert 'codex_skills_dir = "~/.codex/skills"' in new_config
    assert ".agents/skills" not in new_config
    assert results.config_updated is True

    # 2. The daemon-projected ``foo-skill/`` directories were moved aside.
    assert not (home / ".claude/skills/foo-skill").exists()
    assert not (home / ".agents/skills/foo-skill").exists()
    moved_total = sum(results.suffix_counts.values())
    assert moved_total == 2

    # 3. The user's ``foo/`` directory survives — the migration must never
    # touch user content that wasn't a daemon-projected duplicate.
    assert (home / ".claude/skills/foo/SKILL.md").exists()

    # 4. The injected ``pair_id:`` line was stripped from the user SKILL.md.
    user_skill = (home / ".claude/skills/foo/SKILL.md").read_text(encoding="utf-8")
    assert "pair_id:" not in user_skill
    assert "User content for foo." in user_skill

    # 5. state.json and canonical/ were moved out of the live state dir.
    assert not (home / ".local/state/agents-sync/state.json").exists()
    assert (backup_dir / "state.json").exists()

    # 6. The original state.json + sources are in the backup, so a manual
    # revert is possible per the script's docstring contract.
    assert (backup_dir / "skill-suffix-duplicates").exists()


def test_run_migration_rolls_back_when_state_wipe_fails(
    migrate_mod,
    tmp_path: Path,
):
    home = tmp_path / "home"
    _retarget_module(migrate_mod, home)
    _materialize_v0_3_layout(home)

    backup_dir = home / ".local/state/agents-sync/backups/v0.4-migration-test"
    migrate_mod.stop_daemon = lambda: None

    def fail_wipe(_backup_dir: Path) -> None:
        raise OSError("simulated state wipe failure")

    migrate_mod.wipe_state = fail_wipe

    with pytest.raises(migrate_mod.MigrationError) as exc_info:
        migrate_mod.run_migration(backup_dir)

    assert exc_info.value.phase == "wipe state and canonical"

    # The strip phase ran before the wipe failed, but rollback restores the
    # original user-authored file so live bytes never remain half-migrated.
    user_skill = (home / ".claude/skills/foo/SKILL.md").read_text(encoding="utf-8")
    assert "pair_id:" in user_skill
    assert "User content for foo." in user_skill

    # Earlier live mutations are rolled back too: duplicates return, config is
    # back on its pre-fix path, and state.json was not wiped.
    assert (home / ".claude/skills/foo-skill/SKILL.md").exists()
    assert (home / ".agents/skills/foo-skill/SKILL.md").exists()
    config_text = (home / ".config/agents-sync/config.toml").read_text(
        encoding="utf-8",
    )
    assert 'codex_skills_dir = "~/.agents/skills"' in config_text
    assert (home / ".local/state/agents-sync/state.json").exists()
