"""Shared recipe-application for the folding dialects (pure, no I/O).

Both ``markdown_frontmatter`` and ``keyed_map_slot`` reduce a surface to a flat
mapping of fields and apply the *same* recipe to it; they differ only in how they
extract that mapping from the wire (split front-matter vs navigate to a slot) and
reassemble it. This module is that one shared recipe-application, so "apply the
recipe" lives in exactly one place across dialects (proposal §10):

- ``fold_fields_into_canonical`` — map the recipe's ``known_fields`` onto canonical
  attributes, keep ``tool_only_fields`` under ``per_tool_only[tool]`` and every other
  field under ``per_tool_extra[tool]`` (no-foreign-leak, NFR-06/16), carry the embedded
  id through without minting (FR-11/AD-2), and stamp ``kind`` from the surface.
- ``project_canonical_to_fields`` — the inverse: write the canonical's view of one
  surface back onto a (possibly prior-seeded) mapping, dropping empty values.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import replace
from typing import Any

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import ToolSurface

# Canonical attributes whose field value is a list (or a comma-separated string).
_LIST_ATTRIBUTES = frozenset({"tools", "disallowed_tools"})


def fold_fields_into_canonical(
    fields: Mapping[str, Any],
    tool_surface: ToolSurface,
    prior_canonical: CanonicalDocument | None,
    *,
    body: str | None,
) -> CanonicalDocument:
    """Fold one surface's flat field mapping into the canonical document.

    ``body`` is the surface's body text, or ``None`` for a surface whose fold must leave
    the canonical's body untouched — either body-less (a keyed-map slot) or carrying its
    body as a named field (a structured-text artifact maps ``developer_instructions`` to
    ``body`` via ``known_fields``). A recipe supplies the body through *exactly one* of
    these two channels — the ``body`` argument or a ``known_fields`` pair targeting
    ``body`` — never both: the ``known_fields`` loop below runs after the ``body``
    argument and would otherwise silently override it.
    """
    surface_format = tool_surface.surface_format
    tool = tool_surface.tool

    base = prior_canonical or CanonicalDocument(artifact_id="", kind=tool_surface.kind)
    changes: dict[str, Any] = {
        "artifact_id": _recover_id(fields, surface_format.id_field, base),
        "kind": tool_surface.kind,
    }
    if body is not None:
        changes["body"] = body
    for field_key, attribute in surface_format.known_fields:
        value = fields.get(field_key)
        # A present-but-null key means "absent", not a None written onto a str-typed
        # canonical attribute (which would crash normalised()/content_digest()).
        if value is not None:
            changes[attribute] = _coerce(attribute, value)

    consumed = (
        {key for key, _ in surface_format.known_fields}
        | set(surface_format.tool_only_fields)
        | {surface_format.id_field}
    )
    tool_only = {key: fields[key] for key in surface_format.tool_only_fields if key in fields}
    extra = {key: value for key, value in fields.items() if key not in consumed}
    changes["per_tool_only"] = _with_tool_slot(base.per_tool_only, tool, tool_only)
    changes["per_tool_extra"] = _with_tool_slot(base.per_tool_extra, tool, extra)

    return replace(base, **changes)


def project_canonical_to_fields(
    canonical: CanonicalDocument,
    tool_surface: ToolSurface,
    base: MutableMapping[str, Any] | None = None,
) -> MutableMapping[str, Any]:
    """Project the canonical's view of one surface onto a field mapping.

    ``base`` is an optional prior mapping to write onto (the markdown dialect passes a
    comment-preserving prior front-matter); when ``None`` a fresh dict is built.
    """
    surface_format = tool_surface.surface_format
    tool = tool_surface.tool
    values = canonical.to_dict()  # thawed to plain dict/list so any emitter can serialise

    fields: MutableMapping[str, Any] = base if base is not None else {}
    if canonical.artifact_id:
        fields[surface_format.id_field] = canonical.artifact_id
    for field_key, attribute in surface_format.known_fields:
        _set_or_drop(fields, field_key, _render_value(attribute, values.get(attribute)))
    for key, value in values["per_tool_only"].get(tool, {}).items():
        fields[key] = value
    for key, value in values["per_tool_extra"].get(tool, {}).items():
        fields[key] = value
    return fields


def _recover_id(fields: Mapping[str, Any], id_field: str, base: CanonicalDocument) -> str:
    """Carry the embedded id through if present and a non-empty string, else the prior id."""
    embedded = fields.get(id_field)
    if isinstance(embedded, str) and embedded:
        return embedded
    return base.artifact_id


def _coerce(attribute: str, value: Any) -> Any:
    """Coerce a field value to the canonical attribute's shape."""
    if attribute in _LIST_ATTRIBUTES:
        return tuple(_as_string_list(value))
    return value


def _as_string_list(value: Any) -> list[str]:
    """A list, or a comma-separated string, as a list of strings."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _with_tool_slot(
    bags: Mapping[str, Any],
    tool: str,
    slot: Mapping[str, Any],
) -> dict[str, Any]:
    """Replace this tool's per-tool bag with ``slot`` (an empty slot clears it), keeping others.

    The surface is the source of truth for its own bag, so an empty slot removes a field
    the user deleted; the other tools' bags are carried untouched (no-foreign-leak).
    """
    merged = dict(bags)
    if slot:
        merged[tool] = dict(slot)
    else:
        merged.pop(tool, None)
    return merged


def _render_value(attribute: str, value: Any) -> Any:
    """Prepare a canonical value for emission (list attributes emit as a list)."""
    if attribute in _LIST_ATTRIBUTES:
        return list(value) if value else None
    return value


def _set_or_drop(fields: MutableMapping[str, Any], key: str, value: Any) -> None:
    """Set ``key`` to ``value``, or drop it when the value is empty (absent on the wire)."""
    if value is None or value == "" or value == []:
        fields.pop(key, None)
    else:
        fields[key] = value
