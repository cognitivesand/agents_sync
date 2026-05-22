"""Factory for the per-tool ``mcp_server`` ``CustomizationTypeIO`` cell."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import (
    CustomizationTypeIO,
    SharedKeyedMapLayout,
)


def build_mcp_server_io(
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
        # Tolerant read: prefer the canonical ``secret_policy`` key but
        # accept the deprecated ``mcp_server_secret_policy`` as a fall-back
        # for callers that construct config dicts directly (e.g. tests).
        # ``apply_mcp_secret_policy`` normalizes the value at entry, so
        # both old and new spellings reach the policy engine intact.
        if config is None:
            return "secrets_refused"
        return str(
            config.get("secret_policy")
            or config.get("mcp_server_secret_policy")
            or "secrets_refused"
        )

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
            slot_format=file_format,
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
            slot_format=file_format,
            secret_policy=secret_policy(),
        )

    def extract_pair_id(text: str) -> str | None:
        return extract_pair_id_from_mcp_server_json(
            text,
            dialect=mcp_dialect,
            slot_format=file_format,
        )

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
