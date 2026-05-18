"""Integration tests for v0.5 slash_command synchronization."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import AgenticToolSpec, CustomizationTypeIO
from agents_sync.canonical import load_canonical
from agents_sync.slash_command_io import (
    extract_pair_id_from_slash_command_markdown,
    extract_pair_id_from_slash_command_toml,
    parse_slash_command_toml,
    parse_slash_command_markdown,
    render_slash_command_toml,
    render_slash_command_markdown,
    slash_command_slug,
)
from agents_sync.state import load_state
from agents_sync.sync import Syncer


def _required_config(tmp_path: Path, state_dir: Path) -> dict[str, Any]:
    """Return the legacy required keys plus test-specific additions."""
    return {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "unused-ca"),
        "claude_commands_dir": str(tmp_path / "unused-cc"),
        "claude_skills_dir": str(tmp_path / "unused-cs"),
        "codex_agents_dir": str(tmp_path / "unused-xa"),
        "codex_prompts_dir": str(tmp_path / "unused-xp"),
        "codex_skills_dir": str(tmp_path / "unused-xs"),
        "antigravity_skills_dir": str(tmp_path / "unused-as"),
        "opencode_agents_dir": str(tmp_path / "unused-oa"),
        "opencode_commands_dir": str(tmp_path / "unused-oc"),
        "opencode_skills_dir": str(tmp_path / "unused-os"),
    }


def _markdown_tool(
    name: str,
    config_key: str,
    *,
    reserved_names: frozenset[str] = frozenset(),
) -> AgenticToolSpec:
    def parse(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_slash_command_markdown(
            text,
            prior_canonical,
            agentic_tool_name=name,
            artifact_path=artifact_path,
            artifact_root=artifact_root,
        )

    def render(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_slash_command_markdown(
            canonical,
            prior_text,
            agentic_tool_name=name,
        )

    return AgenticToolSpec(
        name=name,
        config_dir_keys={"slash_command": config_key},
        io={
            "slash_command": CustomizationTypeIO(
                parse=parse,
                render=render,
                extract_pair_id=extract_pair_id_from_slash_command_markdown,
                storage="single_file",
                file_suffix=".md",
                slugify_name=slash_command_slug,
                recursive=True,
                reserved_names=reserved_names,
            )
        },
    )


def _toml_tool(name: str, config_key: str) -> AgenticToolSpec:
    def parse(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_slash_command_toml(
            text,
            prior_canonical,
            agentic_tool_name=name,
            artifact_path=artifact_path,
            artifact_root=artifact_root,
        )

    def render(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_slash_command_toml(
            canonical,
            prior_text,
            agentic_tool_name=name,
        )

    return AgenticToolSpec(
        name=name,
        config_dir_keys={"slash_command": config_key},
        io={
            "slash_command": CustomizationTypeIO(
                parse=parse,
                render=render,
                extract_pair_id=extract_pair_id_from_slash_command_toml,
                storage="single_file",
                file_suffix=".toml",
                slugify_name=slash_command_slug,
                recursive=True,
            )
        },
    )


def test_slash_command_syncs_markdown_to_toml_with_namespace(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    md_root = tmp_path / "md-commands"
    toml_root = tmp_path / "toml-commands"
    config = _required_config(tmp_path, state_dir)
    config.update({
        "md_commands_dir": str(md_root),
        "toml_commands_dir": str(toml_root),
    })
    syncer = Syncer(
        config,
        agentic_tools={
            "mdtool": _markdown_tool("mdtool", "md_commands_dir"),
            "tomltool": _toml_tool("tomltool", "toml_commands_dir"),
        },
    )

    body = "Use $ARGUMENTS exactly.\n!git status\n@README.md\n"
    source = md_root / "git" / "commit.md"
    source.parent.mkdir(parents=True)
    source.write_text(body, encoding="utf-8")

    assert syncer.sync_once() == 1

    injected = source.read_text(encoding="utf-8")
    pair_id = extract_pair_id_from_slash_command_markdown(injected)
    assert pair_id is not None
    target = toml_root / "git" / "commit.toml"
    assert target.exists()

    target_canonical = parse_slash_command_toml(
        target.read_text(encoding="utf-8"),
        None,
        agentic_tool_name="tomltool",
        artifact_path=target,
        artifact_root=toml_root,
    )
    assert target_canonical["pair_id"] == pair_id
    assert target_canonical["name"] == "git:commit"
    assert target_canonical["body"] == body

    state = load_state(syncer.state_dir)
    assert set(state[pair_id].agentic_tools) == {"mdtool", "tomltool"}
    canonical = load_canonical(syncer.state_dir, pair_id)
    assert canonical is not None
    assert canonical["kind"] == "slash_command"
    assert canonical["name"] == "git:commit"


def test_slash_command_syncs_toml_to_markdown_preserving_prompt_grammar(
    tmp_path: Path,
):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    md_root = tmp_path / "md-commands"
    toml_root = tmp_path / "toml-commands"
    config = _required_config(tmp_path, state_dir)
    config.update({
        "md_commands_dir": str(md_root),
        "toml_commands_dir": str(toml_root),
    })
    syncer = Syncer(
        config,
        agentic_tools={
            "mdtool": _markdown_tool("mdtool", "md_commands_dir"),
            "tomltool": _toml_tool("tomltool", "toml_commands_dir"),
        },
    )

    body = "Deploy {{args}}.\n!{git status --short}\n@{README.md}\n$ARGUMENTS\n"
    source = toml_root / "ops" / "deploy.toml"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join([
            'description = "Deploy service"',
            '"argument-hint" = "[service]"',
            '"allowed-tools" = "Shell(git:*), Read"',
            'mode = "execute"',
            f"prompt = {json.dumps(body)}",
            "",
        ]),
        encoding="utf-8",
    )

    assert syncer.sync_once() == 1

    pair_id = extract_pair_id_from_slash_command_toml(
        source.read_text(encoding="utf-8")
    )
    assert pair_id is not None
    target = md_root / "ops" / "deploy.md"
    assert target.exists()

    target_canonical = parse_slash_command_markdown(
        target.read_text(encoding="utf-8"),
        None,
        agentic_tool_name="mdtool",
        artifact_path=target,
        artifact_root=md_root,
    )
    assert target_canonical["pair_id"] == pair_id
    assert target_canonical["name"] == "ops:deploy"
    assert target_canonical["description"] == "Deploy service"
    assert target_canonical["argument_hint"] == "[service]"
    assert target_canonical["allowed_tools"] == ["Shell(git:*)", "Read"]
    assert target_canonical["body"] == body


def test_reserved_slash_command_name_skips_only_that_target(tmp_path: Path, caplog):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    source_root = tmp_path / "source-commands"
    reserved_root = tmp_path / "reserved-commands"
    toml_root = tmp_path / "toml-commands"
    config = _required_config(tmp_path, state_dir)
    config.update({
        "source_commands_dir": str(source_root),
        "reserved_commands_dir": str(reserved_root),
        "toml_commands_dir": str(toml_root),
    })
    caplog.set_level("WARNING")
    syncer = Syncer(
        config,
        agentic_tools={
            "source": _markdown_tool("source", "source_commands_dir"),
            "reserved": _markdown_tool(
                "reserved",
                "reserved_commands_dir",
                reserved_names=frozenset({"plan"}),
            ),
            "tomltool": _toml_tool("tomltool", "toml_commands_dir"),
        },
    )

    source = source_root / "plan.md"
    source.write_text("Plan with {{args}}.\n", encoding="utf-8")

    assert syncer.sync_once() == 1

    pair_id = extract_pair_id_from_slash_command_markdown(
        source.read_text(encoding="utf-8")
    )
    assert pair_id is not None
    assert not (reserved_root / "plan.md").exists()
    assert (toml_root / "plan.toml").exists()
    assert "Reserved slash_command name skipped" in caplog.text

    state = load_state(syncer.state_dir)
    assert set(state[pair_id].agentic_tools) == {"source", "tomltool"}
