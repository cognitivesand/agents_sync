"""Per-pair sync algorithm — Phase 2 (one-way: Claude -> canonical -> Codex)."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from agents_sync import archive
from agents_sync.canonical import (
    load_canonical,
    save_canonical,
)
from agents_sync.claude_io import (
    extract_pair_id_from_md,
    parse_claude_md,
    render_claude_md,
)
from agents_sync.codex_io import (
    render_codex_agent_toml,
    render_codex_skill_md,
)
from agents_sync.config import expand_path
from agents_sync.state import (
    PairState,
    atomic_write_text,
    load_state,
    save_state,
    sha256_file,
    sha256_tree,
    slugify,
)


def stage_skill_dir(source: Path, target: Path, skill_md_content: str) -> None:
    """Stage `source` as `target` and overwrite SKILL.md atomically.

    Two `rename(2)` calls bound the missing-target window instead of a
    full `copytree`.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    old = target.with_name(f".{target.name}.old")
    for stale in (tmp, old):
        if stale.exists():
            shutil.rmtree(stale)
    shutil.copytree(source, tmp)
    (tmp / "SKILL.md").write_text(skill_md_content, encoding="utf-8")
    if target.exists():
        target.rename(old)
        try:
            tmp.rename(target)
        except Exception:
            old.rename(target)
            raise
        shutil.rmtree(old)
    else:
        tmp.rename(target)


class Syncer:
    def __init__(self, config: dict[str, Any]) -> None:
        self.claude_agents_dir = expand_path(config["claude_agents_dir"])
        self.claude_skills_dir = expand_path(config["claude_skills_dir"])
        self.codex_agents_dir = expand_path(config["codex_agents_dir"])
        self.codex_skills_dir = expand_path(config["codex_skills_dir"])
        self.state_dir = expand_path(config["state_path"]).parent

    # ---------- discovery ----------

    def _find_claude_agents(self) -> list[Path]:
        if not self.claude_agents_dir.exists():
            return []
        return sorted(p for p in self.claude_agents_dir.glob("*.md") if p.is_file())

    def _find_claude_skills(self) -> list[Path]:
        if not self.claude_skills_dir.exists():
            return []
        return sorted(p.parent for p in self.claude_skills_dir.glob("*/SKILL.md"))

    # ---------- agent flow ----------

    def _process_agent(self, claude_path: Path, state: dict[str, PairState]) -> bool:
        text = claude_path.read_text(encoding="utf-8")
        current_digest = sha256_file(claude_path)

        pair_id = extract_pair_id_from_md(text)
        prior_canonical = load_canonical(self.state_dir, pair_id) if pair_id else None

        ps = state.get(pair_id) if pair_id else None
        if (
            ps is not None
            and ps.claude_last_written == current_digest
            and ps.codex_path
            and Path(ps.codex_path).exists()
        ):
            return False

        canonical = parse_claude_md(text, prior_canonical, kind="agent")

        # Adoption: pair_id not in frontmatter -> archive original then inject.
        if pair_id is None:
            archive.archive_file(self.state_dir, canonical["pair_id"], "claude", claude_path)
            new_text = render_claude_md(canonical, prior_text=text)
            atomic_write_text(claude_path, new_text)
            current_digest = sha256_file(claude_path)
            pair_id = canonical["pair_id"]
            logging.info("Adopted agent: %s (pair_id=%s)", claude_path, pair_id)

        save_canonical(self.state_dir, pair_id, canonical)

        slug = slugify(canonical["name"]) or pair_id[:8]
        codex_path = self.codex_agents_dir / f"{slug}.toml"
        atomic_write_text(codex_path, render_codex_agent_toml(canonical))
        codex_digest = sha256_file(codex_path)

        ps = state.setdefault(pair_id, PairState(kind="agent"))
        ps.kind = "agent"
        ps.claude_path = str(claude_path)
        ps.codex_path = str(codex_path)
        ps.claude_last_seen = current_digest
        ps.claude_last_written = current_digest
        ps.codex_last_seen = codex_digest
        ps.codex_last_written = codex_digest

        logging.info("Synced agent: %s -> %s (pair_id=%s)", claude_path, codex_path, pair_id)
        return True

    # ---------- skill flow ----------

    def _process_skill(self, claude_dir: Path, state: dict[str, PairState]) -> bool:
        skill_md = claude_dir / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        current_digest = sha256_tree(claude_dir)

        pair_id = extract_pair_id_from_md(text)
        prior_canonical = load_canonical(self.state_dir, pair_id) if pair_id else None

        ps = state.get(pair_id) if pair_id else None
        if (
            ps is not None
            and ps.claude_last_written == current_digest
            and ps.codex_path
            and Path(ps.codex_path).exists()
        ):
            return False

        canonical = parse_claude_md(text, prior_canonical, kind="skill")

        if pair_id is None:
            archive.archive_file(self.state_dir, canonical["pair_id"], "claude", claude_dir)
            atomic_write_text(skill_md, render_claude_md(canonical, prior_text=text))
            current_digest = sha256_tree(claude_dir)
            pair_id = canonical["pair_id"]
            logging.info("Adopted skill: %s (pair_id=%s)", claude_dir, pair_id)

        save_canonical(self.state_dir, pair_id, canonical)

        slug = slugify(canonical["name"]) or pair_id[:8]
        codex_dir = self.codex_skills_dir / slug
        stage_skill_dir(claude_dir, codex_dir, render_codex_skill_md(canonical))
        codex_digest = sha256_tree(codex_dir)

        ps = state.setdefault(pair_id, PairState(kind="skill"))
        ps.kind = "skill"
        ps.claude_path = str(claude_dir)
        ps.codex_path = str(codex_dir)
        ps.claude_last_seen = current_digest
        ps.claude_last_written = current_digest
        ps.codex_last_seen = codex_digest
        ps.codex_last_written = codex_digest

        logging.info("Synced skill: %s -> %s (pair_id=%s)", claude_dir, codex_dir, pair_id)
        return True

    # ---------- top-level ----------

    def sync_once(self) -> int:
        state = load_state(self.state_dir)
        changed = 0

        for claude_path in self._find_claude_agents():
            try:
                if self._process_agent(claude_path, state):
                    changed += 1
            except Exception:
                logging.exception("Failed to sync agent: %s", claude_path)

        for claude_dir in self._find_claude_skills():
            try:
                if self._process_skill(claude_dir, state):
                    changed += 1
            except Exception:
                logging.exception("Failed to sync skill: %s", claude_dir)

        save_state(self.state_dir, state)
        return changed
