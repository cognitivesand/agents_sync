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
from collections.abc import Mapping
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
        artifact_root: Path | None = None,
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
class SharedKeyedMapLayout:
    """A customization artifact stored as one slot inside a shared keyed-map file.

    Unlike ``SingleFileLayout``, the artifact is *not* one file on disk —
    multiple artifacts share the same file, each owning one entry in a
    keyed map nested at ``map_key_path`` inside that file.

    ``shared_path_config_key`` names the config entry that resolves to
    the shared file path (e.g. ``mcp_servers_file`` for Cursor's
    ``~/.cursor/mcp.json``). ``map_key_path`` is the tuple of keys to
    walk into the parsed mapping to reach the map of slots (e.g.
    ``("mcpServers",)``). ``key_field`` names the canonical field whose
    value becomes the slot key (``"name"`` for every v0.5 ``mcp_server``
    adapter). ``file_format`` selects the registered format handler in
    ``shared_keyed_map_formats``.
    """

    shared_path_config_key: str
    map_key_path: tuple[str, ...]
    key_field: str = "name"
    file_format: str = "json"

    @property
    def storage(self) -> str:
        return "shared_keyed_map"

    @property
    def file_suffix(self) -> str:
        from agents_sync.shared_keyed_map_formats import get_format
        return get_format(self.file_format).extension

    @property
    def fixed_file_name(self) -> str | None:
        return None


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
    recursive: bool = False
    reserved_names: frozenset[str] = frozenset()

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


def is_reserved_customization_name(io: CustomizationTypeIO, name: str) -> bool:
    """Return whether a canonical name collides with a target-reserved name."""
    if not io.reserved_names:
        return False
    candidates = {name.casefold(), name.rsplit(":", 1)[-1].casefold()}
    reserved = {value.casefold() for value in io.reserved_names}
    return bool(candidates & reserved)


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
        artifact_root: Path | None = None,
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


def _mcp_server_io(
    agentic_tool_name: str,
    shared_path_config_key: str,
    map_key_path: tuple[str, ...],
    *,
    file_format: str,
    dialect: Any | None = None,
    config: Mapping[str, Any] | None = None,
) -> CustomizationTypeIO:
    from agents_sync.mcp_server_io import (
        DEFAULT_MCP_SERVER_DIALECT,
        extract_pair_id_from_mcp_server_json,
        parse_mcp_server_json,
        render_mcp_server_json,
    )

    mcp_dialect = dialect or DEFAULT_MCP_SERVER_DIALECT

    def secret_policy() -> str:
        if config is None:
            return "refuse"
        return str(config.get("mcp_server_secret_policy", "refuse"))

    def parse_mcp_server(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_mcp_server_json(
            text,
            prior_canonical,
            agentic_tool_name=agentic_tool_name,
            artifact_path=artifact_path,
            artifact_root=artifact_root,
            dialect=mcp_dialect,
            secret_policy=secret_policy(),
        )

    def render_mcp_server(
        canonical: dict[str, Any],
        prior_text: str | None,
    ) -> str:
        return render_mcp_server_json(
            canonical,
            prior_text,
            agentic_tool_name=agentic_tool_name,
            dialect=mcp_dialect,
            secret_policy=secret_policy(),
        )

    def extract_pair_id(text: str) -> str | None:
        return extract_pair_id_from_mcp_server_json(text, dialect=mcp_dialect)

    return CustomizationTypeIO(
        parse=parse_mcp_server,
        render=render_mcp_server,
        extract_pair_id=extract_pair_id,
        file_layout=SharedKeyedMapLayout(
            shared_path_config_key=shared_path_config_key,
            map_key_path=map_key_path,
            key_field="name",
            file_format=file_format,
        ),
    )


def _build_claude_spec(config: Mapping[str, Any] | None = None) -> AgenticToolSpec:
    from agents_sync.mcp_server_io import McpServerDialect
    from agents_sync.claude_io import (
        extract_pair_id_from_md,
        parse_claude_md,
        render_claude_md,
    )
    from agents_sync.slash_command_io import (
        parse_slash_command_markdown,
        render_slash_command_markdown,
        slash_command_slug,
    )

    def parse_agent(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_claude_md(text, prior_canonical=prior_canonical, kind="agent")

    def parse_skill(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_claude_md(text, prior_canonical=prior_canonical, kind="skill")

    def render(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_claude_md(canonical, prior_text=prior_text)

    def parse_slash_command(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_slash_command_markdown(
            text,
            prior_canonical,
            agentic_tool_name="claude",
            artifact_path=artifact_path,
            artifact_root=artifact_root,
        )

    def render_slash_command(
        canonical: dict[str, Any],
        prior_text: str | None,
    ) -> str:
        return render_slash_command_markdown(
            canonical,
            prior_text,
            agentic_tool_name="claude",
        )

    return AgenticToolSpec(
        name="claude",
        config_dir_keys={
            "agent": "claude_agents_dir",
            "skill": "claude_skills_dir",
            "slash_command": "claude_commands_dir",
            "rules": "claude_rules_dir",
            "mcp_server": "claude_mcp_servers_file",
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
            "slash_command": CustomizationTypeIO(
                parse=parse_slash_command,
                render=render_slash_command,
                extract_pair_id=extract_pair_id_from_md,
                storage="single_file",
                file_suffix=".md",
                slugify_name=slash_command_slug,
                recursive=True,
            ),
            "rules": _global_rules_io("claude", "CLAUDE.md"),
            "mcp_server": _mcp_server_io(
                "claude",
                "claude_mcp_servers_file",
                ("mcpServers",),
                file_format="json",
                config=config,
                dialect=McpServerDialect(
                    render_name_field=False,
                    transport_fields=("type", "transport", "transportType"),
                    auth_fields=("oauth", "auth"),
                    auth_render_field="oauth",
                    env_reference_style="claude",
                ),
            ),
        },
    )


def _build_codex_spec(config: Mapping[str, Any] | None = None) -> AgenticToolSpec:
    from agents_sync.mcp_server_io import McpServerDialect
    from agents_sync.claude_io import extract_pair_id_from_md
    from agents_sync.codex_io import (
        extract_pair_id,
        parse_codex_agent_toml,
        parse_codex_skill_md,
        render_codex_agent_toml,
        render_codex_skill_md,
    )
    from agents_sync.slash_command_io import (
        parse_slash_command_markdown,
        render_slash_command_markdown,
        slash_command_slug,
    )

    def parse_agent(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_codex_agent_toml(text, prior_canonical=prior_canonical)

    def render_agent(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_codex_agent_toml(canonical, prior_text=prior_text)

    def parse_skill(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_codex_skill_md(text, prior_canonical=prior_canonical)

    def render_skill(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_codex_skill_md(canonical)

    def parse_slash_command(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_slash_command_markdown(
            text,
            prior_canonical,
            agentic_tool_name="codex",
            artifact_path=artifact_path,
            artifact_root=artifact_root,
        )

    def render_slash_command(
        canonical: dict[str, Any],
        prior_text: str | None,
    ) -> str:
        return render_slash_command_markdown(
            canonical,
            prior_text,
            agentic_tool_name="codex",
        )

    return AgenticToolSpec(
        name="codex",
        config_dir_keys={
            "agent": "codex_agents_dir",
            "skill": "codex_skills_dir",
            "slash_command": "codex_prompts_dir",
            "rules": "codex_rules_dir",
            "mcp_server": "codex_config_file",
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
            "slash_command": CustomizationTypeIO(
                parse=parse_slash_command,
                render=render_slash_command,
                extract_pair_id=extract_pair_id_from_md,
                storage="single_file",
                file_suffix=".md",
                slugify_name=slash_command_slug,
                recursive=True,
            ),
            "rules": _global_rules_io("codex", "AGENTS.md"),
            "mcp_server": _mcp_server_io(
                "codex",
                "codex_config_file",
                ("mcp_servers",),
                file_format="toml",
                config=config,
                dialect=McpServerDialect(
                    render_name_field=False,
                    render_transport_field=False,
                    headers_fields=("http_headers", "headers"),
                    headers_render_field="http_headers",
                    env_http_headers_field="env_http_headers",
                    bearer_token_env_var_field="bearer_token_env_var",
                    auth_render_field=None,
                ),
            ),
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
                storage="directory_skill",
                file_suffix="",
            ),
        },
        disable_config_key="antigravity_enabled",
    )


def _build_opencode_spec(config: Mapping[str, Any] | None = None) -> AgenticToolSpec:
    from agents_sync.mcp_server_io import McpServerDialect
    from agents_sync.opencode_io import (
        extract_pair_id_from_md,
        opencode_skill_slug,
        parse_opencode_agent_md,
        parse_opencode_skill_md,
        render_opencode_agent_md,
        render_opencode_skill_md,
    )
    from agents_sync.slash_command_io import (
        parse_slash_command_markdown,
        render_slash_command_markdown,
        slash_command_slug,
    )

    def parse_agent(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
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
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_opencode_skill_md(text, prior_canonical=prior_canonical)

    def render_skill(canonical: dict[str, Any], prior_text: str | None) -> str:
        return render_opencode_skill_md(canonical, prior_text=prior_text)

    def parse_slash_command(
        text: str,
        prior_canonical: dict[str, Any] | None,
        *,
        artifact_path: Path | None = None,
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        return parse_slash_command_markdown(
            text,
            prior_canonical,
            agentic_tool_name="opencode",
            artifact_path=artifact_path,
            artifact_root=artifact_root,
        )

    def render_slash_command(
        canonical: dict[str, Any],
        prior_text: str | None,
    ) -> str:
        return render_slash_command_markdown(
            canonical,
            prior_text,
            agentic_tool_name="opencode",
        )

    return AgenticToolSpec(
        name="opencode",
        config_dir_keys={
            "agent": "opencode_agents_dir",
            "skill": "opencode_skills_dir",
            "slash_command": "opencode_commands_dir",
            "rules": "opencode_rules_dir",
            "mcp_server": "opencode_config_file",
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
            "slash_command": CustomizationTypeIO(
                parse=parse_slash_command,
                render=render_slash_command,
                extract_pair_id=extract_pair_id_from_md,
                storage="single_file",
                file_suffix=".md",
                slugify_name=slash_command_slug,
                recursive=True,
                reserved_names=frozenset({
                    "build",
                    "plan",
                    "general",
                    "explore",
                    "scout",
                }),
            ),
            "rules": _global_rules_io("opencode", "AGENTS.md"),
            "mcp_server": _mcp_server_io(
                "opencode",
                "opencode_config_file",
                ("mcp",),
                file_format="json",
                config=config,
                dialect=McpServerDialect(
                    render_name_field=False,
                    transport_fields=("type", "transport", "transportType"),
                    auth_fields=("oauth", "auth"),
                    auth_render_field="oauth",
                    command_mode="array",
                    env_fields=("environment", "env"),
                    disabled_fields=("enabled", "disabled"),
                    env_reference_style="opencode",
                    transport_render_values=(
                        ("stdio", "local"),
                        ("http", "remote"),
                        ("sse", "remote"),
                        ("streamable-http", "remote"),
                    ),
                ),
            ),
        },
        disable_config_key="opencode_enabled",
    )


def default_agentic_tools(
    config: Mapping[str, Any] | None = None,
) -> dict[str, AgenticToolSpec]:
    """Return the default registry of agentic tools participating in the sync.

    Order matters for deterministic discovery iteration and for the §5.5
    mtime-tie tiebreaker (alphabetical by tool name). Antigravity is
    skill-only; the daemon respects `antigravity_enabled` from config.
    """
    return {
        "antigravity": _build_antigravity_spec(),
        "claude": _build_claude_spec(config),
        "codex": _build_codex_spec(config),
        "opencode": _build_opencode_spec(config),
    }
