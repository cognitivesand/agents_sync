"""Factory for the per-tool ``rules`` ``CustomizationTypeIO`` cell."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import (
    CustomizationTypeIO,
    RulesFileLayout,
)


def build_global_rules_io(
    agentic_tool_name: str,
    candidate_file_names: tuple[str, ...],
    create_file_name: str | None = None,
) -> CustomizationTypeIO:
    """Build the global-rules IO cell.

    ``candidate_file_names`` is the ordered detection precedence (highest
    first); the daemon adopts the first present on disk (FR-10). When the
    daemon must create a rules file from scratch it uses ``create_file_name``,
    defaulting to the lowest-precedence (legacy) candidate — the name the tool
    natively loads (US-14 AC-5).
    """
    create_name = (
        create_file_name if create_file_name is not None else candidate_file_names[-1]
    )
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
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_rules_md(
            text,
            prior_canonical,
            agentic_tool_name=agentic_tool_name,
            artifact_path=artifact_path,
            artifact_root=artifact_root,
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
            fixed_file_name=create_name,
            candidate_file_names=candidate_file_names,
        ),
    )
