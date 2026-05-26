"""AgenticToolSpec factory for the antigravity tool (skill-only)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    DirectorySkillLayout,
)


def build_antigravity_spec() -> AgenticToolSpec:
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
        artifact_root: Path | None = None,
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
                file_layout=DirectorySkillLayout(),
            ),
        },
        disable_config_key="antigravity_enabled",
    )
