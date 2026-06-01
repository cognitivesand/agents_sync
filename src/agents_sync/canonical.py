"""Canonical JSON document — the lossless intermediate per pair.

Each managed pair has one canonical document at:
  <state_dir>/canonical/<pair_id>.json

Both renderers project from it; in Phase 3 both parsers will fold side
changes back into it. For Phase 2 (one-way) only the Claude parser is
wired through.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from agents_sync.identity import InvalidPairId, validate_pair_id
from agents_sync.parser_bounds import ParserBoundsExceeded, read_text_bounded
from agents_sync.state import _quarantine_corrupt, atomic_write_text

SCHEMA_VERSION = 2


def new_pair_id() -> str:
    return str(uuid.uuid4())


def empty_canonical(kind: str, pair_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "pair_id": pair_id or new_pair_id(),
        "kind": kind,
        "name": "",
        "description": "",
        "body": "",
        "model": None,
        "effort": None,
        "tools": [],
        "disallowed_tools": [],
        "permission_mode": None,
        "provenance": "user",
        "private": False,
        "per_agentic_tool_only": {},
        "per_agentic_tool_extra": {},
    }


def is_private(canonical: dict[str, Any]) -> bool:
    return bool(canonical.get("private", False))


# Canonical fields whose ordering is semantically irrelevant — sorted to
# guarantee that two adapters producing the same set of values (in any
# order) hash identically (audit slice 06 · CQ-01).
_ORDER_INSENSITIVE_LIST_FIELDS: tuple[str, ...] = (
    "tools",
    "disallowed_tools",
)


def canonicalize(canonical: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied, normalised view of ``canonical``.

    The point of this module is to be the lossless intermediate per pair,
    but the JSON we persist used to depend on the call order of every
    parser (list ordering, ``None`` vs missing key, trailing whitespace,
    CRLF vs LF). Two semantically-equal canonicals from two adapters
    could therefore hash to different SHA-256s, causing the engine to
    rewrite identical bytes every poll. ``canonicalize`` collapses those
    irrelevant differences:

    - ``tools`` and ``disallowed_tools`` lists are sorted (set-equality
      semantics; adapter call order should not matter).
    - ``name`` / ``description`` strings are stripped of leading and
      trailing whitespace.
    - ``body`` line endings are normalised to ``\\n`` (CRLF/CR → LF) and
      trailing whitespace per line is preserved (markdown-relevant) but
      a single trailing newline is enforced (no trailing whitespace at
      EOF).
    - ``None`` values are kept for nullable fields (``model``, ``effort``,
      ``permission_mode``) — they are the documented signal for "field
      not set by user" and must not be elided to absent keys.

    Does *not* normalise ``per_agentic_tool_only`` / ``per_agentic_tool_extra``
    contents — those are opaque adapter-specific bags whose internal
    structure each adapter owns.

    Use :func:`canonical_equal` to compare two canonicals semantically;
    use :func:`save_canonical` to persist (which calls ``canonicalize``
    internally so the persisted bytes are stable).
    """
    import copy

    normalised = copy.deepcopy(canonical)

    for list_field in _ORDER_INSENSITIVE_LIST_FIELDS:
        value = normalised.get(list_field)
        if isinstance(value, list):
            try:
                normalised[list_field] = sorted(value)
            except TypeError:
                # Heterogeneous list (mix of str and dict) — leave order
                # alone but at least make the bytes deterministic by
                # converting elements to strings for the sort key.
                normalised[list_field] = sorted(value, key=str)

    for str_field in ("name", "description"):
        value = normalised.get(str_field)
        if isinstance(value, str):
            normalised[str_field] = value.strip()

    body = normalised.get("body")
    if isinstance(body, str):
        normalised["body"] = _normalise_body(body)

    return normalised


def _normalise_body(body: str) -> str:
    """Normalise line endings to LF and force a single trailing newline.

    Inline whitespace inside lines is preserved (Markdown indentation,
    code blocks). CR-only line endings are mapped to LF; CRLF to LF.
    """
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = text.rstrip("\n")
    return text + "\n" if text else ""


def canonical_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Return True if two canonicals are semantically equal.

    Equality is computed by ``canonicalize``-ing both sides and comparing
    by structural equality of the resulting dicts. Two canonicals that
    differ only in ``tools`` list order, body line endings, or
    ``description`` trailing whitespace compare equal.
    """
    return canonicalize(a) == canonicalize(b)


def canonical_content(canonical: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical content payload, excluding metadata.

    ``metadata`` carries sync/runtime facts such as ``last_modified`` and
    ``generation``. Those facts must travel with the canonical document, but
    they are not user content and must not affect content-change detection.
    """
    content = dict(canonical)
    content.pop("metadata", None)
    return content


def canonical_metadata(canonical: dict[str, Any]) -> dict[str, Any]:
    metadata = canonical.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def canonical_last_modified(canonical: dict[str, Any]) -> float | None:
    metadata = canonical_metadata(canonical)
    raw_last_modified = metadata.get("last_modified")
    if raw_last_modified is None:
        return None
    try:
        return float(raw_last_modified)
    except (TypeError, ValueError):
        return None


def set_canonical_metadata(
    canonical: dict[str, Any], *, last_modified: float, generation: int
) -> None:
    canonical["metadata"] = {
        "last_modified": float(last_modified),
        "generation": int(generation),
    }


def canonical_path(state_dir: Path, pair_id: str) -> Path:
    validate_pair_id(pair_id)
    return state_dir / "canonical" / f"{pair_id}.json"


def list_canonical_ids(state_dir: Path) -> list[str]:
    """Return the pair_ids of every canonical document in the store.

    Used by the daemon to adopt a canonical present in the store but not yet
    managed (FR-16) — a freshly imported canonical. Filenames whose stem is not a
    valid pair_id are skipped (defensive; canonical writes always use a valid id).
    """
    canonical_dir = state_dir / "canonical"
    if not canonical_dir.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(canonical_dir.glob("*.json")):
        try:
            validate_pair_id(path.stem)
        except InvalidPairId:
            continue
        ids.append(path.stem)
    return ids


def canonical_digest(canonical: dict[str, Any]) -> str:
    """Stable SHA-256 digest of canonical content (FR-14 change detection).

    Runtime metadata is excluded, so stamping ``last_modified`` / ``generation``
    does not look like a user-content edit.
    """
    payload = json.dumps(canonical_content(canonical), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_canonical(state_dir: Path, pair_id: str) -> dict[str, Any] | None:
    """Return the canonical dict for ``pair_id``, or ``None`` if absent.

    Corrupt canonicals (unparseable JSON, non-object root) are quarantined
    under ``state_dir/quarantine/`` before this returns ``None`` — distinguishing
    a partial-write recovery scenario from "never existed yet" by inspecting
    the quarantine directory. Callers may treat the ``None`` return as
    "treat as absent for this poll" without losing the corrupt bytes.
    """
    path = canonical_path(state_dir, pair_id)
    if not path.exists():
        return None
    try:
        text = read_text_bounded(path, label=f"canonical {pair_id}")
    except ParserBoundsExceeded:
        logging.exception("Canonical exceeds parser bounds: %s", path)
        _quarantine_corrupt(state_dir, path, reason="exceeds parser bounds")
        return None
    except (OSError, UnicodeDecodeError):
        logging.exception("Could not read canonical for %s: %s", pair_id, path)
        _quarantine_corrupt(state_dir, path, reason="unreadable bytes")
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        _quarantine_corrupt(state_dir, path, reason="JSON parse error")
        return None
    if not isinstance(data, dict):
        _quarantine_corrupt(state_dir, path, reason="root is not a JSON object")
        return None
    return data


def save_canonical(state_dir: Path, pair_id: str, canonical: dict[str, Any]) -> None:
    """Persist a canonical to disk, normalising it first.

    Normalisation guarantees byte-stable output: two adapters producing
    the same canonical (modulo list ordering / line endings) write
    identical files, so SHA-256 digests are stable across polls and the
    daemon doesn't churn writing identical bytes (audit slice 06 · CQ-01).
    """
    path = canonical_path(state_dir, pair_id)
    atomic_write_text(
        path,
        json.dumps(
            canonicalize(canonical),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
    )


def apply_per_tool_partition(
    canonical: dict[str, Any],
    *,
    agentic_tool_name: str,
    frontmatter_data: dict[str, Any],
    tool_only_fields: tuple[str, ...],
    known_fields: frozenset[str] | set[str],
) -> None:
    """Project ``frontmatter_data`` into ``per_agentic_tool_only`` and
    ``per_agentic_tool_extra`` under ``agentic_tool_name``.

    - ``tool_only_fields`` is the ordered set of frontmatter keys this
      adapter owns (rendered back into the tool's frontmatter on emit but
      excluded from the cross-tool canonical surface).
    - ``known_fields`` is the union of all keys this adapter knows about
      (canonical fields *plus* tool-only fields); any key not in this set
      lands in ``per_agentic_tool_extra`` so user-authored fields the
      project does not yet model are not silently dropped.

    Mutates ``canonical`` in place. Other agentic tools' entries are
    preserved untouched — only this adapter's slice is rewritten.

    This helper replaces three hand-rolled copies of the same eight-line
    pattern that previously lived in ``rules_io.py`` and
    ``slash_command_io.py`` (Phase 2.3 of the audit remediation).
    """
    per_only = dict(canonical.get("per_agentic_tool_only") or {})
    per_only[agentic_tool_name] = {
        field_name: frontmatter_data[field_name]
        for field_name in tool_only_fields
        if field_name in frontmatter_data
    }
    canonical["per_agentic_tool_only"] = per_only

    per_extra = dict(canonical.get("per_agentic_tool_extra") or {})
    per_extra[agentic_tool_name] = {
        key: value for key, value in frontmatter_data.items() if key not in known_fields
    }
    canonical["per_agentic_tool_extra"] = per_extra
