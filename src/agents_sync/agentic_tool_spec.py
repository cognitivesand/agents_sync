"""AgenticToolSpec registry — descriptor for each agentic tool participating
in the sync.

One `AgenticToolSpec` represents one agentic tool (e.g. claude, codex,
antigravity). It declares which customization_types the tool supports (agent
and/or skill), where on disk each customization_type lives (config keys), and
how to parse / render / extract the pair_id for each (tool, type) cell via
`CustomizationTypeIO`.

This module is a passive descriptor. Enumeration, dispatch, and sync-loop
wiring live in `sync.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ParseFn = Callable[[str, dict[str, Any] | None], dict[str, Any]]
RenderFn = Callable[[dict[str, Any], str | None], str]
ExtractPairIdFn = Callable[[str], str | None]


@dataclass(frozen=True)
class CustomizationTypeIO:
    """Parse / render / extract bundle for one (agentic_tool, customization_type) cell.

    `storage` is either "single_file" (the artifact is one file with
    `file_suffix`) or "directory_skill" (the artifact is a directory whose
    metadata file is `SKILL.md`).
    """

    parse: ParseFn
    render: RenderFn
    extract_pair_id: ExtractPairIdFn
    storage: str
    file_suffix: str


@dataclass(frozen=True)
class AgenticToolSpec:
    """Descriptor for one agentic tool participating in the sync.

    `config_dir_keys` maps customization_type -> the config key holding the
    on-disk root for that type (e.g. "claude_agents_dir"). `io` maps the same
    customization_type -> its `CustomizationTypeIO`. `disable_config_key`, if
    set, names a boolean config key whose explicit False value makes the tool
    `disabled` per US-11 (registered but silent). Default `None` means the
    tool cannot be disabled — only made `unavailable` by a missing root.
    """

    name: str
    config_dir_keys: dict[str, str]
    io: dict[str, CustomizationTypeIO]
    disable_config_key: str | None = None

    @property
    def supported_customization_types(self) -> frozenset[str]:
        return frozenset(self.io.keys())


def _build_claude_spec() -> AgenticToolSpec:
    from agents_sync.claude_io import (
        extract_pair_id_from_md,
        parse_claude_md,
        render_claude_md,
    )

    def parse_agent(text: str, prior_canonical: dict[str, Any] | None) -> dict[str, Any]:
        return parse_claude_md(text, prior_canonical=prior_canonical, kind="agent")

    def parse_skill(text: str, prior_canonical: dict[str, Any] | None) -> dict[str, Any]:
        return parse_claude_md(text, prior_canonical=prior_canonical, kind="skill")

    def render(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_claude_md(canonical, prior_text=prior_text)

    return AgenticToolSpec(
        name="claude",
        config_dir_keys={
            "agent": "claude_agents_dir",
            "skill": "claude_skills_dir",
        },
        io={
            "agent": CustomizationTypeIO(
                parse=parse_agent,
                render=render,
                extract_pair_id=extract_pair_id_from_md,
                storage="single_file",
                file_suffix=".md",
            ),
            "skill": CustomizationTypeIO(
                parse=parse_skill,
                render=render,
                extract_pair_id=extract_pair_id_from_md,
                storage="directory_skill",
                file_suffix="",
            ),
        },
    )


def _build_codex_spec() -> AgenticToolSpec:
    from agents_sync.claude_io import extract_pair_id_from_md
    from agents_sync.codex_io import (
        extract_pair_id,
        parse_codex_agent_toml,
        parse_codex_skill_md,
        render_codex_agent_toml,
        render_codex_skill_md,
    )

    def parse_agent(text: str, prior_canonical: dict[str, Any] | None) -> dict[str, Any]:
        return parse_codex_agent_toml(text, prior_canonical=prior_canonical)

    def render_agent(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_codex_agent_toml(canonical)

    def parse_skill(text: str, prior_canonical: dict[str, Any] | None) -> dict[str, Any]:
        return parse_codex_skill_md(text, prior_canonical=prior_canonical)

    def render_skill(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_codex_skill_md(canonical)

    return AgenticToolSpec(
        name="codex",
        config_dir_keys={
            "agent": "codex_agents_dir",
            "skill": "codex_skills_dir",
        },
        io={
            "agent": CustomizationTypeIO(
                parse=parse_agent,
                render=render_agent,
                extract_pair_id=extract_pair_id,
                storage="single_file",
                file_suffix=".toml",
            ),
            "skill": CustomizationTypeIO(
                parse=parse_skill,
                render=render_skill,
                extract_pair_id=extract_pair_id_from_md,
                storage="directory_skill",
                file_suffix="",
            ),
        },
    )


def _build_antigravity_spec() -> AgenticToolSpec:
    from agents_sync.antigravity_io import (
        extract_pair_id_from_md,
        parse_antigravity_skill_md,
        render_antigravity_skill_md,
    )

    def parse_skill(text: str, prior_canonical: dict[str, Any] | None) -> dict[str, Any]:
        return parse_antigravity_skill_md(text, prior_canonical=prior_canonical)

    def render_skill(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_antigravity_skill_md(canonical, prior_text=prior_text)

    return AgenticToolSpec(
        name="antigravity",
        config_dir_keys={"skill": "antigravity_skills_dir"},
        io={
            "skill": CustomizationTypeIO(
                parse=parse_skill,
                render=render_skill,
                extract_pair_id=extract_pair_id_from_md,
                storage="directory_skill",
                file_suffix="",
            ),
        },
        disable_config_key="antigravity_enabled",
    )


def default_agentic_tools() -> dict[str, AgenticToolSpec]:
    """Return the default registry of agentic tools participating in the sync.

    Order matters for deterministic discovery iteration and for the §5.5
    mtime-tie tiebreaker (alphabetical by tool name). Antigravity is
    skill-only; the daemon respects `antigravity_enabled` from config.
    """
    return {
        "antigravity": _build_antigravity_spec(),
        "claude": _build_claude_spec(),
        "codex": _build_codex_spec(),
    }
