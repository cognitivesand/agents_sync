"""Shared vocabulary for the customization-library export and import (US-12).

The constants name the zip's wire layout (the manifest path, the canonical-entry
prefix, the manifest schema version); ``PortableLibraryError`` is the one structured
failure both halves raise (NFR-13); ``read_canonical_document`` is the lenient,
non-mutating parse both use to inspect a store/export envelope's bytes — it never
quarantines, so the read-only export and the pre-write import validation stay safe.
"""

from __future__ import annotations

import json

from agents_sync.domain_model.canonical_document import CanonicalDocument

PORTABLE_LIBRARY_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
CANONICAL_PREFIX = "canonical/"


class PortableLibraryError(ValueError):
    """A library export/import could not be completed (e.g. the path is not writable)."""


def read_canonical_document(raw: bytes) -> CanonicalDocument | None:
    """Parse a store/export envelope's bytes into a document; ``None`` if it will not
    parse. Non-mutating — corruption handling is never this path's concern."""
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return CanonicalDocument.from_dict(data)
    except (TypeError, ValueError):
        return None
