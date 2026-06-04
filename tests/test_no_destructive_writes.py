"""Architecture invariant I-3 (backs NFR-01): the use-case layer never performs
a destructive filesystem mutation directly.

Every overwrite or delete in the system must go through a sanctioned gateway —
``archive.py`` (archive-before-write / archive-before-delete) and the projection
gateway ``rendering.py`` — so that no user-authored content can be lost. The
use-case modules (the per-poll orchestrator, discovery, and adoption) must
therefore contain *no* raw destructive primitive of their own.

This is the cheap static complement to the integration tests that exercise
NFR-01 dynamically (see docs/architecture.md §8 "I-3" and §11 "D-6"). It walks
the AST of each use-case module and fails fast the moment a destructive call is
introduced into that layer without routing through a gateway.

A genuinely-unavoidable exception may opt out with an inline ``# noqa: I-3``
marker on the call's line; such markers are intended to be rare and reviewed.
"""
from __future__ import annotations

import ast
from pathlib import Path

import agents_sync

# Path-bound methods that destroy or overwrite content. These names are
# unambiguous in this codebase (they are not common non-filesystem methods),
# so matching by attribute name alone is safe.
_DESTRUCTIVE_METHODS = frozenset(
    {"write_text", "write_bytes", "unlink", "rename", "rmdir"}
)

# Module-qualified destructive calls. ``replace``/``remove`` are matched ONLY
# when qualified by ``os``/``shutil`` so that string ``.replace(...)`` and
# list ``.remove(...)`` never trip the guard.
_DESTRUCTIVE_QUALIFIED = frozenset(
    {
        ("os", "replace"),
        ("os", "remove"),
        ("os", "rename"),
        ("os", "unlink"),
        ("shutil", "move"),
        ("shutil", "rmtree"),
    }
)

# The use-case layer (Layer 2): must delegate all mutation to the gateways.
# rendering.py, archive.py, state.py and the canonical store are the sanctioned
# gateways and are intentionally NOT scanned here.
_USE_CASE_MODULES = (
    "sync.py",
    "adoption/engine.py",
    "adoption/canonical_projection.py",
    "adoption/removal_propagator.py",
    "adoption/privacy_gate.py",
    "discovery/walker.py",
    "discovery/enumerator.py",
    "discovery/adoption_planner.py",
    "discovery/collision_blocker.py",
)

_ALLOW_MARKER = "noqa: I-3"


def _source_root() -> Path:
    return Path(agents_sync.__file__).parent


def _is_destructive(call: ast.Call) -> str | None:
    """Return the offending attribute name if this call is destructive, else None."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return None
    attr = func.attr
    if attr in _DESTRUCTIVE_METHODS:
        return attr
    if isinstance(func.value, ast.Name) and (func.value.id, attr) in _DESTRUCTIVE_QUALIFIED:
        return f"{func.value.id}.{attr}"
    return None


def test_use_case_layer_has_no_raw_destructive_writes() -> None:
    root = _source_root()
    violations: list[str] = []

    for rel in _USE_CASE_MODULES:
        path = root / rel
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            attr = _is_destructive(node)
            if attr is None:
                continue
            if _ALLOW_MARKER in lines[node.lineno - 1]:
                continue
            violations.append(f"{rel}:{node.lineno}  {attr}(...)")

    assert not violations, (
        "I-3 violation — use-case modules must route every filesystem mutation "
        "through the archive.py / rendering.py gateways and never call a raw "
        "destructive primitive directly. Offending calls:\n  "
        + "\n  ".join(violations)
    )


def test_scanned_modules_all_exist() -> None:
    # Guard the guard: if a use-case module is renamed/moved, this list must be
    # updated rather than silently scanning nothing (which would pass vacuously).
    root = _source_root()
    missing = [rel for rel in _USE_CASE_MODULES if not (root / rel).is_file()]
    assert not missing, f"_USE_CASE_MODULES is stale; not found: {missing}"
