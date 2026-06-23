"""``sync_once`` — the read→plan→execute orchestration for one poll (S22b).

One cycle: build the read-phase specs from the resolved paths, observe every tool
surface (reusing the previous poll's digest cache, NFR-08), load the stored
canonicals, compute the pure ``SyncPlan``, execute it (the executor persists
canonicals), then persist the updated ``SyncState``. ``sync_once`` derives the
two-tool destructive guard's ``available_tool_count`` internally from
``resolved_paths`` + ``tool_definitions`` via ``count_available_tools`` (a tool is
available when at least one of its resolved roots exists — the new-model definition
the S24 conformance cutover validates), so the safety count is a single source of
truth that cannot desync from the paths it summarizes. ``poll_daemon`` drives this
through ``make_periodic_poll`` (the CLI wires it at S22c).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from agents_sync.canonical_store import list_canonical_ids, load_canonical
from agents_sync.domain_model.canonical_document import CanonicalDocument, CorruptCanonical
from agents_sync.domain_model.observation import SurfaceObservation
from agents_sync.domain_model.plan.compute_sync_plan import compute_sync_plan
from agents_sync.domain_model.sync_plan import SyncResult
from agents_sync.domain_model.sync_state import SurfaceLocation, SyncState
from agents_sync.execute_sync_plan import execute_sync_plan
from agents_sync.read_tool_surfaces import PreviousObservations, SurfaceSpec, read_tool_surfaces
from agents_sync.runtime_config import RuntimeConfig
from agents_sync.secret_policy import SECRET_POLICY_REFUSED
from agents_sync.sync_state_store import load_sync_state, save_sync_state
from agents_sync.tools.agentic_tools_registry import ALL_TOOL_DEFINITIONS, surface_specs_for
from agents_sync.tools.tool_definition import ToolDefinition

_StoredCanonical = CanonicalDocument | CorruptCanonical


def count_available_tools(
    resolved_paths: Mapping[str, Path],
    tool_definitions: Iterable[ToolDefinition],
) -> int:
    """How many tools are available this poll: a tool is available when at least
    one of its resolved surface roots exists on disk (US-07 AC-5 / US-11). The
    two-tool destructive guard reads this count. (New-model definition; the S24
    conformance cutover validates it against the two-tool-guard suite.)"""
    available = 0
    for definition in tool_definitions:
        roots = [
            resolved_paths[recipe.config_key]
            for recipe in definition.surface_recipes
            if recipe.config_key in resolved_paths
        ]
        if any(root.exists() for root in roots):
            available += 1
    return available


def sync_once(
    state_dir: Path,
    resolved_paths: Mapping[str, Path],
    sync_state: SyncState,
    previous_observations: PreviousObservations,
    *,
    tool_definitions: Iterable[ToolDefinition],
    secret_policy: str = SECRET_POLICY_REFUSED,
) -> tuple[SyncResult, dict[SurfaceLocation, SurfaceObservation], SyncState]:
    """Perform one poll (read → plan → execute) and persist the new state.

    Returns the poll result, the fresh observations (the next poll's digest cache),
    and the updated state (the next poll's input). The executor persists canonicals;
    this function persists the ``SyncState``. The two-tool destructive guard's
    ``available_tool_count`` is derived here from ``resolved_paths`` +
    ``tool_definitions`` via ``count_available_tools`` — the single source of truth,
    so the safety count cannot desync from the paths it summarizes (US-07 AC-5)."""
    definitions = tuple(tool_definitions)
    specs = _surface_specs(resolved_paths, definitions)
    observations = read_tool_surfaces(specs, previous_observations)
    stored = _load_stored_canonicals(state_dir, sync_state)
    available_tool_count = count_available_tools(resolved_paths, definitions)
    plan = compute_sync_plan(observations, sync_state, stored, available_tool_count)
    result, new_state = execute_sync_plan(
        plan, observations, sync_state, state_dir, secret_policy_value=secret_policy
    )
    # The two persistence steps (executor canonicals above, SyncState below) are
    # intentionally not one transaction: canonicals are content-addressed and the
    # planner re-reads state each poll, so if save_sync_state raises after the
    # executor committed, the store is briefly ahead of recorded state but the next
    # poll re-derives safely with no content loss (FR-14 / NFR-04 / US-07 AC-4).
    save_sync_state(state_dir, new_state)
    fresh = {observation.tool_surface.location: observation for observation in observations}
    return result, fresh, new_state


def make_periodic_poll(
    config: RuntimeConfig,
    tool_definitions: Iterable[ToolDefinition] = ALL_TOOL_DEFINITIONS,
) -> Callable[[], SyncResult]:
    """Adapt ``sync_once`` to the ``() -> SyncResult`` the poll loop calls, threading
    the state and digest cache across polls (NFR-08). State is loaded once here;
    each poll feeds the prior poll's state and observations back in."""
    state_dir = config.state_path.parent
    definitions = tuple(tool_definitions)
    state = load_sync_state(state_dir)
    observations: dict[SurfaceLocation, SurfaceObservation] = {}

    def poll() -> SyncResult:
        nonlocal state, observations
        result, observations, state = sync_once(
            state_dir,
            config.resolved_paths,
            state,
            observations,
            secret_policy=config.secret_policy,
            tool_definitions=definitions,
        )
        return result

    return poll


def _surface_specs(
    resolved_paths: Mapping[str, Path], tool_definitions: Iterable[ToolDefinition]
) -> tuple[SurfaceSpec, ...]:
    specs: list[SurfaceSpec] = []
    for definition in tool_definitions:
        specs.extend(surface_specs_for(definition, resolved_paths))
    return tuple(specs)


def _load_stored_canonicals(
    state_dir: Path, sync_state: SyncState
) -> dict[str, _StoredCanonical | None]:
    stored: dict[str, _StoredCanonical | None] = {
        artifact_id: load_canonical(state_dir, artifact_id)
        for artifact_id in list_canonical_ids(state_dir)
    }
    for artifact_id in sync_state.records:
        stored.setdefault(artifact_id, None)
    return stored
