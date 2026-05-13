"""Per-pair sync algorithm — Phase 3 (bidirectional with mtime conflict resolution)."""
from __future__ import annotations

import logging
import os
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents_sync import archive
from agents_sync.canonical import (
    load_canonical,
    new_pair_id,
    save_canonical,
)
from agents_sync.claude_io import (
    extract_pair_id_from_md,
    parse_claude_md,
    render_claude_md,
)
from agents_sync.codex_io import (
    extract_pair_id,
    parse_codex_agent_toml,
    parse_codex_skill_md,
    render_codex_agent_toml,
    render_codex_skill_md,
)
from agents_sync.config import expand_path
from agents_sync.config import validate_config
from agents_sync.filesystem_windows_retry import retry_fs
from agents_sync.identity import InvalidPairId, validate_pair_id
from agents_sync.state import (
    PairState,
    atomic_write_text,
    ignored_tree_names,
    load_state,
    save_state,
    sha256_file,
    sha256_tree,
    target_slug,
)


@dataclass
class SideInfo:
    path: Path
    digest: str
    mtime: float
    pair_id_present: bool


@dataclass
class PairInfo:
    kind: str
    claude: SideInfo | None = None
    codex: SideInfo | None = None


def stage_skill_dir(source: Path, target: Path, skill_md_content: str) -> None:
    """Stage a fresh copy of `source` as `target` and overwrite SKILL.md atomically."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    old = target.with_name(f".{target.name}.old")
    for stale in (tmp, old):
        if stale.exists():
            retry_fs(
                lambda stale=stale: shutil.rmtree(stale),
                operation=f"rmtree {stale}",
            )
    shutil.copytree(source, tmp, ignore=lambda _dir, names: ignored_tree_names(names))
    atomic_write_text(tmp / "SKILL.md", skill_md_content)
    if target.exists():
        retry_fs(
            lambda: target.rename(old),
            operation=f"rename {target} -> {old}",
        )
        try:
            retry_fs(
                lambda: tmp.rename(target),
                operation=f"rename {tmp} -> {target}",
            )
        except Exception:
            retry_fs(
                lambda: old.rename(target),
                operation=f"rollback {old} -> {target}",
            )
            raise
        retry_fs(
            lambda: shutil.rmtree(old),
            operation=f"cleanup {old}",
        )
    else:
        retry_fs(
            lambda: tmp.rename(target),
            operation=f"rename {tmp} -> {target}",
        )


class Syncer:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)
        self.claude_agents_dir = expand_path(config["claude_agents_dir"])
        self.claude_skills_dir = expand_path(config["claude_skills_dir"])
        self.codex_agents_dir = expand_path(config["codex_agents_dir"])
        self.codex_skills_dir = expand_path(config["codex_skills_dir"])
        self.state_dir = expand_path(config["state_path"]).parent
        self._blocked_pair_ids: set[str] = set()

    # ---------- discovery ----------

    def _discover(self, state: dict[str, PairState]) -> dict[str, PairInfo]:
        pairs: dict[str, PairInfo] = {}
        blocked_pair_ids: set[str] = set()

        if self.claude_agents_dir.exists():
            for path in sorted(
                p for p in self.claude_agents_dir.glob("*.md")
                if p.is_file() and not p.name.startswith(".")
            ):
                self._add_claude_agent(path, pairs, blocked_pair_ids, state)

        if self.claude_skills_dir.exists():
            for skill_md in sorted(
                p for p in self.claude_skills_dir.glob("*/SKILL.md")
                if not p.parent.name.startswith(".")
            ):
                self._add_claude_skill(skill_md.parent, pairs, blocked_pair_ids, state)

        if self.codex_agents_dir.exists():
            for path in sorted(
                p for p in self.codex_agents_dir.glob("*.toml")
                if p.is_file() and not p.name.startswith(".")
            ):
                self._add_codex_agent(path, pairs, blocked_pair_ids, state)

        if self.codex_skills_dir.exists():
            for skill_md in sorted(
                p for p in self.codex_skills_dir.glob("*/SKILL.md")
                if not p.parent.name.startswith(".")
            ):
                self._add_codex_skill(skill_md.parent, pairs, blocked_pair_ids, state)

        self._blocked_pair_ids = blocked_pair_ids
        return pairs

    def _add_claude_agent(
        self,
        path: Path,
        pairs: dict[str, PairInfo],
        blocked_pair_ids: set[str],
        state: dict[str, PairState],
    ) -> None:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            logging.exception("Cannot read Claude agent: %s", path)
            self._block_state_owner(path, state, blocked_pair_ids)
            return
        pair_id = extract_pair_id_from_md(text)
        present = pair_id is not None
        if pair_id is None:
            pair_id = new_pair_id()
        else:
            try:
                validate_pair_id(pair_id)
            except InvalidPairId:
                logging.error("Invalid pair_id in Claude agent: path=%s", path)
                self._block_state_owner(path, state, blocked_pair_ids)
                return
        info = SideInfo(path, sha256_file(path), path.stat().st_mtime, present)
        self._insert_side(pair_id, "agent", "claude", info, pairs, blocked_pair_ids)

    def _add_claude_skill(
        self,
        path: Path,
        pairs: dict[str, PairInfo],
        blocked_pair_ids: set[str],
        state: dict[str, PairState],
    ) -> None:
        skill_md = path / "SKILL.md"
        try:
            text = skill_md.read_text(encoding="utf-8")
        except Exception:
            logging.exception("Cannot read Claude skill: %s", skill_md)
            self._block_state_owner(path, state, blocked_pair_ids)
            return
        pair_id = extract_pair_id_from_md(text)
        present = pair_id is not None
        if pair_id is None:
            pair_id = new_pair_id()
        else:
            try:
                validate_pair_id(pair_id)
            except InvalidPairId:
                logging.error("Invalid pair_id in Claude skill: path=%s", skill_md)
                self._block_state_owner(path, state, blocked_pair_ids)
                return
        info = SideInfo(path, sha256_tree(path), path.stat().st_mtime, present)
        self._insert_side(pair_id, "skill", "claude", info, pairs, blocked_pair_ids)

    def _add_codex_agent(
        self,
        path: Path,
        pairs: dict[str, PairInfo],
        blocked_pair_ids: set[str],
        state: dict[str, PairState],
    ) -> None:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            logging.exception("Cannot read Codex agent: %s", path)
            self._block_state_owner(path, state, blocked_pair_ids)
            return
        pair_id = extract_pair_id(text)
        present = pair_id is not None
        if pair_id is None:
            pair_id = new_pair_id()
        else:
            try:
                validate_pair_id(pair_id)
            except InvalidPairId:
                logging.error("Invalid pair_id in Codex agent: path=%s", path)
                self._block_state_owner(path, state, blocked_pair_ids)
                return
        info = SideInfo(path, sha256_file(path), path.stat().st_mtime, present)
        self._insert_side(pair_id, "agent", "codex", info, pairs, blocked_pair_ids)

    def _add_codex_skill(
        self,
        path: Path,
        pairs: dict[str, PairInfo],
        blocked_pair_ids: set[str],
        state: dict[str, PairState],
    ) -> None:
        skill_md = path / "SKILL.md"
        try:
            text = skill_md.read_text(encoding="utf-8")
        except Exception:
            logging.exception("Cannot read Codex skill: %s", skill_md)
            self._block_state_owner(path, state, blocked_pair_ids)
            return
        pair_id = extract_pair_id_from_md(text)
        present = pair_id is not None
        if pair_id is None:
            pair_id = new_pair_id()
        else:
            try:
                validate_pair_id(pair_id)
            except InvalidPairId:
                logging.error("Invalid pair_id in Codex skill: path=%s", skill_md)
                self._block_state_owner(path, state, blocked_pair_ids)
                return
        info = SideInfo(path, sha256_tree(path), path.stat().st_mtime, present)
        self._insert_side(pair_id, "skill", "codex", info, pairs, blocked_pair_ids)

    def _insert_side(
        self,
        pair_id: str,
        kind: str,
        side: str,
        info: SideInfo,
        pairs: dict[str, PairInfo],
        blocked_pair_ids: set[str],
    ) -> None:
        if pair_id in blocked_pair_ids:
            return
        pair = pairs.get(pair_id)
        if pair is None:
            pair = PairInfo(kind=kind)
            pairs[pair_id] = pair
        elif pair.kind != kind:
            logging.error("pair_id reused across kinds: pair_id=%s", pair_id)
            pairs.pop(pair_id, None)
            blocked_pair_ids.add(pair_id)
            return

        if getattr(pair, side) is not None:
            logging.error("duplicate pair_id on %s side: pair_id=%s", side, pair_id)
            pairs.pop(pair_id, None)
            blocked_pair_ids.add(pair_id)
            return

        setattr(pair, side, info)

    def _block_state_owner(
        self,
        path: Path,
        state: dict[str, PairState],
        blocked_pair_ids: set[str],
    ) -> None:
        owner = self._state_owner_for_path(path, state)
        if owner is not None:
            blocked_pair_ids.add(owner)

    # ---------- top-level loop ----------

    def sync_once(self) -> int:
        validate_config(self.config)
        state = load_state(self.state_dir)
        discovery = self._discover(state)
        self._block_target_collisions(discovery, state)
        changed = 0

        for pair_id, info in discovery.items():
            try:
                if self._process_pair(pair_id, info, state):
                    changed += 1
            except Exception:
                logging.exception("Failed to sync pair: pair_id=%s", pair_id)

        # Detect deleted pairs (in state but not in discovery).
        for pair_id in list(state.keys()):
            if pair_id in discovery:
                continue
            if pair_id in self._blocked_pair_ids:
                continue
            try:
                if self._propagate_orphan_state(pair_id, state):
                    changed += 1
            except Exception:
                logging.exception("Failed to handle orphan state: pair_id=%s", pair_id)

        save_state(self.state_dir, state)
        return changed

    def _process_pair(self, pair_id: str, info: PairInfo, state: dict[str, PairState]) -> bool:
        ps = state.get(pair_id)

        if ps is None:
            return self._adopt_new_pair(pair_id, info, state)

        # Either side may be missing in this poll (file removed).
        if info.claude is None and info.codex is None:
            return False
        if info.claude is None:
            return self._propagate_claude_removal(pair_id, info, state)
        if info.codex is None:
            return self._propagate_codex_removal(pair_id, info, state)

        claude_changed = info.claude.digest != ps.claude_last_written
        codex_changed = info.codex.digest != ps.codex_last_written

        if not claude_changed and not codex_changed:
            return False
        if claude_changed and not codex_changed:
            return self._sync_claude_to_codex(pair_id, info, state)
        if codex_changed and not claude_changed:
            return self._sync_codex_to_claude(pair_id, info, state)
        return self._resolve_conflict(pair_id, info, state)

    def _block_target_collisions(
        self,
        discovery: dict[str, PairInfo],
        state: dict[str, PairState],
    ) -> None:
        targets: dict[str, list[str]] = {}
        target_display: dict[str, Path] = {}
        blocked: set[str] = set()

        for pair_id, info in discovery.items():
            if pair_id in state:
                continue
            try:
                target = self._planned_adoption_target(info)
            except Exception:
                logging.exception("Cannot plan adoption target: pair_id=%s", pair_id)
                blocked.add(pair_id)
                continue
            if target is None:
                continue
            target_key = self._path_collision_key(target)
            targets.setdefault(target_key, []).append(pair_id)
            target_display.setdefault(target_key, target)

            owner = self._state_owner_for_path(target, state)
            if owner is not None and owner != pair_id:
                logging.error(
                    "Target path collision with managed pair: pair_id=%s owner_pair_id=%s target=%s",
                    pair_id,
                    owner,
                    target,
                )
                blocked.add(pair_id)
            elif owner is None and target.exists():
                logging.error(
                    "Target path collision with unmanaged path: pair_id=%s target=%s",
                    pair_id,
                    target,
                )
                blocked.add(pair_id)

        for target_key, pair_ids in targets.items():
            if len(pair_ids) <= 1:
                continue
            logging.error(
                "Target path collision: target=%s pair_ids=%s",
                target_display[target_key],
                pair_ids,
            )
            blocked.update(pair_ids)

        for pair_id in blocked:
            discovery.pop(pair_id, None)
            self._blocked_pair_ids.add(pair_id)

    def _planned_adoption_target(self, info: PairInfo) -> Path | None:
        if info.claude is not None and info.codex is not None:
            return None
        if info.claude is not None:
            canonical = parse_claude_md(
                self._read_text(info.kind, info.claude.path),
                prior_canonical=None,
                kind=info.kind,
            )
            slug = target_slug(canonical["name"], info.kind)
            if info.kind == "agent":
                return self.codex_agents_dir / f"{slug}.toml"
            return self.codex_skills_dir / slug

        if info.codex is None:
            return None
        text = self._read_text(info.kind, info.codex.path)
        if info.kind == "agent":
            canonical = parse_codex_agent_toml(text, prior_canonical=None)
        else:
            canonical = parse_codex_skill_md(text, prior_canonical=None)
        slug = target_slug(canonical["name"], info.kind)
        if info.kind == "agent":
            return self.claude_agents_dir / f"{slug}.md"
        return self.claude_skills_dir / slug

    def _state_owner_for_path(
        self,
        path: Path,
        state: dict[str, PairState],
    ) -> str | None:
        target_key = self._path_collision_key(path)
        for pair_id, pair_state in state.items():
            for stored in (pair_state.claude_path, pair_state.codex_path):
                if stored is None:
                    continue
                if self._path_collision_key(Path(stored)) == target_key:
                    return pair_id
        return None

    def _path_collision_key(self, path: Path) -> str:
        resolved = path.resolve()
        normalized = unicodedata.normalize("NFC", os.path.normcase(str(resolved)))
        if sys.platform == "darwin":
            return normalized.casefold()
        return normalized

    # ---------- adoption ----------

    def _adopt_new_pair(self, pair_id: str, info: PairInfo, state: dict[str, PairState]) -> bool:
        if info.claude is not None and info.codex is None:
            return self._adopt_from_claude(pair_id, info, state)
        if info.codex is not None and info.claude is None:
            return self._adopt_from_codex(pair_id, info, state)
        # Both present without prior state: pick the more-recently-modified side.
        if info.claude.mtime >= info.codex.mtime:
            return self._adopt_from_claude(pair_id, info, state)
        return self._adopt_from_codex(pair_id, info, state)

    def _adopt_from_claude(self, pair_id: str, info: PairInfo, state: dict[str, PairState]) -> bool:
        side = info.claude
        text = self._read_text(info.kind, side.path)
        canonical = parse_claude_md(text, prior_canonical=None, kind=info.kind)
        canonical["pair_id"] = pair_id

        if not side.pair_id_present:
            archive.archive_copy(self.state_dir, pair_id, "claude", side.path)
            self._write_claude(info.kind, side.path, canonical, prior_text=text)

        save_canonical(self.state_dir, pair_id, canonical)
        codex_path = self._render_codex(info.kind, canonical, info.codex.path if info.codex else None,
                                         claude_dir=side.path if info.kind == "skill" else None)

        self._update_state(state, pair_id, info.kind, side.path, codex_path)
        logging.info("Adopted from Claude: %s -> %s (pair_id=%s)", side.path, codex_path, pair_id)
        return True

    def _adopt_from_codex(self, pair_id: str, info: PairInfo, state: dict[str, PairState]) -> bool:
        side = info.codex
        text = self._read_text(info.kind, side.path)
        if info.kind == "agent":
            canonical = parse_codex_agent_toml(text, prior_canonical=None)
        else:
            canonical = parse_codex_skill_md(text, prior_canonical=None)
        canonical["pair_id"] = pair_id

        if not side.pair_id_present:
            archive.archive_copy(self.state_dir, pair_id, "codex", side.path)
            if info.kind == "agent":
                atomic_write_text(side.path, render_codex_agent_toml(canonical))
            else:
                atomic_write_text(side.path / "SKILL.md", render_codex_skill_md(canonical))

        save_canonical(self.state_dir, pair_id, canonical)
        claude_path = self._render_claude(info.kind, canonical,
                                           info.claude.path if info.claude else None,
                                           prior_text=None,
                                           codex_dir=side.path if info.kind == "skill" else None)

        self._update_state(state, pair_id, info.kind, claude_path, side.path)
        logging.info("Adopted from Codex: %s -> %s (pair_id=%s)", side.path, claude_path, pair_id)
        return True

    # ---------- one-direction sync ----------

    def _sync_claude_to_codex(self, pair_id: str, info: PairInfo, state: dict[str, PairState]) -> bool:
        prior_canonical = load_canonical(self.state_dir, pair_id)
        text = self._read_text(info.kind, info.claude.path)
        canonical = parse_claude_md(text, prior_canonical=prior_canonical, kind=info.kind)
        canonical["pair_id"] = pair_id
        save_canonical(self.state_dir, pair_id, canonical)

        codex_path = self._render_codex(info.kind, canonical, info.codex.path,
                                         claude_dir=info.claude.path if info.kind == "skill" else None)
        self._update_state(state, pair_id, info.kind, info.claude.path, codex_path)
        logging.info("Synced Claude->Codex: %s (pair_id=%s)", info.claude.path, pair_id)
        return True

    def _sync_codex_to_claude(self, pair_id: str, info: PairInfo, state: dict[str, PairState]) -> bool:
        prior_canonical = load_canonical(self.state_dir, pair_id)
        text = self._read_text(info.kind, info.codex.path)
        if info.kind == "agent":
            canonical = parse_codex_agent_toml(text, prior_canonical=prior_canonical)
        else:
            canonical = parse_codex_skill_md(text, prior_canonical=prior_canonical)
        canonical["pair_id"] = pair_id
        save_canonical(self.state_dir, pair_id, canonical)

        prior_claude_text = self._read_text(info.kind, info.claude.path)
        claude_path = self._render_claude(info.kind, canonical, info.claude.path,
                                           prior_text=prior_claude_text,
                                           codex_dir=info.codex.path if info.kind == "skill" else None)
        self._update_state(state, pair_id, info.kind, claude_path, info.codex.path)
        logging.info("Synced Codex->Claude: %s (pair_id=%s)", info.codex.path, pair_id)
        return True

    def _resolve_conflict(self, pair_id: str, info: PairInfo, state: dict[str, PairState]) -> bool:
        if info.claude.mtime >= info.codex.mtime:
            archive.archive_copy(self.state_dir, pair_id, "codex", info.codex.path)
            logging.warning(
                "Conflict resolved (Claude wins): pair_id=%s claude_mtime=%s codex_mtime=%s",
                pair_id, info.claude.mtime, info.codex.mtime,
            )
            return self._sync_claude_to_codex(pair_id, info, state)
        archive.archive_copy(self.state_dir, pair_id, "claude", info.claude.path)
        logging.warning(
            "Conflict resolved (Codex wins): pair_id=%s claude_mtime=%s codex_mtime=%s",
            pair_id, info.claude.mtime, info.codex.mtime,
        )
        return self._sync_codex_to_claude(pair_id, info, state)

    # ---------- removal propagation ----------

    def _propagate_claude_removal(self, pair_id: str, info: PairInfo, state: dict[str, PairState]) -> bool:
        if info.codex is not None and info.codex.path.exists():
            archive.archive_move(self.state_dir, pair_id, "codex", info.codex.path)
        del state[pair_id]
        logging.info("Propagated Claude removal: pair_id=%s", pair_id)
        return True

    def _propagate_codex_removal(self, pair_id: str, info: PairInfo, state: dict[str, PairState]) -> bool:
        if info.claude is not None and info.claude.path.exists():
            archive.archive_move(self.state_dir, pair_id, "claude", info.claude.path)
        del state[pair_id]
        logging.info("Propagated Codex removal: pair_id=%s", pair_id)
        return True

    def _propagate_orphan_state(self, pair_id: str, state: dict[str, PairState]) -> bool:
        """Pair_id is in state but neither side was discovered this poll.

        Both sides removed: drop from state, no archive needed (nothing to
        archive; user already removed both).
        """
        del state[pair_id]
        logging.info("Pair fully removed: pair_id=%s", pair_id)
        return True

    # ---------- read / render helpers ----------

    def _read_text(self, kind: str, path: Path) -> str:
        if kind == "agent":
            return path.read_text(encoding="utf-8")
        return (path / "SKILL.md").read_text(encoding="utf-8")

    def _write_claude(self, kind: str, path: Path, canonical: dict[str, Any],
                      prior_text: str | None) -> None:
        new_text = render_claude_md(canonical, prior_text=prior_text)
        if kind == "agent":
            atomic_write_text(path, new_text)
        else:
            atomic_write_text(path / "SKILL.md", new_text)

    def _render_claude(self, kind: str, canonical: dict[str, Any],
                       existing_path: Path | None, *, prior_text: str | None,
                       codex_dir: Path | None) -> Path:
        slug = target_slug(canonical["name"], kind)
        if kind == "agent":
            target = existing_path or (self.claude_agents_dir / f"{slug}.md")
            self._assert_target_available(target, existing_path)
            atomic_write_text(target, render_claude_md(canonical, prior_text=prior_text))
            return target
        target_dir = existing_path or (self.claude_skills_dir / slug)
        self._assert_target_available(target_dir, existing_path)
        skill_md_text = render_claude_md(canonical, prior_text=prior_text)
        if codex_dir is not None and target_dir != codex_dir:
            stage_skill_dir(codex_dir, target_dir, skill_md_text)
        else:
            target_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target_dir / "SKILL.md", skill_md_text)
        return target_dir

    def _render_codex(self, kind: str, canonical: dict[str, Any],
                      existing_path: Path | None, *, claude_dir: Path | None) -> Path:
        slug = target_slug(canonical["name"], kind)
        if kind == "agent":
            target = existing_path or (self.codex_agents_dir / f"{slug}.toml")
            self._assert_target_available(target, existing_path)
            atomic_write_text(target, render_codex_agent_toml(canonical))
            return target
        target_dir = existing_path or (self.codex_skills_dir / slug)
        self._assert_target_available(target_dir, existing_path)
        skill_md_text = render_codex_skill_md(canonical)
        if claude_dir is not None and target_dir != claude_dir:
            stage_skill_dir(claude_dir, target_dir, skill_md_text)
        else:
            target_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target_dir / "SKILL.md", skill_md_text)
        return target_dir

    def _update_state(self, state: dict[str, PairState], pair_id: str, kind: str,
                       claude_path: Path, codex_path: Path) -> None:
        claude_digest = sha256_file(claude_path) if kind == "agent" else sha256_tree(claude_path)
        codex_digest = sha256_file(codex_path) if kind == "agent" else sha256_tree(codex_path)
        ps = state.setdefault(pair_id, PairState(kind=kind))
        ps.kind = kind
        ps.claude_path = str(claude_path)
        ps.codex_path = str(codex_path)
        ps.claude_last_seen = claude_digest
        ps.claude_last_written = claude_digest
        ps.codex_last_seen = codex_digest
        ps.codex_last_written = codex_digest

    def _assert_target_available(self, target: Path, existing_path: Path | None) -> None:
        if existing_path is not None and (
            self._path_collision_key(target) == self._path_collision_key(existing_path)
        ):
            return
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite unowned target path: {target}")
