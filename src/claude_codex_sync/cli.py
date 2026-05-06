from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import signal
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z",
    re.DOTALL,
)

READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "LS"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

DEFAULTS: dict[str, Any] = {
    "poll_interval_seconds": 2.0,
    "prune": False,
    "state_path": "~/.local/state/claude-codex-sync/state.json",
    "claude_agents_dir": "~/.claude/agents",
    "claude_skills_dir": "~/.claude/skills",
    "codex_agents_dir": "~/.codex/agents",
    "codex_skills_dir": "~/.agents/skills",
}


@dataclass(frozen=True)
class MarkdownDoc:
    path: Path
    frontmatter: dict[str, Any]
    body: str


@dataclass(frozen=True)
class SourceItem:
    kind: str
    source_path: Path
    logical_name: str
    digest: str


@dataclass(frozen=True)
class ExportResult:
    source: SourceItem
    targets: list[Path]


def expand_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "converted"


def read_markdown(path: Path) -> MarkdownDoc:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)

    if not match:
        return MarkdownDoc(path=path, frontmatter={}, body=text.strip())

    raw_frontmatter, body = match.groups()
    data = yaml.safe_load(raw_frontmatter) or {}

    if not isinstance(data, dict):
        raise ValueError(f"{path}: YAML frontmatter must be a mapping")

    return MarkdownDoc(path=path, frontmatter=dict(data), body=body.strip())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def stage_skill_dir(source: Path, target: Path, skill_md_content: str) -> None:
    # Build the full target tree in a sibling .tmp dir, then swap into place
    # via two renames. The window in which `target` does not exist is the
    # gap between the two renames (microseconds), not the full copytree.
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    old = target.with_name(f".{target.name}.old")
    for stale in (tmp, old):
        if stale.exists():
            shutil.rmtree(stale)
    shutil.copytree(source, tmp)
    # Overwrite SKILL.md inside the staged dir so the rendered version is
    # in place before the swap; avoids a transient stale SKILL.md.
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


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def yaml_frontmatter(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def tool_base_name(tool: str) -> str:
    return tool.split("(", 1)[0].strip()


def infer_codex_sandbox(frontmatter: dict[str, Any]) -> str | None:
    tools = {tool_base_name(t) for t in normalize_list(frontmatter.get("tools"))}
    denied = {tool_base_name(t) for t in normalize_list(frontmatter.get("disallowedTools"))}
    if tools and tools <= READ_ONLY_TOOLS:
        return "read-only"
    if denied & WRITE_TOOLS:
        return "read-only"
    return None


def render_codex_agent(source: SourceItem) -> str:
    doc = read_markdown(source.source_path)
    name = slugify(str(doc.frontmatter.get("name") or source.source_path.stem))
    description = str(doc.frontmatter.get("description") or f"Converted Claude Code agent: {name}").strip()
    instructions = doc.body or "Follow the role and task scope described above."
    preserved = {key: value for key, value in doc.frontmatter.items() if key not in {"name", "description"}}
    if preserved:
        instructions += "\n\n---\nConverted Claude-specific metadata for manual review:\n"
        instructions += json.dumps(preserved, indent=2, ensure_ascii=False, sort_keys=True)
    lines = [
        "# Generated by claude-codex-sync. Edit the Claude source, not this file.",
        f"# Source: {source.source_path}",
        f"# Source SHA256: {source.digest}",
        f"name = {toml_string(name)}",
        f"description = {toml_string(description)}",
    ]
    sandbox = infer_codex_sandbox(doc.frontmatter)
    if sandbox:
        lines.append(f"sandbox_mode = {toml_string(sandbox)}")
    model = doc.frontmatter.get("model")
    if isinstance(model, str) and model not in {"inherit", "sonnet", "opus", "haiku"}:
        lines.append(f"model = {toml_string(model)}")
    effort = doc.frontmatter.get("effort")
    if isinstance(effort, str) and effort in {"low", "medium", "high"}:
        lines.append(f"model_reasoning_effort = {toml_string(effort)}")
    lines.append(f"developer_instructions = {toml_string(instructions)}")
    lines.append("")
    return "\n".join(lines)


def render_codex_skill(source: SourceItem) -> str:
    source_skill_md = source.source_path / "SKILL.md"
    doc = read_markdown(source_skill_md)
    name = slugify(str(doc.frontmatter.get("name") or source.logical_name))
    description = str(doc.frontmatter.get("description") or f"Converted Claude Code skill: {name}").strip()
    preserved = {key: value for key, value in doc.frontmatter.items() if key not in {"name", "description"}}
    parts = [
        "---",
        yaml_frontmatter({"name": name, "description": description}),
        "---",
        "",
        "<!-- Generated by claude-codex-sync. Edit the Claude source, not this file. -->",
        f"<!-- Source: {source_skill_md} -->",
        f"<!-- Source tree SHA256: {source.digest} -->",
        "",
        doc.body.strip(),
    ]
    if preserved:
        parts.extend([
            "", "---", "", "## Converted Claude-specific metadata for manual review", "", "```json",
            json.dumps(preserved, indent=2, ensure_ascii=False, sort_keys=True),
            "```",
        ])
    return "\n".join(parts).rstrip() + "\n"


def load_external_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    with path.open("rb") as file:
        data = tomllib.load(file)
    return data.get("claude-codex-sync", data)


def maybe_set(config: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        config[key] = value


def merged_config(args: argparse.Namespace) -> dict[str, Any]:
    config = dict(DEFAULTS)
    config.update(load_external_config(args.config))
    maybe_set(config, "poll_interval_seconds", args.interval)
    maybe_set(config, "prune", args.prune)
    maybe_set(config, "claude_agents_dir", args.claude_agents_dir)
    maybe_set(config, "claude_skills_dir", args.claude_skills_dir)
    maybe_set(config, "codex_agents_dir", args.codex_agents_dir)
    maybe_set(config, "codex_skills_dir", args.codex_skills_dir)
    maybe_set(config, "state_path", args.state_path)
    return config


class Syncer:
    def __init__(self, config: dict[str, Any]) -> None:
        self.claude_agents_dir = expand_path(config["claude_agents_dir"])
        self.claude_skills_dir = expand_path(config["claude_skills_dir"])
        self.codex_agents_dir = expand_path(config["codex_agents_dir"])
        self.codex_skills_dir = expand_path(config["codex_skills_dir"])
        self.state_path = expand_path(config["state_path"])
        self.prune = bool(config["prune"])

    def load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"sources": {}}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logging.warning("Invalid state file, rebuilding: %s", self.state_path)
            return {"sources": {}}
        if not isinstance(data, dict):
            return {"sources": {}}
        data.setdefault("sources", {})
        return data

    def save_state(self, state: dict[str, Any]) -> None:
        atomic_write_text(self.state_path, json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n")

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
                    existing.source_path, item.source_path, item.kind, item.logical_name,
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
        state = self.load_state()
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
        self.save_state(state)
        return changed

    def watch(self, interval_seconds: float) -> None:
        stop = False
        def request_stop(signum: int, frame: object) -> None:
            nonlocal stop
            stop = True
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
        logging.info("Watching Claude agents/skills with SHA256 polling")
        while not stop:
            try:
                changed = self.sync_once()
                if changed:
                    logging.info("Sync completed: %d changed item(s)", changed)
            except Exception:
                logging.exception("Sync failed")
            time.sleep(interval_seconds)
        logging.info("Stopped")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync Claude Code agents and skills into Codex.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Run one sync then exit.")
    mode.add_argument("--watch", action="store_true", help="Continuously watch and sync.")
    parser.add_argument("--config", type=Path, help="Optional app config TOML.")
    parser.add_argument("--interval", type=float, help="Polling interval in seconds.")
    parser.add_argument("--prune", action=argparse.BooleanOptionalAction, default=None, help="Remove generated outputs for deleted sources.")
    parser.add_argument("--claude-agents-dir", type=str)
    parser.add_argument("--claude-skills-dir", type=str)
    parser.add_argument("--codex-agents-dir", type=str)
    parser.add_argument("--codex-skills-dir", type=str)
    parser.add_argument("--state-path", type=str)
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = merged_config(args)
    syncer = Syncer(config)
    if args.watch:
        syncer.watch(float(config["poll_interval_seconds"]))
        return 0
    changed = syncer.sync_once()
    logging.info("Sync completed: %d changed item(s)", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
