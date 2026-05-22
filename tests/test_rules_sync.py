"""Integration coverage for the v0.5 `rules` customization_type."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration  # audit slice 10 · TQ-01

import json
import os
import textwrap
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import (
    AgenticToolSpec,
    CustomizationTypeIO,
    RulesFileLayout,
)
from agents_sync.rules_io import (
    extract_pair_id_from_rules_md,
    parse_rules_md,
    render_rules_md,
)
from agents_sync.sync import Syncer


def _rules_io(tool_name: str, extension: str = ".md") -> CustomizationTypeIO:
    def parse(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_rules_md(
            text,
            prior_canonical,
            agentic_tool_name=tool_name,
            artifact_path=artifact_path,
        )

    def render(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_rules_md(
            canonical,
            prior_text,
            agentic_tool_name=tool_name,
        )

    return CustomizationTypeIO(
        parse=parse,
        render=render,
        extract_pair_id=extract_pair_id_from_rules_md,
        file_layout=RulesFileLayout(extension),
    )


def _rules_spec(tool_name: str, extension: str = ".md") -> AgenticToolSpec:
    return AgenticToolSpec(
        name=tool_name,
        config_dir_keys={"rules": f"{tool_name}_rules_dir"},
        io={"rules": _rules_io(tool_name, extension)},
    )


def _base_config(tmp_path: Path) -> dict[str, Any]:
    state_dir = tmp_path / "state"
    return {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "unused-ca"),
        "claude_commands_dir": str(tmp_path / "unused-cc"),
        "claude_skills_dir": str(tmp_path / "unused-cs"),
        "claude_rules_dir": str(tmp_path / "unused-cr"),
        "codex_agents_dir": str(tmp_path / "unused-xa"),
        "codex_prompts_dir": str(tmp_path / "unused-xp"),
        "codex_skills_dir": str(tmp_path / "unused-xs"),
        "codex_rules_dir": str(tmp_path / "unused-xr"),
        "antigravity_skills_dir": str(tmp_path / "unused-as"),
        "opencode_agents_dir": str(tmp_path / "unused-oa"),
        "opencode_commands_dir": str(tmp_path / "unused-oc"),
        "opencode_skills_dir": str(tmp_path / "unused-os"),
        "opencode_rules_dir": str(tmp_path / "unused-or"),
        "alpha_rules_dir": str(tmp_path / "alpha-rules"),
        "beta_rules_dir": str(tmp_path / "beta-rules"),
    }


def _rules_syncer(tmp_path: Path, *, beta_extension: str = ".md") -> Syncer:
    return Syncer(
        _base_config(tmp_path),
        agentic_tools={
            "alpha": _rules_spec("alpha"),
            "beta": _rules_spec("beta", beta_extension),
        },
    )


def _read_state(syncer: Syncer) -> dict[str, Any]:
    return json.loads((syncer.state_dir / "state.json").read_text())


def test_rules_adopt_between_synthetic_adapters(tmp_path: Path):
    syncer = _rules_syncer(tmp_path)
    source = syncer.tool_root("alpha", "rules") / "clean-code.md"
    source.write_text(
        textwrap.dedent(
            """\
            ---
            description: Clean Python
            globs:
              - "**/*.py"
            alwaysApply: true
            trigger: manual
            vendor-alpha: keep
            ---
            Prefer small functions.
            """
        )
    )

    result = syncer.sync_once(); changed = result.changed

    assert changed == 1
    state = _read_state(syncer)
    pair_id, entry = next(iter(state["customization_artifacts"].items()))
    assert entry["customization_type"] == "rules"
    assert set(entry["agentic_tools"]) == {"alpha", "beta"}
    assert f"pair_id: {pair_id}" in source.read_text()

    target = syncer.tool_root("beta", "rules") / "clean-code.md"
    target_text = target.read_text()
    assert f"pair_id: {pair_id}" in target_text
    assert "description: Clean Python" in target_text
    assert "alwaysApply: true" in target_text
    assert "Prefer small functions." in target_text
    assert "vendor-alpha" not in target_text

    canonical = json.loads((syncer.state_dir / "canonical" / f"{pair_id}.json").read_text())
    assert canonical["name"] == "clean-code"
    assert canonical["globs"] == ["**/*.py"]
    assert canonical["provenance"] == "user"
    assert canonical["private"] is False
    assert canonical["per_agentic_tool_extra"]["alpha"] == {"vendor-alpha": "keep"}


def test_rules_layout_can_project_to_mdc_extension(tmp_path: Path):
    syncer = _rules_syncer(tmp_path, beta_extension=".mdc")
    source = syncer.tool_root("alpha", "rules") / "cursor-style.md"
    source.write_text("---\ndescription: Cursor style\n---\nApply in Cursor.\n")

    syncer.sync_once()

    assert (syncer.tool_root("beta", "rules") / "cursor-style.mdc").is_file()
    assert not (syncer.tool_root("beta", "rules") / "cursor-style.md").exists()


def test_private_rules_are_excluded_end_to_end(tmp_path: Path):
    syncer = _rules_syncer(tmp_path)
    source = syncer.tool_root("alpha", "rules") / "local-memory.md"
    original = textwrap.dedent(
        """\
        ---
        private: true
        ---
        Do not sync this.
        """
    )
    source.write_text(original)

    result = syncer.sync_once(); changed = result.changed

    assert changed == 0
    assert source.read_text() == original
    assert list(syncer.tool_root("beta", "rules").iterdir()) == []
    assert _read_state(syncer)["customization_artifacts"] == {}
    assert not (syncer.state_dir / "canonical").exists()
    assert not (syncer.state_dir / "archive").exists()


def test_private_existing_rule_is_not_overwritten_as_projection_target(tmp_path: Path):
    syncer = _rules_syncer(tmp_path)
    pair_id = "00000000-0000-4000-8000-000000000099"
    private_rule = syncer.tool_root("alpha", "rules") / "shared.md"
    public_rule = syncer.tool_root("beta", "rules") / "shared.md"
    private_text = (
        "---\n"
        f"pair_id: {pair_id}\n"
        "private: true\n"
        "---\n"
        "Local only.\n"
    )
    public_text = (
        "---\n"
        f"pair_id: {pair_id}\n"
        "description: Public rule\n"
        "---\n"
        "Sync me.\n"
    )
    private_rule.write_text(private_text)
    public_rule.write_text(public_text)
    os.utime(private_rule, (1000.0, 1000.0))
    os.utime(public_rule, (2000.0, 2000.0))

    result = syncer.sync_once(); changed = result.changed

    assert changed == 1
    assert private_rule.read_text() == private_text
    entry = _read_state(syncer)["customization_artifacts"][pair_id]
    assert set(entry["agentic_tools"]) == {"beta"}
    assert not (syncer.state_dir / "archive" / pair_id / "alpha").exists()
