"""Read / write primitives for ``SharedKeyedMapLayout`` files.

The layout class declares storage shape; this module is the IO contract.
Three operations:

- ``read_slots(shared_path, layout)`` — return ``{slot_key: slot_text}`` for
  every entry under ``map_key_path``. Missing file or missing map_key_path
  is reported as ``({}, missing_reason)`` rather than raising; the caller
  decides whether to log.
- ``apply_slot(shared_path, layout, slot_key, new_slot_text)`` — read the
  shared file, replace / insert / delete the slot under ``map_key_path``,
  serialise the merged mapping, and atomically write it back under a
  cross-process file lock so concurrent writers serialise instead of
  racing. Returns the prior slot text (or ``None``) so the caller can
  archive it. The shared file is never partially overwritten.
- ``serialize_slot(value, layout)`` — serialise one slot value (the parsed
  Python object for a single slot) to text. Used to feed the canonical
  parser, which expects ``text``.

Concurrency contract: ``apply_slot`` acquires an exclusive lock on
``<shared_path>.lock`` (via :mod:`agents_sync.filesystem_lock`) before
its read-modify-write sequence. Two daemons (or a daemon and a hand
``$EDITOR``) hitting the same shared file therefore serialise; neither
clobbers the other. The lock is released on every exit path, including
exceptions.
"""
from __future__ import annotations

import logging
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from agents_sync.agentic_tool_spec import SharedKeyedMapLayout
from agents_sync.filesystem_lock import LockTimeoutError, lock_file
from agents_sync.parser_bounds import read_text_bounded
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
    text = read_text_bounded(shared_path)
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
        if isinstance(slot_value, dict):
            if layout.key_field not in slot_value:
                slot_value = dict(slot_value)
                slot_value[layout.key_field] = slot_key_text
            elif slot_value[layout.key_field] != slot_key_text:
                raise ValueError(
                    "shared keyed-map slot key conflict: "
                    f"path={shared_path} slot={slot_key_text!r} "
                    f"{layout.key_field}={slot_value[layout.key_field]!r}"
                )
        slots[slot_key_text] = format_handler.serialize(slot_value)
    return slots, None


def apply_slot(
    shared_path: Path,
    layout: SharedKeyedMapLayout,
    slot_key: str,
    new_slot_text: str | None,
    *,
    expected_pair_id: str | None = None,
    allow_unpaired_existing: bool = False,
) -> str | None:
    """Read the shared file, insert / replace / delete ``slot_key`` under
    ``map_key_path``, write the merged file atomically. ``new_slot_text``
    is ``None`` for deletion. Returns the prior slot text (serialised
    via the registered format) or ``None`` if the slot did not previously
    exist. Sibling slots and out-of-map top-level keys are preserved.

    If ``expected_pair_id`` is provided and the slot already exists,
    the existing slot must either carry that pair_id or, when
    ``allow_unpaired_existing`` is true, carry no pair_id. This is a
    defense-in-depth guard against overwriting a slot owned by another
    managed pair.

    Concurrent-writer handling: the read-modify-write runs inside an
    exclusive cross-process lock on ``<shared_path>.lock``. Two writers
    therefore serialise; the shared file is never partially overwritten.
    If the lock cannot be acquired within the configured timeout (a
    user's editor holding the file open for many seconds), raises
    :class:`SharedKeyedMapRaceError` so the caller retries next poll.
    """
    format_handler = get_format(layout.file_format)
    shared_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with lock_file(shared_path):
            root, node = _read_root_and_node(
                shared_path, layout, format_handler,
            )
            prior_value = node.get(slot_key)
            prior_text = (
                format_handler.serialize(prior_value)
                if prior_value is not None else None
            )
            if expected_pair_id is not None and slot_key in node:
                _assert_slot_pair_id_matches(
                    shared_path,
                    slot_key,
                    prior_value,
                    expected_pair_id=expected_pair_id,
                    allow_unpaired_existing=allow_unpaired_existing,
                )
            if new_slot_text is None:
                node.pop(slot_key, None)
            else:
                node[slot_key] = format_handler.deserialize(new_slot_text)
            atomic_write_text(shared_path, format_handler.serialize(root))
            return prior_text
    except LockTimeoutError as exc:
        logging.warning(
            "Could not lock shared keyed-map file in time: path=%s slot=%s (%s)",
            shared_path, slot_key, exc,
        )
        raise SharedKeyedMapRaceError(
            f"Could not acquire lock on {shared_path} for slot {slot_key!r}; "
            "another writer is holding it. Will retry next poll."
        ) from exc


def _read_root_and_node(
    shared_path: Path,
    layout: SharedKeyedMapLayout,
    format_handler: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the shared file (if any), deserialize to a root mapping, and
    return ``(root, node)`` where ``node`` is the inner map at
    ``layout.map_key_path`` ready for slot insertion / deletion."""
    before_text = (
        read_text_bounded(shared_path)
        if shared_path.exists() else ""
    )
    root = (
        format_handler.deserialize(before_text)
        if before_text.strip() else {}
    )
    node = _navigate_or_create(root, layout.map_key_path)
    return root, node


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
        if not isinstance(node, MutableMapping):
            raise ValueError(
                "shared keyed-map path segment is not an object: "
                f"segment={key!r} path={map_key_path!r}"
            )
        if key not in node:
            node[key] = {}
        elif not isinstance(node[key], MutableMapping):
            raise ValueError(
                "shared keyed-map path segment is not an object: "
                f"segment={key!r} path={map_key_path!r}"
            )
        node = node[key]
    return node


class SharedKeyedMapRaceError(RuntimeError):
    """Raised when the shared file is rewritten by another process while
    ``apply_slot`` is computing the merged contents."""


class SharedKeyedMapSlotCollisionError(RuntimeError):
    """Raised when a slot is already occupied by another pair_id."""


def _assert_slot_pair_id_matches(
    shared_path: Path,
    slot_key: str,
    prior_value: Any,
    *,
    expected_pair_id: str,
    allow_unpaired_existing: bool,
) -> None:
    if not isinstance(prior_value, dict):
        if allow_unpaired_existing:
            return
        raise SharedKeyedMapSlotCollisionError(
            "shared keyed-map slot collision: "
            f"path={shared_path} slot={slot_key!r} "
            f"expected_pair_id={expected_pair_id!r} existing_pair_id=None"
        )
    if "pair_id" not in prior_value:
        if allow_unpaired_existing:
            return
        raise SharedKeyedMapSlotCollisionError(
            "shared keyed-map slot collision: "
            f"path={shared_path} slot={slot_key!r} "
            f"expected_pair_id={expected_pair_id!r} existing_pair_id=None"
        )
    existing_pair_id = prior_value["pair_id"]
    if existing_pair_id == expected_pair_id:
        return
    raise SharedKeyedMapSlotCollisionError(
        "shared keyed-map slot collision: "
        f"path={shared_path} slot={slot_key!r} "
        f"expected_pair_id={expected_pair_id!r} "
        f"existing_pair_id={existing_pair_id!r}"
    )
