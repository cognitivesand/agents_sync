"""Read / write primitives for ``SharedKeyedMapLayout`` files.

The layout class declares storage shape; this module is the IO contract.
Three operations:

- ``read_slots(shared_path, layout)`` — return ``{slot_key: slot_text}`` for
  every entry under ``map_key_path``. Missing file or missing map_key_path
  is reported as ``({}, missing_reason)`` rather than raising; the caller
  decides whether to log.
- ``apply_slot(shared_path, layout, slot_key, new_slot_text)`` — read the
  shared file, replace / insert / delete the slot under ``map_key_path``,
  serialise the merged mapping, and atomically write it back. Returns the
  prior slot text (or ``None``) so the caller can archive it.
- ``serialize_slot(value, layout)`` — serialise one slot value (the parsed
  Python object for a single slot) to text. Used to feed the canonical
  parser, which expects ``text``.

Concurrent writers (a user's editor, the agentic tool itself) are handled
by the optimistic detect-and-retry pattern: ``apply_slot`` re-reads the
file just before writing; if the bytes have changed since the initial
read it retries once, and aborts if the second read also races. The
shared file is never partially overwritten.
"""
from __future__ import annotations

import logging
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import SharedKeyedMapLayout
from agents_sync.shared_keyed_map_formats import get_format
from agents_sync.state import atomic_write_text


def read_slots(
    shared_path: Path,
    layout: SharedKeyedMapLayout,
) -> tuple[dict[str, str], str | None]:
    """Return ``({slot_key: slot_text}, None)`` for every slot under
    ``layout.map_key_path``. On a recoverable absence (file missing, map
    key absent, map present but not a mapping) returns ``({}, reason)``
    where ``reason`` is a short string the caller can include in a log
    line. Unrecoverable errors (unreadable bytes, malformed format) are
    propagated."""
    if not shared_path.exists():
        return {}, "file-missing"
    text = shared_path.read_text(encoding="utf-8")
    format_handler = get_format(layout.file_format)
    root = format_handler.deserialize(text)
    node: Any = root
    for key in layout.map_key_path:
        if not isinstance(node, dict) or key not in node:
            return {}, "map-key-absent"
        node = node[key]
    if not isinstance(node, dict):
        return {}, "map-not-an-object"
    slots: dict[str, str] = {}
    for slot_key, slot_value in node.items():
        slot_key_text = str(slot_key)
        if isinstance(slot_value, dict) and layout.key_field not in slot_value:
            slot_value = dict(slot_value)
            slot_value[layout.key_field] = slot_key_text
        slots[slot_key_text] = format_handler.serialize(slot_value)
    return slots, None


def apply_slot(
    shared_path: Path,
    layout: SharedKeyedMapLayout,
    slot_key: str,
    new_slot_text: str | None,
) -> str | None:
    """Read the shared file, insert / replace / delete ``slot_key`` under
    ``map_key_path``, write the merged file atomically. ``new_slot_text``
    is ``None`` for deletion. Returns the prior slot text (serialised
    via the registered format) or ``None`` if the slot did not previously
    exist. Sibling slots and out-of-map top-level keys are preserved.

    Concurrent-writer handling: re-reads the file just before writing.
    If the bytes changed during the merge, retries the merge once on the
    fresh contents; if a second race occurs, raises
    ``SharedKeyedMapRaceError`` so the caller can re-try next poll
    rather than corrupt the file.
    """
    format_handler = get_format(layout.file_format)

    for attempt in (1, 2):
        before_text = (
            shared_path.read_text(encoding="utf-8")
            if shared_path.exists() else ""
        )
        root = format_handler.deserialize(before_text) if before_text.strip() else {}
        node = _navigate_or_create(root, layout.map_key_path)
        prior_value = node.get(slot_key)
        prior_text = (
            format_handler.serialize(prior_value) if prior_value is not None else None
        )
        if new_slot_text is None:
            node.pop(slot_key, None)
        else:
            node[slot_key] = format_handler.deserialize(new_slot_text)
        merged_text = format_handler.serialize(root)

        # Re-read just before write to detect a concurrent writer.
        latest_text = (
            shared_path.read_text(encoding="utf-8")
            if shared_path.exists() else ""
        )
        if latest_text == before_text:
            shared_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(shared_path, merged_text)
            return prior_text

        logging.warning(
            "Shared keyed-map file changed mid-merge: path=%s attempt=%d",
            shared_path, attempt,
        )

    raise SharedKeyedMapRaceError(
        f"Concurrent writer kept racing the merge of {shared_path}; "
        f"slot {slot_key!r} was not written this poll."
    )


def serialize_slot(value: Any, layout: SharedKeyedMapLayout) -> str:
    """Serialise one slot value to text. Used so the canonical parser
    sees a fresh slot the same way it sees a slot read off disk."""
    return get_format(layout.file_format).serialize(value)


def _navigate_or_create(
    root: MutableMapping[str, Any],
    map_key_path: tuple[str, ...],
) -> MutableMapping[str, Any]:
    node: Any = root
    for key in map_key_path:
        if key not in node or not isinstance(node[key], dict):
            node[key] = {}
        node = node[key]
    return node


class SharedKeyedMapRaceError(RuntimeError):
    """Raised when the shared file is rewritten by another process while
    ``apply_slot`` is computing the merged contents."""
