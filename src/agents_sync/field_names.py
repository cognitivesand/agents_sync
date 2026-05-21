"""Named constants for cross-adapter field names.

Replaces the open-coded magic strings that previously appeared across
four adapter modules whenever the canonical schema and a tool's native
frontmatter vocabulary diverge — most visibly the camelCase /
snake_case mismatch between Claude's ``permissionMode`` /
``mcpServers`` / ``disallowedTools`` and the canonical / Codex
``permission_mode`` / ``mcp_servers`` / ``disallowed_tools``.

Each adapter's vocabulary lives in its own ``*Field`` namespace class;
the canonical vocabulary lives in :class:`CanonicalField`. The
declarative pairs in :data:`CROSS_ADAPTER_FIELD_MAP` document every
across-adapter equivalence so a reader does not need to chase string
literals through four modules to see that
``claude.permissionMode == canonical.permission_mode`` (audit slice 07
· CQ-15).

This module is **descriptive**: the adapters still perform their own
conversion (we don't yet have a generic "rename keys" pass), but every
name they touch is anchored to a named constant here so a future
adapter sees the conversion table in one place.
"""
from __future__ import annotations

from typing import Final


class CanonicalField:
    """Field names in the canonical document schema (snake_case)."""

    PAIR_ID: Final[str] = "pair_id"
    KIND: Final[str] = "kind"
    NAME: Final[str] = "name"
    DESCRIPTION: Final[str] = "description"
    BODY: Final[str] = "body"
    MODEL: Final[str] = "model"
    EFFORT: Final[str] = "effort"
    TOOLS: Final[str] = "tools"
    DISALLOWED_TOOLS: Final[str] = "disallowed_tools"
    PERMISSION_MODE: Final[str] = "permission_mode"
    PROVENANCE: Final[str] = "provenance"
    PRIVATE: Final[str] = "private"
    PER_AGENTIC_TOOL_ONLY: Final[str] = "per_agentic_tool_only"
    PER_AGENTIC_TOOL_EXTRA: Final[str] = "per_agentic_tool_extra"
    MCP_SERVERS: Final[str] = "mcp_servers"


class ClaudeField:
    """Field names in Claude .md frontmatter (camelCase for Claude-specific
    fields; canonical names elsewhere)."""

    PERMISSION_MODE: Final[str] = "permissionMode"
    DISALLOWED_TOOLS: Final[str] = "disallowedTools"
    MCP_SERVERS: Final[str] = "mcpServers"
    HOOKS: Final[str] = "hooks"


class CodexField:
    """Field names in Codex TOML / SKILL.md (snake_case plus a few legacy
    aliases)."""

    MCP_SERVERS: Final[str] = "mcp_servers"
    MODEL_REASONING_EFFORT: Final[str] = "model_reasoning_effort"
    DEVELOPER_INSTRUCTIONS: Final[str] = "developer_instructions"
    SANDBOX_MODE: Final[str] = "sandbox_mode"
    NICKNAME_CANDIDATES: Final[str] = "nickname_candidates"


class OpencodeField:
    """Field names in opencode .md frontmatter (snake_case)."""

    PERMISSION: Final[str] = "permission"
    DESCRIPTION: Final[str] = "description"


# Declarative cross-adapter equivalence table.
#
# Each entry is (canonical_name, {adapter_name: native_name}). Adapters
# missing from the dict use the canonical name verbatim. The table is
# documentary today: each adapter still performs its own conversion in
# its parser / renderer (the open-coded pattern is unavoidable until a
# generic rename pass exists), but anyone wondering "what does Claude
# call permission_mode?" can read it here without grepping four files.
CROSS_ADAPTER_FIELD_MAP: Final[tuple[tuple[str, dict[str, str]], ...]] = (
    (
        CanonicalField.PERMISSION_MODE,
        {"claude": ClaudeField.PERMISSION_MODE},
    ),
    (
        CanonicalField.DISALLOWED_TOOLS,
        {"claude": ClaudeField.DISALLOWED_TOOLS},
    ),
    (
        CanonicalField.MCP_SERVERS,
        {"claude": ClaudeField.MCP_SERVERS, "codex": CodexField.MCP_SERVERS},
    ),
    (
        CanonicalField.EFFORT,
        {"codex": CodexField.MODEL_REASONING_EFFORT},
    ),
    (
        CanonicalField.BODY,
        {"codex": CodexField.DEVELOPER_INSTRUCTIONS},
    ),
)


def adapter_field_name(canonical_name: str, adapter: str) -> str:
    """Return the adapter-native spelling for a canonical field name.

    Falls back to ``canonical_name`` when the adapter uses the canonical
    spelling verbatim. Useful in future adapter helpers that want to
    drive the rename off the table without inlining the mapping.
    """
    for canonical, adapter_map in CROSS_ADAPTER_FIELD_MAP:
        if canonical == canonical_name and adapter in adapter_map:
            return adapter_map[adapter]
    return canonical_name


__all__ = [
    "CanonicalField",
    "ClaudeField",
    "CodexField",
    "OpencodeField",
    "CROSS_ADAPTER_FIELD_MAP",
    "adapter_field_name",
]
