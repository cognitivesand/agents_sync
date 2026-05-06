from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from agents_sync.claude_io import read_markdown
from agents_sync.codex_io import render_codex_agent, render_codex_skill
from agents_sync.config import expand_path
from agents_sync.state import (
    ExportResult,
    SourceItem,
    atomic_write_text,
    load_state,
    save_state,
    sha256_file,
    sha256_tree,
    slugify,
)


def stage_skill_dir(source: Path, target: Path, skill_md_content: str) -> None:
    """Stage a fresh copy of `source` as `target` and overwrite SKILL.md.

    Uses a `.tmp` and `.old` rename pair so the missing-target window is
    bounded by two `rename(2)` calls instead of a full `copytree`.
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
        self.state_path = expand_path(config["state_path"])
        self.prune = bool(config["prune"])

    def discover_agents(self) -> list[SourceItem]:
        if not self.claude_agents_dir.exists():
            return []
        result: list[SourceItem] = []
        for path in sorted(self.claude_agents_dir.glob("*.md")):
            if not path.is_file():
                continue
            try:
                doc = read_markdown(path)
                name = slugify(str(doc.frontmatter.get("name") or path.stem))
                result.append(SourceItem("agent", path, name, sha256_file(path)))
            except Exception:
                logging.exception("Failed to read agent: %s", path)
        return result

    def discover_skills(self) -> list[SourceItem]:
        if not self.claude_skills_dir.exists():
            return []
        result: list[SourceItem] = []
        for skill_md in sorted(self.claude_skills_dir.glob("*/SKILL.md")):
            skill_dir = skill_md.parent
            try:
                doc = read_markdown(skill_md)
                name = slugify(str(doc.frontmatter.get("name") or skill_dir.name))
                result.append(SourceItem("skill", skill_dir, name, sha256_tree(skill_dir)))
            except Exception:
                logging.exception("Failed to read skill: %s", skill_md)
        return result

    def discover_all(self) -> dict[str, SourceItem]:
        items = self.discover_agents() + self.discover_skills()
        by_target: dict[tuple[str, str], SourceItem] = {}
        result: dict[str, SourceItem] = {}
        for item in items:
            key = (item.kind, item.logical_name)
            existing = by_target.get(key)
            if existing is not None:
                logging.error(
                    "Slug collision: %s and %s both map to %s/%s; skipping the latter",
                    existing.source_path,
                    item.source_path,
                    item.kind,
                    item.logical_name,
                )
                continue
            by_target[key] = item
            result[str(item.source_path)] = item
        return result

    def export_agent(self, source: SourceItem) -> ExportResult:
        target = self.codex_agents_dir / f"{source.logical_name}.toml"
        atomic_write_text(target, render_codex_agent(source))
        logging.info("Exported agent: %s -> %s", source.source_path, target)
        return ExportResult(source, [target])

    def export_skill(self, source: SourceItem) -> ExportResult:
        target_dir = self.codex_skills_dir / source.logical_name
        stage_skill_dir(source.source_path, target_dir, render_codex_skill(source))
        logging.info("Exported skill: %s -> %s", source.source_path, target_dir)
        return ExportResult(source, [target_dir])

    def export(self, source: SourceItem) -> ExportResult:
        if source.kind == "agent":
            return self.export_agent(source)
        if source.kind == "skill":
            return self.export_skill(source)
        raise ValueError(f"Unsupported source kind: {source.kind}")

    def sync_once(self) -> int:
        state = load_state(self.state_path)
        state_sources = state.setdefault("sources", {})
        current = self.discover_all()
        changed = 0
        for source_key, source in current.items():
            previous = state_sources.get(source_key, {})
            previous_targets = [expand_path(p) for p in previous.get("targets", [])]
            targets_missing = any(not p.exists() for p in previous_targets)
            if previous.get("digest") == source.digest and not targets_missing:
                continue
            result = self.export(source)
            state_sources[source_key] = {
                "kind": source.kind,
                "logical_name": source.logical_name,
                "digest": source.digest,
                "targets": [str(path) for path in result.targets],
            }
            changed += 1
        if self.prune:
            for source_key in sorted(set(state_sources) - set(current)):
                entry = state_sources[source_key]
                for target in entry.get("targets", []):
                    target_path = expand_path(target)
                    if target_path.is_dir():
                        shutil.rmtree(target_path)
                        logging.info("Pruned stale dir: %s", target_path)
                    elif target_path.exists():
                        target_path.unlink()
                        logging.info("Pruned stale file: %s", target_path)
                del state_sources[source_key]
                changed += 1
        save_state(self.state_path, state)
        return changed
