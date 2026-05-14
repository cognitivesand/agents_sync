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
    2 — migration failed; partial backup may exist.
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
        except Exception:
            cfg_text = ""
        if _STALE_CODEX_PATH_RE.search(cfg_text):
            return True
    if not STATE_FILE.exists():
        return False
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        # Malformed state — migrate to be safe.
        return True
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
            except Exception:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="proceed without an interactive confirmation prompt",
    )
    args = parser.parse_args()

    if not detect_pre_v04_fix_state():
        print("agents-sync v0.4 migration: nothing to migrate.")
        return 0

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    backup_dir = STATE_DIR / "backups" / f"v0.4-migration-{timestamp}"

    print("agents-sync v0.4 migration is required.")
    print()
    print("This will:")
    print("  - stop the agents-sync daemon if it is running")
    print(f"  - back up state, canonical, the existing config.toml, and every")
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

    if not args.yes:
        try:
            response = input("Proceed? [y/N] ").strip().lower()
        except EOFError:
            response = ""
        if response not in {"y", "yes"}:
            print("Migration declined; daemon will not be restarted.", file=sys.stderr)
            return 1

    try:
        stop_daemon()
        backup_dir.mkdir(parents=True, exist_ok=True)

        # 1. Snapshot every tool root that we are about to mutate. The
        #    daemon state directory contains ``backups/`` itself (where this
        #    backup lives), so we deliberately do not copy STATE_DIR
        #    wholesale — ``wipe_state`` below copies ``state.json`` and
        #    ``canonical/`` individually, and ``archive/`` is preserved
        #    in place per US-05.
        for root in (*AGENT_ROOTS, *SKILL_ROOTS):
            backup_copy(root, backup_dir, f"sources/{root.relative_to(HOME)}")

        # 2. Rewrite config.toml's codex_skills_dir if it still points at
        #    ~/.agents/skills (the pre-fix default). install.sh's seed-only-
        #    if-missing rule means an existing config never gets updated by
        #    re-running the installer.
        config_updated = update_config_codex_skills_path(backup_dir)

        # 3. Move daemon-projected `-skill` duplicates out of every skill root.
        suffix_counts = {
            str(root): move_skill_suffix_duplicates(root, backup_dir)
            for root in SKILL_ROOTS
        }

        # 4. Strip injected pair_id frontmatter so reconciliation treats
        #    every remaining artifact as fresh. `~/.agents/skills/` is
        #    included so OpenCode's library is left in a clean state
        #    even though the daemon won't manage it until OpenCode is
        #    registered as a fourth agentic_tool.
        stripped = {
            "claude-agents": strip_pair_ids_in_root(HOME / ".claude/agents", ("*.md",)),
            "claude-skills": strip_pair_ids_in_root(HOME / ".claude/skills", ("*/SKILL.md",)),
            "codex-skills": strip_pair_ids_in_root(HOME / ".codex/skills", ("*/SKILL.md",)),
            "opencode-skills": strip_pair_ids_in_root(HOME / ".agents/skills", ("*/SKILL.md",)),
            "antigravity-skills": strip_pair_ids_in_root(
                HOME / ".gemini/antigravity/skills", ("*/SKILL.md",),
            ),
        }

        # 5. Wipe state + canonical; archive/ is preserved (per US-05).
        wipe_state(backup_dir)
    except Exception as exc:  # pragma: no cover — last-ditch reporting
        print(f"Migration failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"Partial backup may exist at: {backup_dir}", file=sys.stderr)
        return 2

    print()
    print("Migration complete.")
    if config_updated:
        print("  rewrote codex_skills_dir in config.toml → ~/.codex/skills")
    for root, n in suffix_counts.items():
        if n:
            print(f"  moved aside as duplicates from {root}: {n}")
    for label, n in stripped.items():
        if n:
            print(f"  stripped pair_id frontmatter ({label}): {n}")
    print(f"  backup: {backup_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
