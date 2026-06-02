"""Pre-process collision blocking for adoption targets.

After per-pair processing has had a chance to assign new pair_ids,
:meth:`DiscoveryWalker.block_target_collisions` plans the adoption
target for every not-yet-managed pair and vetoes any pair whose target
would clobber:

- another managed pair's owned path / slot,
- an existing unmanaged path / slot on disk,
- another not-yet-managed pair's planned target.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agents_sync.agentic_tool_spec import SharedKeyedMapLayout
from agents_sync.rendering import slot_aware_collision_key
from agents_sync.shared_keyed_map_io import read_slots
from agents_sync.state import CustomizationArtifactState
from agents_sync.sync_types import (
    CustomizationArtifactInfo,
    PlannedTarget,
)

if TYPE_CHECKING:
    from agents_sync.discovery._host import _WalkerHost

    _WalkerHostBase = _WalkerHost
else:
    _WalkerHostBase = object


def _target_already_exists(target: PlannedTarget) -> bool:
    """Whether a planned target collides with an existing on-disk entry.

    For per-file targets, existence is filesystem existence. For
    shared-keyed-map targets, the shared file may exist (it is shared
    with other entries) — the collision question is whether the slot
    key is already populated under the configured ``map_key_path``.
    This helper covers unmanaged occupants; managed occupants are found
    by ``state_owner_for_path`` before this is called.
    """
    if target.slot is None:
        return target.path.exists()
    if not isinstance(target.file_layout, SharedKeyedMapLayout):
        return False
    try:
        slots, absent_reason = read_slots(target.path, target.file_layout)
    except Exception:
        logging.exception(
            "Cannot inspect shared keyed-map target: path=%s slot=%s",
            target.path, target.slot,
        )
        return True
    if absent_reason is not None:
        return False
    return target.slot in slots


class CollisionBlockerMixin(_WalkerHostBase):
    """Block pairs whose adoption targets collide. Relies on
    ``self.agentic_tools`` and the planner mixin's
    ``_planned_adoption_targets``."""

    def block_target_collisions(
        self,
        discovery: dict[str, CustomizationArtifactInfo],
        state: dict[str, CustomizationArtifactState],
    ) -> set[str]:
        """For each not-yet-managed pair, plan its adoption targets. Block any
        pair whose target collides with a managed pair's owned path, with an
        unmanaged path on disk, or with another pair's planned target.

        Mutates ``discovery`` (pops blocked entries) and returns the set of
        blocked pair_ids so the caller can fold them into the overall block.
        """
        targets: dict[tuple[str, str | None], list[str]] = {}
        target_display: dict[tuple[str, str | None], PlannedTarget] = {}
        blocked: set[str] = set()

        for pair_id, info in discovery.items():
            if pair_id in state:
                continue
            blocked_now = self._collect_targets_and_detect_collisions(
                pair_id, info, state, targets, target_display,
            )
            if blocked_now:
                blocked.add(pair_id)

        self._detect_multi_pair_collisions(targets, target_display, blocked)

        for pair_id in blocked:
            discovery.pop(pair_id, None)
        return blocked

    def _collect_targets_and_detect_collisions(
        self,
        pair_id: str,
        info: CustomizationArtifactInfo,
        state: dict[str, CustomizationArtifactState],
        targets: dict[tuple[str, str | None], list[str]],
        target_display: dict[tuple[str, str | None], PlannedTarget],
    ) -> bool:
        """Plan one pair's targets and detect managed/unmanaged collisions.

        Returns True if the pair must be blocked. Side-effect: updates
        ``targets`` / ``target_display`` for later multi-pair detection.
        """
        try:
            planned_targets = self._planned_adoption_targets(info)
        except Exception:
            logging.exception("Cannot plan adoption target: pair_id=%s", pair_id)
            return True

        blocked = False
        for target in planned_targets:
            target_key = slot_aware_collision_key(target.path, target.slot)
            targets.setdefault(target_key, []).append(pair_id)
            target_display.setdefault(target_key, target)

            owner = self.state_owner_for_path(
                target.path, state, slot=target.slot,
            )
            if owner is not None and owner != pair_id:
                logging.error(
                    "Target collision with managed pair: "
                    "pair_id=%s owner_pair_id=%s target=%s slot=%s",
                    pair_id, owner, target.path, target.slot,
                )
                blocked = True
            elif owner is None and _target_already_exists(target):
                if target.slot is None:
                    logging.error(
                        "Target collision with unmanaged entry: "
                        "pair_id=%s target=%s slot=%s",
                        pair_id, target.path, target.slot,
                    )
                else:
                    logging.error(
                        "Keyed-map slot collision with unmanaged entry: "
                        "pair_id=%s target=%s slot=%s",
                        pair_id, target.path, target.slot,
                    )
                blocked = True
        return blocked

    def _detect_multi_pair_collisions(
        self,
        targets: dict[tuple[str, str | None], list[str]],
        target_display: dict[tuple[str, str | None], PlannedTarget],
        blocked: set[str],
    ) -> None:
        for target_key, pair_ids in targets.items():
            if len(pair_ids) <= 1:
                continue
            display = target_display[target_key]
            logging.error(
                "Target collision: target=%s slot=%s pair_ids=%s",
                display.path, display.slot, pair_ids,
            )
            blocked.update(pair_ids)
