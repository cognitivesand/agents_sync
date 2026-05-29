"""Meta-test: every test module in the integration-class layer carries
``pytestmark = pytest.mark.integration``.

Audit slice 10 · TQ-01 (2026-05-22) found that the ``slow`` / ``integration``
markers were registered in ``pyproject.toml`` but applied to zero modules —
``pytest -m 'not integration'`` deselected nothing, even though the
fast/full pytest split policy in CLAUDE.md §7.1 mandates that split.
Phase 4 of the v0.5 security hardening plan landed the markers; this
test makes the discipline self-policing so a future integration-class
module added without a marker fails CI rather than silently re-eroding
the policy.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_INTEGRATION_MODULES: frozenset[str] = frozenset({
    "test_e2e_sync.py",
    "test_first_boot_reconciliation.py",
    "test_v0_4_1_matrix.py",
    "test_migrate_v0_4_e2e.py",
    "test_mcp_real_adapters.py",
    "test_rules_real_adapters.py",
    "test_slash_command_real_adapters.py",
    "test_shared_keyed_map_discovery.py",
    "test_shared_keyed_map_render.py",
    "test_antigravity_three_way.py",
    "test_mcp_server_sync.py",
    "test_rules_sync.py",
    "test_slash_command_sync.py",
    "test_portable_archive.py",
    "test_portable_archive_secret_egress.py",
})


def _module_has_integration_pytestmark(path: Path) -> bool:
    """Parse ``path`` as a Python module and look for ``pytestmark =
    pytest.mark.integration`` at module scope. Accepts both the bare
    attribute form and the equivalent ``pytest.mark.integration(...)``
    call form.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t for t in node.targets if isinstance(t, ast.Name)]
        if not any(t.id == "pytestmark" for t in targets):
            continue
        # Accept either ``pytest.mark.integration`` (an attribute access)
        # or ``pytest.mark.integration()`` (a call); both produce the
        # same MarkDecorator.
        value = node.value
        if isinstance(value, ast.Call):
            value = value.func
        if not isinstance(value, ast.Attribute):
            continue
        if value.attr != "integration":
            continue
        inner = value.value
        if not isinstance(inner, ast.Attribute):
            continue
        if inner.attr != "mark":
            continue
        return True
    return False


@pytest.mark.parametrize("module_name", sorted(_INTEGRATION_MODULES))
def test_integration_module_carries_marker(module_name: str) -> None:
    tests_dir = Path(__file__).parent
    path = tests_dir / module_name
    assert path.exists(), (
        f"{module_name} listed in the integration-module guard but the file "
        f"is missing — update _INTEGRATION_MODULES if the test was renamed."
    )
    assert _module_has_integration_pytestmark(path), (
        f"{module_name} is registered as integration-class but does not "
        "carry ``pytestmark = pytest.mark.integration`` at module scope. "
        "Either add the marker (right after ``import pytest``) or drop "
        "the module from ``_INTEGRATION_MODULES`` in this file if the "
        "module is genuinely unit-scoped."
    )
