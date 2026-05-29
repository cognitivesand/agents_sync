#!/usr/bin/env python3
"""v0.4 layout migration.

The v0.4 commits that match Codex's real on-disk layout (commit 0e22c49)
moved ``codex_skills_dir`` from ``~/.agents/skills`` to ``~/.codex/skills``
and dropped the ``-skill`` / ``-agent`` suffix that v0.3 added to
daemon-projected counterparts.

An install that ran any pre-fix version (anything before 0e22c49) will
have:

  - A ``state.json`` with managed-artifact paths under ``~/.agents/skills``
    or with ``-skill`` suffixes on the basenames.
  - Daemon-projected ``<name>-skill/`` directories sitting next to user
    originals at ``<name>/`` on the claude and/or codex side, with the
    pair drifted into two separate managed pair_ids per logical skill.
  - ``pair_id:`` lines injected into the user's SKILL.md frontmatter.

Note on ``~/.agents/skills/``: this directory is **OpenCode's**
user-level "agent-compatible" skills root, not a stale Codex location.
OpenCode is a multi-source loader (see https://opencode.ai/docs/skills/)
and the daemon should not move its content elsewhere. Migration leaves
the bare-named directories in ``~/.agents/skills/`` in place; it only
moves daemon-projected ``-skill`` duplicates aside and strips any
injected ``pair_id`` frontmatter so a future OpenCode-as-fourth-tool
integration starts from clean inputs.

This script detects the pre-fix layout and re-baselines so the next
``sync_once`` starts from clean inputs and goes through first-boot §5.5
reconciliation. Nothing is deleted outright; every file moved aside
lands under ``~/.local/state/agents-sync/backups/v0.4-migration-<ts>/``
so a manual revert is always possible.

Exit codes:
    0 — no migration needed, or migration completed.
    1 — migration declined.
    2 — migration failed, detection was inconclusive, or another migration is running.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

HOME = Path.home()
STATE_DIR = HOME / ".local/state/agents-sync"
STATE_FILE = STATE_DIR / "state.json"
CANONICAL_DIR = STATE_DIR / "canonical"
CONFIG_FILE = HOME / ".config/agents-sync/config.toml"

# Roots that may hold either user-authored or daemon-projected content.
# ``~/.agents/skills/`` is OpenCode's directory; the migration touches it only
# to remove daemon-projected ``-skill`` duplicates and strip injected pair_ids.
SKILL_ROOTS = (
    HOME / ".claude/skills",
    HOME / ".codex/skills",
    HOME / ".agents/skills",
    HOME / ".gemini/antigravity/skills",
)
AGENT_ROOTS = (HOME / ".claude/agents",)


_STALE_CODEX_PATH_RE = re.compile(
    r'^\s*codex_skills_dir\s*=\s*"~?/?(?:\$HOME/)?\.agents/skills"?',
    re.MULTILINE,
)


def detect_pre_v04_fix_state() -> bool:
    """True if state.json or config.toml still carry the pre-fix codex path
    or a `-skill` suffix on a managed-artifact basename.
    """
    if CONFIG_FILE.exists():
        try:
            cfg_text = CONFIG_FILE.read_text(encoding="utf-8")
        except OSError as exc:
            raise MigrationDetectionError(
                f"could not read {CONFIG_FILE} during migration detection "
                f"({type(exc).__name__}: {exc})"
            ) from exc
        except UnicodeDecodeError as exc:
            raise MigrationDetectionError(
                f"could not decode {CONFIG_FILE} during migration detection "
                f"({type(exc).__name__}: {exc})"
            ) from exc
        if _STALE_CODEX_PATH_RE.search(cfg_text):
            return True
    if not STATE_FILE.exists():
        return False
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MigrationDetectionError(
            f"could not read {STATE_FILE} during migration detection "
            f"({type(exc).__name__}: {exc})"
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationDetectionError(
            f"could not decode {STATE_FILE} during migration detection "
            f"({type(exc).__name__}: {exc})"
        ) from exc
    artifacts = data.get("customization_artifacts")
    if not isinstance(artifacts, dict):
        return False
    for entry in artifacts.values():
        tools = entry.get("agentic_tools", {}) if isinstance(entry, dict) else {}
        for tool in tools.values():
            path = tool.get("path", "") if isinstance(tool, dict) else ""
            normalized = path.rstrip("/")
            basename = os.path.basename(normalized)
            if ".agents/skills" in path or basename.endswith("-skill"):
                return True
    return False


def update_config_codex_skills_path(backup_dir: Path) -> bool:
    """Rewrite ``codex_skills_dir = "~/.agents/skills"`` to ``"~/.codex/skills"``.

    Returns True iff the config file was modified. The original file is
    copied into the backup before rewriting.
    """
    if not CONFIG_FILE.exists():
        return False
    text = CONFIG_FILE.read_text(encoding="utf-8")
    new = _STALE_CODEX_PATH_RE.sub('codex_skills_dir = "~/.codex/skills"', text)
    if new == text:
        return False
    backup_copy(CONFIG_FILE, backup_dir, "config.toml")
    CONFIG_FILE.write_text(new, encoding="utf-8")
    return True


def stop_daemon() -> None:
    """Stop the systemd / launchd unit if either is registered. Idempotent."""
    if shutil.which("systemctl"):
        subprocess.run(
            ["systemctl", "--user", "stop", "agents-sync.service"],
            check=False,
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
    if shutil.which("launchctl"):
        # Bootout is the macOS analogue. `uid` discovery via `id -u`.
        try:
            uid = os.getuid()
        except AttributeError:
            uid = None
        if uid is not None:
            plist = HOME / "Library/LaunchAgents/com.agents-sync.daemon.plist"
            if plist.exists():
                subprocess.run(
                    ["launchctl", "bootout", f"gui/{uid}", str(plist)],
                    check=False,
                    stderr=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                )


def backup_copy(source: Path, backup_dir: Path, label: str) -> None:
    """Recursively copy ``source`` into ``backup_dir / label`` if it exists."""
    if not source.exists():
        return
    dest = backup_dir / label
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, dest, symlinks=True, dirs_exist_ok=False)
    else:
        shutil.copy2(source, dest)


def move_skill_suffix_duplicates(root: Path, backup_dir: Path) -> int:
    """Move every ``<name>-skill/`` subdirectory of ``root`` into the backup.

    These are daemon-projected counterparts from the v0.3-suffix era; the
    fresh v0.4 sync will recreate them with bare names. A user who
    intentionally named a skill ``foo-skill`` will see their content in
    the backup and can restore it manually.
    """
    if not root.exists() or not root.is_dir():
        return 0
    moved = 0
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if not entry.name.endswith("-skill"):
            continue
        target = backup_dir / "skill-suffix-duplicates" / root.name / entry.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(entry), str(target))
        moved += 1
    return moved


_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.DOTALL)


def strip_pair_id_in_text(text: str) -> tuple[str, bool]:
    """Remove a single ``pair_id:`` line from the artifact's frontmatter."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return text, False
    fm = match.group(1)
    new_fm, n = re.subn(r"^pair_id:[^\n]*\n?", "", fm, count=1, flags=re.MULTILINE)
    if n == 0:
        return text, False
    new_block = "---\n" + new_fm.rstrip("\n") + "\n---\n"
    return new_block + text[match.end():], True


def strip_pair_ids_in_root(root: Path, patterns: tuple[str, ...]) -> int:
    """Walk ``root`` and strip pair_id frontmatter from every matching file."""
    if not root.exists():
        return 0
    count = 0
    for pattern in patterns:
        for md in root.glob(pattern):
            if not md.is_file():
                continue
            try:
                text = md.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                print(
                    f"warning: skipping unreadable file {md} "
                    f"({type(exc).__name__}: {exc})",
                    file=sys.stderr,
                )
                continue
            new, changed = strip_pair_id_in_text(text)
            if changed:
                md.write_text(new, encoding="utf-8")
                count += 1
    return count


def wipe_state(backup_dir: Path) -> None:
    """Drop state.json and canonical/ once they're safely in the backup."""
    backup_copy(STATE_FILE, backup_dir, "state.json")
    backup_copy(CANONICAL_DIR, backup_dir, "canonical")
    STATE_FILE.unlink(missing_ok=True)
    if CANONICAL_DIR.exists():
        shutil.rmtree(CANONICAL_DIR)


@dataclass
class MigrationResults:
    config_updated: bool
    suffix_counts: dict[str, int]
    stripped: dict[str, int]


class MigrationDetectionError(Exception):
    """Raised when detection cannot safely decide whether migration is needed."""


class MigrationLockError(Exception):
    """Raised when another migration process already holds the lock."""


class MigrationFileLock:
    """Exclusive filesystem lock for the full detect-and-migrate decision."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: int | None = None

    def __enter__(self) -> MigrationFileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise MigrationLockError(
                f"migration lock already exists at {self.path}"
            ) from exc
        try:
            os.write(self.fd, f"pid={os.getpid()}\n".encode("ascii"))
        except Exception:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            self.path.unlink(missing_ok=True)
            raise
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.path.unlink(missing_ok=True)


class MigrationError(Exception):
    """A migration phase failed; carries the phase name and chains the cause."""

    def __init__(self, phase: str) -> None:
        super().__init__(f"phase {phase!r} failed")
        self.phase = phase


class MigrationRollbackError(MigrationError):
    """Rollback failed after an earlier migration phase failed."""

    def __init__(self, phase: str, original: MigrationError) -> None:
        super().__init__(phase)
        self.original = original


def _run_phase[T](phase_name: str, fn: Callable[[], T]) -> T:
    """Execute `fn`, wrapping any failure in a MigrationError that names the phase."""
    try:
        return fn()
    except Exception as exc:
        raise MigrationError(phase_name) from exc


def _print_plan_banner(backup_dir: Path) -> None:
    print("agents-sync v0.4 migration is required.")
    print()
    print("This will:")
    print("  - stop the agents-sync daemon if it is running")
    print("  - back up state, canonical, the existing config.toml, and every")
    print(f"    configured skill / agent root to {backup_dir}")
    print("  - rewrite codex_skills_dir in config.toml from ~/.agents/skills")
    print("    to ~/.codex/skills (Codex's real user-level skills directory)")
    print("  - move daemon-projected `<name>-skill/` directories aside in")
    print("    every skill root (claude / codex / opencode / antigravity)")
    print("  - strip injected `pair_id:` frontmatter from every SKILL.md and")
    print("    claude agent .md so first-boot §5.5 reconciliation treats them")
    print("    as fresh inputs")
    print("  - wipe state.json and canonical/ so the next sync rebuilds")
    print()
    print("~/.agents/skills/ (OpenCode's directory) is otherwise left alone.")
    print("Nothing is deleted: everything is moved into the backup.")
    print()


def _confirm_proceed() -> bool:
    try:
        response = input("Proceed? [y/N] ").strip().lower()
    except EOFError:
        response = ""
    return response in {"y", "yes"}


def _snapshot_tool_roots(backup_dir: Path) -> None:
    """Snapshot every tool root that we are about to mutate. We deliberately do
    not copy STATE_DIR wholesale (it contains ``backups/`` itself); state.json
    and canonical/ are copied by ``wipe_state``, and archive/ is preserved in
    place per US-05.
    """
    for root in (*AGENT_ROOTS, *SKILL_ROOTS):
        backup_copy(root, backup_dir, f"sources/{root.relative_to(HOME)}")


def _remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _restore_path(source: Path, target: Path) -> None:
    if not source.exists() and not source.is_symlink():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    _remove_path(target)
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)


def rollback_migration(backup_dir: Path) -> None:
    """Restore live files from the pre-mutation backup snapshot.

    ``run_migration`` calls this whenever a mutating phase fails after the
    source roots have been snapshotted. That makes the live filesystem
    all-or-nothing: a later failure cannot leave stripped frontmatter next to
    stale state.
    """
    for root in (*AGENT_ROOTS, *SKILL_ROOTS):
        snapshot = backup_dir / "sources" / root.relative_to(HOME)
        _restore_path(snapshot, root)
    _restore_path(backup_dir / "config.toml", CONFIG_FILE)
    _restore_path(backup_dir / "state.json", STATE_FILE)
    _restore_path(backup_dir / "canonical", CANONICAL_DIR)


def _move_all_skill_suffix_duplicates(backup_dir: Path) -> dict[str, int]:
    return {
        str(root): move_skill_suffix_duplicates(root, backup_dir)
        for root in SKILL_ROOTS
    }


def _strip_pair_ids_everywhere() -> dict[str, int]:
    """Strip injected pair_id frontmatter so reconciliation treats every
    remaining artifact as fresh. ``~/.agents/skills/`` is included so
    OpenCode's library is left clean even though the daemon won't manage it
    until OpenCode is registered as a fourth agentic_tool.
    """
    return {
        "claude-agents": strip_pair_ids_in_root(HOME / ".claude/agents", ("*.md",)),
        "claude-skills": strip_pair_ids_in_root(HOME / ".claude/skills", ("*/SKILL.md",)),
        "codex-skills": strip_pair_ids_in_root(HOME / ".codex/skills", ("*/SKILL.md",)),
        "opencode-skills": strip_pair_ids_in_root(HOME / ".agents/skills", ("*/SKILL.md",)),
        "antigravity-skills": strip_pair_ids_in_root(
            HOME / ".gemini/antigravity/skills", ("*/SKILL.md",),
        ),
    }


def run_migration(backup_dir: Path) -> MigrationResults:
    """Execute every migration phase under per-phase error reporting."""
    _run_phase("stop daemon", stop_daemon)
    _run_phase(
        "create backup directory",
        lambda: backup_dir.mkdir(parents=True, exist_ok=True),
    )
    _run_phase("snapshot tool roots", lambda: _snapshot_tool_roots(backup_dir))
    try:
        config_updated = _run_phase(
            "rewrite config.toml",
            lambda: update_config_codex_skills_path(backup_dir),
        )
        suffix_counts = _run_phase(
            "move -skill duplicates aside",
            lambda: _move_all_skill_suffix_duplicates(backup_dir),
        )
        stripped = _run_phase("strip pair_id frontmatter", _strip_pair_ids_everywhere)
        _run_phase("wipe state and canonical", lambda: wipe_state(backup_dir))
    except MigrationError as exc:
        try:
            rollback_migration(backup_dir)
        except Exception as rollback_exc:
            raise MigrationRollbackError("rollback migration", exc) from rollback_exc
        raise
    return MigrationResults(
        config_updated=config_updated,
        suffix_counts=suffix_counts,
        stripped=stripped,
    )


def _print_summary(backup_dir: Path, results: MigrationResults) -> None:
    print()
    print("Migration complete.")
    if results.config_updated:
        print("  rewrote codex_skills_dir in config.toml → ~/.codex/skills")
    for root, n in results.suffix_counts.items():
        if n:
            print(f"  moved aside as duplicates from {root}: {n}")
    for label, n in results.stripped.items():
        if n:
            print(f"  stripped pair_id frontmatter ({label}): {n}")
    print(f"  backup: {backup_dir}")


def _migration_lock_path() -> Path:
    return STATE_DIR / "migration.lock"


def _run_main_under_lock(args: argparse.Namespace) -> int:
    if not detect_pre_v04_fix_state():
        print("agents-sync v0.4 migration: nothing to migrate.")
        return 0

    timestamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    backup_dir = STATE_DIR / "backups" / f"v0.4-migration-{timestamp}"

    _print_plan_banner(backup_dir)

    if not args.yes and not _confirm_proceed():
        print("Migration declined; daemon will not be restarted.", file=sys.stderr)
        return 1

    try:
        results = run_migration(backup_dir)
    except MigrationRollbackError as exc:
        rollback_cause = exc.__cause__
        original = exc.original
        original_cause = original.__cause__
        print(
            f"Migration failed during phase {original.phase!r}: "
            f"{type(original_cause).__name__}: {original_cause}",
            file=sys.stderr,
        )
        print(
            f"Rollback then failed: "
            f"{type(rollback_cause).__name__}: {rollback_cause}",
            file=sys.stderr,
        )
        print(f"Backup may exist at: {backup_dir}", file=sys.stderr)
        return 2
    except MigrationError as exc:
        underlying = exc.__cause__
        print(
            f"Migration failed during phase {exc.phase!r}: "
            f"{type(underlying).__name__}: {underlying}",
            file=sys.stderr,
        )
        print(
            "Live files were rolled back from the backup where a mutation had "
            "already started.",
            file=sys.stderr,
        )
        print(f"Backup retained at: {backup_dir}", file=sys.stderr)
        return 2

    _print_summary(backup_dir, results)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="proceed without an interactive confirmation prompt",
    )
    args = parser.parse_args()

    try:
        with MigrationFileLock(_migration_lock_path()):
            return _run_main_under_lock(args)
    except MigrationLockError as exc:
        print(
            f"Migration skipped because another migration appears to be running: {exc}",
            file=sys.stderr,
        )
        return 2
    except MigrationDetectionError as exc:
        print(
            f"Migration detection failed without changing files: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
