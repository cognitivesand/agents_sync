"""AgenticToolSpec registry — data model + default registry.

One `AgenticToolSpec` represents one agentic tool (e.g. claude, codex,
cursor, antigravity, opencode). It declares which customization_types the tool
supports (agent and/or skill), where on disk each customization_type lives
(config keys), and how to parse / render / extract the pair_id for each
(tool, type) cell via `CustomizationTypeIO`.

This module is a passive descriptor. Per-tool factory functions live
under :mod:`agents_sync.tool_specs`; sync-loop wiring lives in
:mod:`agents_sync.sync`.
"""
from __future__ import annotations

from collections.abc import Mapping
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
        artifact_root: Path | None = None,
    ) -> dict[str, Any]:
        ...


class FileLayout(Protocol):
    """Storage shape for one customization_type on one agentic_tool.

    Polymorphic methods (Phase 2.2 of the audit remediation) let callers
    operate on a layout without sniffing its concrete subclass:

    - ``probe_check_path(resolved)`` — given the resolved config value (a
      file path or directory path), returns the Path that ``ToolStatusTracker``
      should check for existence/permissions. For per-file layouts that is
      the path itself; for shared-keyed-map layouts the shared file may not
      yet exist on a fresh install, so the *parent directory* is probed
      instead.
    - ``tolerates_missing_config_key()`` — whether absence of the resolved
      config value should mark the tool unavailable (``False``, the default)
      or simply skip the cell silently (``True``, used by
      ``SharedKeyedMapLayout`` whose ``shared_path_config_key`` is optional
      until a user actually configures an MCP file).
    """

    @property
    def storage(self) -> str:
        ...

    @property
    def file_suffix(self) -> str:
        ...

    @property
    def fixed_file_name(self) -> str | None:
        ...

    def probe_check_path(self, resolved: Path) -> Path:
        ...

    def tolerates_missing_config_key(self) -> bool:
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

    def probe_check_path(self, resolved: Path) -> Path:
        return resolved

    def tolerates_missing_config_key(self) -> bool:
        return False


@dataclass(frozen=True)
class RulesFileLayout(SingleFileLayout):
    """Layout for v0.5 `rules` artifacts."""


@dataclass(frozen=True)
class DirectorySkillLayout:
    """A skill artifact stored as a directory containing a ``SKILL.md`` plus
    auxiliary files. The directory itself *is* the artifact identity.
    """

    @property
    def storage(self) -> str:
        return "directory_skill"

    @property
    def file_suffix(self) -> str:
        return ""

    @property
    def fixed_file_name(self) -> str | None:
        return None

    def probe_check_path(self, resolved: Path) -> Path:
        return resolved

    def tolerates_missing_config_key(self) -> bool:
        return False


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

    def probe_check_path(self, resolved: Path) -> Path:
        # The shared file itself may not exist yet — a fresh install starts
        # with an empty ``~/.cursor/mcp.json`` directory. Probe the parent
        # so the tool reads ``available`` once the directory is created,
        # even before any MCP server is configured.
        return resolved.parent

    def tolerates_missing_config_key(self) -> bool:
        return True


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

    def __post_init__(self) -> None:
        """Reject ``config_dir_keys`` / ``io`` drift at construction time.

        The two dicts encode the same set of supported customization types
        from two different angles (config-key surface vs. IO bundle).
        ``ToolStatusTracker`` iterates ``config_dir_keys`` to probe roots,
        while ``supported_customization_types`` reads ``io`` — historically a
        single missing entry on either side caused either silent
        "available without probe" status or a ``KeyError`` at probe time.
        Catching the divergence at registry-build time (per audit slice
        05 · CQ-03) turns a silent runtime corruption into a clear startup
        failure that names the missing key and the tool involved.
        """
        config_keys = set(self.config_dir_keys.keys())
        io_keys = set(self.io.keys())
        if config_keys != io_keys:
            only_in_config = sorted(config_keys - io_keys)
            only_in_io = sorted(io_keys - config_keys)
            raise ValueError(
                f"AgenticToolSpec(name={self.name!r}) capability matrix drift: "
                f"in config_dir_keys but not io: {only_in_config!r}; "
                f"in io but not config_dir_keys: {only_in_io!r}"
            )

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


def default_agentic_tools(
    config: Mapping[str, Any] | None = None,
) -> dict[str, AgenticToolSpec]:
    """Return the default registry of agentic tools participating in the sync.

    Order matters for deterministic discovery iteration and for the §5.5
    mtime-tie tiebreaker (alphabetical by tool name). Antigravity is
    skill-only; the daemon respects `antigravity_enabled` from config.
    """
    from agents_sync.tool_specs import (
        build_antigravity_spec,
        build_claude_spec,
        build_codex_spec,
        build_cursor_spec,
        build_opencode_spec,
    )

    return {
        "antigravity": build_antigravity_spec(),
        "claude": build_claude_spec(config),
        "codex": build_codex_spec(config),
        "cursor": build_cursor_spec(config),
        "opencode": build_opencode_spec(config),
    }
