"""Hard caps on parser input size and YAML alias expansion.

Phase 3 of the v0.5 security hardening plan (audit findings SEC-C-01 +
SEC-C-02): the long-running daemon must not be DoS'd by either an
oversized input file or a pathological YAML alias graph. Every parser
entry point validates ``len(text) <= MAX_PARSE_BYTES`` (UTF-8 byte
budget enforced at file-read time as a stat() check, or at parse time
as a ``len(str)`` check) before handing the buffer to ruamel/json/tomllib.
The YAML loader threads a :class:`BoundedComposer` that counts alias
resolutions and aborts at :data:`MAX_YAML_ALIAS_RESOLUTIONS`.

All bounds raise :class:`ParserBoundsExceeded`, a subclass of
:class:`AdapterParseError`, so existing callers (discovery walker's
broad ``except Exception``, quarantine path in ``load_canonical`` /
``load_state``, ``SyncResult.failed`` recording in ``Syncer.sync_once``)
handle the new exception type without code changes.

The bounds are deliberately constants rather than configurable values.
Legitimate inputs fit comfortably within them:

  - 16 MB per parsed file. A user's combined Claude / Codex / OpenCode
    MCP server configs are typically a few KB each.
  - 256 KB per Markdown frontmatter block. SKILL.md / agent.md
    frontmatter is rarely more than a few hundred bytes.
  - 10 000 YAML alias resolutions per document. Defends against the
    quadratic billion-laughs variant that ruamel's round-trip loader
    does not natively guard against; legitimate frontmatter has
    essentially no anchors.

If a real user input ever brushes one of these caps, raise the bound
in a follow-up PR; don't make it configurable. See plan Decision D3.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agents_sync.markdown_yaml_metadata_block import AdapterParseError

MAX_PARSE_BYTES: int = 16 * 1024 * 1024
"""Per-file parse-input ceiling in bytes (16 MB).

Applied at every parser entry point (JSON / TOML / shared keyed-map /
canonical store / state.json / MCP slot codec). The cap is on the UTF-8
character count of the text handed to the parser — a 16 MB binary blob
that happens to round-trip through UTF-8 will be rejected before
``json.loads`` / ``tomllib.loads`` allocates the parse tree.
"""

MAX_FRONTMATTER_BYTES: int = 256 * 1024
"""Markdown frontmatter ceiling in bytes (256 KB).

Bounds the linear scan of :data:`markdown_yaml_metadata_block.FRONTMATTER_RE`
against the leading slice of the document. A frontmatter block above
this size is malformed by every adapter's contract.
"""

MAX_YAML_ALIAS_RESOLUTIONS: int = 10_000
"""Cap on the number of YAML node compositions performed for a single
document. Defeats quadratic billion-laughs YAML even though
``ruamel.yaml`` 's round-trip loader is RCE-safe (it resolves anchors
and aliases by reference, not by exponential expansion). A document
that legitimately needs more than ~10 000 node resolutions is in itself
unusual; raise this constant if real-world frontmatter ever needs it.
"""


class ParserBoundsExceeded(AdapterParseError):
    """A parser input exceeded one of the bounds in this module."""


def enforce_text_bound(
    text: str, *, label: str, limit: int = MAX_PARSE_BYTES,
) -> str:
    """Return ``text`` unchanged if within bounds; raise otherwise.

    ``label`` is the human-readable name of the input (e.g. file path,
    "<state.json>", "<mcp_server slot>"). It is included in the error
    message so the operator can find the offending input quickly.
    """
    n = len(text)
    if n > limit:
        raise ParserBoundsExceeded(
            f"{label}: input size {n} bytes exceeds MAX_PARSE_BYTES ({limit} bytes)",
        )
    return text


def read_text_bounded(
    path: Path,
    *,
    label: str | None = None,
    limit: int = MAX_PARSE_BYTES,
    encoding: str = "utf-8",
) -> str:
    """Read ``path`` as text, rejecting files larger than ``limit`` bytes.

    Uses ``path.stat().st_size`` BEFORE reading, so a 2 GB hostile file
    never lands in memory. The on-disk size is a strict upper bound on
    the in-memory text length (UTF-8 is at most 4 bytes per code point),
    so the stat check is sufficient.
    """
    effective_label = label if label is not None else str(path)
    size = path.stat().st_size
    if size > limit:
        raise ParserBoundsExceeded(
            f"{effective_label}: file size {size} bytes exceeds MAX_PARSE_BYTES "
            f"({limit} bytes)",
        )
    return path.read_text(encoding=encoding)


def enforce_frontmatter_window(text: str) -> str:
    """Return the leading slice of ``text`` that the frontmatter scanner
    is allowed to examine. Documents whose body is larger than the cap
    still parse — the frontmatter scanner just doesn't get to see past
    the first :data:`MAX_FRONTMATTER_BYTES` characters, which is far
    more than any legitimate frontmatter occupies.
    """
    if len(text) <= MAX_FRONTMATTER_BYTES:
        return text
    return text[:MAX_FRONTMATTER_BYTES]


def make_bounded_composer_class() -> Any:
    """Return a ``BoundedComposer`` subclass of ruamel's round-trip composer.

    Constructed lazily so ``parser_bounds`` does not pay the
    ``ruamel.yaml`` import at module load time (relevant for callers
    that never touch YAML).
    """
    from ruamel.yaml.composer import Composer

    class BoundedComposer(Composer):
        """Counts node compositions; raises after the configured cap."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._composed_nodes = 0

        def compose_node(self, parent: Any, index: Any) -> Any:  # noqa: ANN401
            self._composed_nodes += 1
            if self._composed_nodes > MAX_YAML_ALIAS_RESOLUTIONS:
                raise ParserBoundsExceeded(
                    "YAML document exceeds MAX_YAML_ALIAS_RESOLUTIONS "
                    f"({MAX_YAML_ALIAS_RESOLUTIONS}) node compositions — "
                    "rejecting as potential alias/anchor bomb",
                )
            return super().compose_node(parent, index)

    return BoundedComposer


__all__ = [
    "MAX_FRONTMATTER_BYTES",
    "MAX_PARSE_BYTES",
    "MAX_YAML_ALIAS_RESOLUTIONS",
    "ParserBoundsExceeded",
    "enforce_frontmatter_window",
    "enforce_text_bound",
    "make_bounded_composer_class",
    "read_text_bounded",
]
