"""Rules ``@import`` inlining — read-side resolution of import directives (US-15).

A rules body line of the form ``@<relative-path>`` inlines the target file's text
(depth-first, in order) into the *effective* body the read phase propagates; the
user's directive-bearing source body stays on the origin surface. Imports resolve
only inside the rules root; an escaping target, a cycle, an unreadable target, or
nesting beyond the depth limit raises ``RulesImportError`` — malformed content the
read phase records as a ``ParseFailure`` (freeze, US-15). Lives outside
``dialects/`` because resolution reads the filesystem and dialects are pure.
"""

from __future__ import annotations

import re
from pathlib import Path

_IMPORT_LINE_PATTERN = re.compile(r"^\s*@(\S+)\s*$")
_MAX_IMPORT_DEPTH = 10


class RulesImportError(ValueError):
    """A rules ``@import`` directive cannot be resolved — malformed content."""


def inline_rules_imports(
    body: str,
    rules_root: Path,
    *,
    _seen_targets: frozenset[Path] = frozenset(),
    _depth: int = 0,
) -> tuple[str, bool]:
    """Inline ``@import`` directives; return ``(effective_body, had_import)``.

    Without a directive the body returns verbatim (no reformatting)."""
    if _depth > _MAX_IMPORT_DEPTH:  # the leading-underscore params are recursion plumbing
        raise RulesImportError("rules @import nesting exceeds maximum depth")
    root_resolved = rules_root.resolve()
    output_lines: list[str] = []
    had_import = False
    for line in body.splitlines():
        match = _IMPORT_LINE_PATTERN.match(line)
        if match is None:
            output_lines.append(line)
            continue
        had_import = True
        relative_target = match.group(1)
        target = (rules_root / relative_target).resolve()
        if target != root_resolved and root_resolved not in target.parents:
            raise RulesImportError(f"rules @import escapes the rules root: {relative_target}")
        if target in _seen_targets:
            raise RulesImportError(f"rules @import cycle detected: {relative_target}")
        try:
            imported_text = target.read_text(encoding="utf-8")
        except OSError as error:
            raise RulesImportError(f"rules @import target unreadable: {relative_target}") from error
        inlined, _ = inline_rules_imports(
            imported_text, rules_root, _seen_targets=_seen_targets | {target}, _depth=_depth + 1
        )
        output_lines.append(inlined)
    if not had_import:
        return body, False
    effective = "\n".join(output_lines)
    if body.endswith("\n"):
        effective += "\n"
    return effective, True
