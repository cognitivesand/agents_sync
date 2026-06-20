"""Customization library export and import — one transportable snapshot (US-12).

The export and import halves live in ``_export`` / ``_import`` (split to respect the
module-size limit, like ``dialects/mcp_server``); this package re-exports their
public surface so callers and the CLI import from ``agents_sync.portable_library``
directly.
"""

from agents_sync.portable_library._export import (
    ExportEnvironment,
    ExportReport,
    export_library,
)
from agents_sync.portable_library._import import ImportReport, import_library
from agents_sync.portable_library._shared import (
    CANONICAL_PREFIX,
    MANIFEST_NAME,
    PORTABLE_LIBRARY_SCHEMA_VERSION,
    PortableLibraryError,
)

__all__ = [
    "CANONICAL_PREFIX",
    "MANIFEST_NAME",
    "PORTABLE_LIBRARY_SCHEMA_VERSION",
    "ExportEnvironment",
    "ExportReport",
    "ImportReport",
    "PortableLibraryError",
    "export_library",
    "import_library",
]
