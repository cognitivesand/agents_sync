"""Antigravity — tool definition (data only).

Antigravity participates through directory-tree skills only; the rebuild's
skill (directory) dialect has not landed yet, so this definition carries no
active surface recipes until it does (a later S20 increment). Registering the
tool now keeps the registry the single complete tool list.
"""

from __future__ import annotations

from agents_sync.tools.tool_definition import ToolDefinition

ANTIGRAVITY_TOOL = ToolDefinition(name="antigravity", surface_recipes=())
