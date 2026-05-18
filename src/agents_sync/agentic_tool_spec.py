"""AgenticToolSpec registry — descriptor for each agentic tool participating
in the sync.

One `AgenticToolSpec` represents one agentic tool (e.g. claude, codex,
antigravity, opencode). It declares which customization_types the tool
supports (agent and/or skill), where on disk each customization_type lives
(config keys), and how to parse / render / extract the pair_id for each
(tool, type) cell via `CustomizationTypeIO`.

This module is a passive descriptor. Enumeration, dispatch, and sync-loop
wiring live in `sync.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol


RenderFn = Callable[[dict[str, Any], str | None], str]
ExtractPairIdFn = Callable[[str], str | None]
SlugifyFn = Callable[[str], str]


class ParseFn(Protocol):
    def __call__(
        self,
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
    ) -> dict[str, Any]:
        ...


class FileLayout(Protocol):
    """Storage shape for one customization_type on one agentic_tool."""

    @property
    def storage(self) -> str:
        ...

    @property
    def file_suffix(self) -> str:
        ...

    @property
    def fixed_file_name(self) -> str | None:
        ...


@dataclass(frozen=True)
class SingleFileLayout:
    """A customization artifact stored as one file under its configured root."""

    extension: str
    fixed_file_name: str | None = None

    def __post_init__(self) -> None:
        if (
            self.fixed_file_name is not None
            and not self.fixed_file_name.endswith(self.extension)
        ):
            raise ValueError("fixed_file_name must end with extension")

    @property
    def storage(self) -> str:
        return "single_file"

    @property
    def file_suffix(self) -> str:
        return self.extension


@dataclass(frozen=True)
class RulesFileLayout(SingleFileLayout):
    """Layout for v0.5 `rules` artifacts."""


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
    storage: str = ""
    file_suffix: str = ""
    file_layout: FileLayout | None = None
    slugify_name: SlugifyFn | None = None

    def __post_init__(self) -> None:
        if self.file_layout is None:
            if not self.storage:
                raise ValueError("CustomizationTypeIO requires storage or file_layout")
            return

        layout_storage = self.file_layout.storage
        layout_suffix = self.file_layout.file_suffix
        if self.storage and self.storage != layout_storage:
            raise ValueError("storage conflicts with file_layout")
        if self.file_suffix and self.file_suffix != layout_suffix:
            raise ValueError("file_suffix conflicts with file_layout")
        object.__setattr__(self, "storage", layout_storage)
        object.__setattr__(self, "file_suffix", layout_suffix)

    @property
    def fixed_file_name(self) -> str | None:
        if self.file_layout is None:
            return None
        return self.file_layout.fixed_file_name


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


def _global_rules_io(
    agentic_tool_name: str,
    fixed_file_name: str,
) -> CustomizationTypeIO:
    from agents_sync.rules_io import (
        GLOBAL_RULE_NAME,
        extract_pair_id_from_rules_md,
        parse_rules_md,
        render_rules_md,
    )

    def parse_rules(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
    ) -> dict[str, Any]:
        return parse_rules_md(
            text,
            prior_canonical,
            agentic_tool_name=agentic_tool_name,
            artifact_path=artifact_path,
            canonical_name=GLOBAL_RULE_NAME,
        )

    def render_rules(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_rules_md(
            canonical,
            prior_text,
            agentic_tool_name=agentic_tool_name,
        )

    return CustomizationTypeIO(
        parse=parse_rules,
        render=render_rules,
        extract_pair_id=extract_pair_id_from_rules_md,
        file_layout=RulesFileLayout(
            extension=".md",
            fixed_file_name=fixed_file_name,
        ),
    )


def _build_claude_spec() -> AgenticToolSpec:
    from agents_sync.claude_io import (
        extract_pair_id_from_md,
        parse_claude_md,
        render_claude_md,
    )

    def parse_agent(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
    ) -> dict[str, Any]:
        return parse_claude_md(text, prior_canonical=prior_canonical, kind="agent")

    def parse_skill(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
    ) -> dict[str, Any]:
        return parse_claude_md(text, prior_canonical=prior_canonical, kind="skill")

    def render(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_claude_md(canonical, prior_text=prior_text)

    return AgenticToolSpec(
        name="claude",
        config_dir_keys={
            "agent": "claude_agents_dir",
            "skill": "claude_skills_dir",
            "rules": "claude_rules_dir",
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
            "rules": _global_rules_io("claude", "CLAUDE.md"),
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

    def parse_agent(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
    ) -> dict[str, Any]:
        return parse_codex_agent_toml(text, prior_canonical=prior_canonical)

    def render_agent(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_codex_agent_toml(canonical, prior_text=prior_text)

    def parse_skill(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
    ) -> dict[str, Any]:
        return parse_codex_skill_md(text, prior_canonical=prior_canonical)

    def render_skill(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_codex_skill_md(canonical)

    return AgenticToolSpec(
        name="codex",
        config_dir_keys={
            "agent": "codex_agents_dir",
            "skill": "codex_skills_dir",
            "rules": "codex_rules_dir",
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
            "rules": _global_rules_io("codex", "AGENTS.md"),
        },
    )


def _build_antigravity_spec() -> AgenticToolSpec:
    from agents_sync.antigravity_io import (
        extract_pair_id_from_md,
        parse_antigravity_skill_md,
        render_antigravity_skill_md,
    )

    def parse_skill(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
    ) -> dict[str, Any]:
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


def _build_opencode_spec() -> AgenticToolSpec:
    from agents_sync.opencode_io import (
        extract_pair_id_from_md,
        opencode_skill_slug,
        parse_opencode_agent_md,
        parse_opencode_skill_md,
        render_opencode_agent_md,
        render_opencode_skill_md,
    )

    def parse_agent(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
    ) -> dict[str, Any]:
        return parse_opencode_agent_md(
            text,
            prior_canonical=prior_canonical,
            artifact_path=artifact_path,
        )

    def render_agent(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_opencode_agent_md(canonical, prior_text=prior_text)

    def parse_skill(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
    ) -> dict[str, Any]:
        return parse_opencode_skill_md(text, prior_canonical=prior_canonical)

    def render_skill(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_opencode_skill_md(canonical, prior_text=prior_text)

    return AgenticToolSpec(
        name="opencode",
        config_dir_keys={
            "agent": "opencode_agents_dir",
            "skill": "opencode_skills_dir",
            "rules": "opencode_rules_dir",
        },
        io={
            "agent": CustomizationTypeIO(
                parse=parse_agent,
                render=render_agent,
                extract_pair_id=extract_pair_id_from_md,
                storage="single_file",
                file_suffix=".md",
            ),
            "skill": CustomizationTypeIO(
                parse=parse_skill,
                render=render_skill,
                extract_pair_id=extract_pair_id_from_md,
                storage="directory_skill",
                file_suffix="",
                slugify_name=opencode_skill_slug,
            ),
            "rules": _global_rules_io("opencode", "AGENTS.md"),
        },
        disable_config_key="opencode_enabled",
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
        "opencode": _build_opencode_spec(),
    }
