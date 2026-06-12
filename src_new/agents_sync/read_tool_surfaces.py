"""Read phase — tool surfaces on disk to ``SurfaceObservation``s (FR-10/FR-11).

The one place the sync pipeline reads tool files: declarative surface specs
(directory, keyed-map, FR-10 rules-precedence — populated by tools-as-data at S20)
are turned into the observations the pure planner consumes. Each observation
carries the raw-text content digest, a fresh mtime, the id extracted in isolation
(never raises, FR-11), and a parse result — malformed content becomes a
``ParseFailure`` the planner routes to freeze; a recipe error stays a loud
``ValueError``. A surface whose digest matches its previous observation reuses the
prior parse (re-parse only changed; the daemon owns the cross-poll cache, S22).
A keyed-map file that no longer deserializes yields ``ParseFailure`` observations
for its previously-known slots — freeze, never removal propagation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from agents_sync.dialects import MalformedSurfaceError
from agents_sync.dialects.structured_text import deserialize
from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.observation import ParseFailure, SurfaceObservation
from agents_sync.domain_model.sync_state import SurfaceLocation
from agents_sync.domain_model.tool_surface import KeyedMapSlot, SurfaceFormat, ToolSurface
from agents_sync.rules_import_resolution import RulesImportError, inline_rules_imports
from agents_sync.translation import extract_artifact_id, file_to_canonical


@dataclass(frozen=True)
class DirectorySurfaceSpec:
    """Per-file artifacts: every ``filename_suffix`` file in ``directory`` is a surface."""

    tool: str
    kind: str
    directory: Path
    filename_suffix: str
    surface_format: SurfaceFormat


@dataclass(frozen=True)
class KeyedMapSurfaceSpec:
    """A shared keyed-map file: every slot under its key path is one surface."""

    tool: str
    kind: str
    file: Path
    surface_format: SurfaceFormat


@dataclass(frozen=True)
class RulesFileSurfaceSpec:
    """FR-10: the highest-precedence present filename is THE rules surface;
    a filename not on the declared list is never observed."""

    tool: str
    kind: str
    directory: Path
    candidate_filenames: tuple[str, ...]
    surface_format: SurfaceFormat


type SurfaceSpec = DirectorySurfaceSpec | KeyedMapSurfaceSpec | RulesFileSurfaceSpec
type PreviousObservations = Mapping[SurfaceLocation, SurfaceObservation]

_NO_HISTORY: PreviousObservations = {}


def read_tool_surfaces(
    surface_specs: tuple[SurfaceSpec, ...],
    previous_observations: PreviousObservations = _NO_HISTORY,
) -> tuple[SurfaceObservation, ...]:
    """Observe every declared surface this poll (the only read-side disk walk)."""
    observations: list[SurfaceObservation] = []
    for spec in surface_specs:
        if isinstance(spec, DirectorySurfaceSpec):
            observations.extend(_observe_directory(spec, previous_observations))
        elif isinstance(spec, KeyedMapSurfaceSpec):
            observations.extend(_observe_keyed_map(spec, previous_observations))
        else:
            observations.extend(_observe_rules_file(spec, previous_observations))
    return tuple(observations)


# --- per-file surfaces ----------------------------------------------------------------


def _observe_directory(
    spec: DirectorySurfaceSpec, previous: PreviousObservations
) -> list[SurfaceObservation]:
    if not spec.directory.is_dir():
        return []
    return [
        _observe_file(ToolSurface(spec.tool, spec.kind, path, spec.surface_format), previous)
        for path in sorted(spec.directory.iterdir())
        if path.is_file() and path.name.endswith(spec.filename_suffix)
    ]


def _observe_rules_file(
    spec: RulesFileSurfaceSpec, previous: PreviousObservations
) -> list[SurfaceObservation]:
    for filename in spec.candidate_filenames:  # ordered: first present wins (FR-10)
        path = spec.directory / filename
        if path.is_file():
            surface = ToolSurface(spec.tool, spec.kind, path, spec.surface_format)
            # No reuse cache for rules: imports must re-resolve every poll (an edit
            # behind the pointer is content), and there is at most one rules file
            # per tool, so the saving would be nil anyway.
            return [_resolve_rules_imports_in(_observe_file(surface, _NO_HISTORY), spec)]
    return []


def _resolve_rules_imports_in(
    observation: SurfaceObservation, spec: RulesFileSurfaceSpec
) -> SurfaceObservation:
    """Split the rules body into source and effective (US-15): ``@import`` directives
    inline into the effective body (what propagates); the user's directive-bearing
    source body is preserved for the origin tool under ``rules_source_body``.
    Imported content is content — it joins the digest, so an edit behind the
    pointer surfaces as a change. A bad import (escape/cycle/missing/too deep) is
    malformed content -> ``ParseFailure`` -> freeze."""
    parsed = observation.parsed
    if isinstance(parsed, ParseFailure):
        return observation
    try:
        effective_body, had_imports = inline_rules_imports(parsed.body, spec.directory)
    except RulesImportError as error:
        return replace(observation, parsed=ParseFailure(str(error)))
    if not had_imports:
        return observation
    tool_bags = {tool: dict(bag) for tool, bag in parsed.per_tool_only.items()}
    tool_bags.setdefault(spec.tool, {})["rules_source_body"] = parsed.body
    return replace(
        observation,
        content_digest=_text_digest(f"{observation.content_digest}\0{effective_body}"),
        parsed=replace(parsed, body=effective_body, per_tool_only=tool_bags),
    )


def _observe_file(tool_surface: ToolSurface, previous: PreviousObservations) -> SurfaceObservation:
    location = tool_surface.location
    assert isinstance(location, Path)
    modified_time = _modified_time(location)
    try:
        text = location.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return SurfaceObservation(
            tool_surface=tool_surface,
            modified_time=modified_time,
            parsed=ParseFailure(f"unreadable surface: {error}"),
        )
    content_digest = _text_digest(text)
    prior = previous.get(location)
    if prior is not None and prior.content_digest == content_digest:
        # unchanged content parses to the same result — reuse, re-stat only mtime.
        return replace(prior, modified_time=modified_time)
    return SurfaceObservation(
        tool_surface=tool_surface,
        embedded_id=extract_artifact_id(text, tool_surface),
        content_digest=content_digest,
        modified_time=modified_time,
        parsed=_parse_or_failure(text, tool_surface),
    )


# --- keyed-map surfaces ---------------------------------------------------------------


def _observe_keyed_map(
    spec: KeyedMapSurfaceSpec, previous: PreviousObservations
) -> list[SurfaceObservation]:
    if not spec.file.is_file():
        return []
    modified_time = _modified_time(spec.file)
    try:
        text = spec.file.read_text(encoding="utf-8")
        slot_map = _navigate_slot_map(
            deserialize(text, spec.surface_format.file_format),
            spec.surface_format.map_key_path,
        )
    except (OSError, UnicodeDecodeError, MalformedSurfaceError) as error:
        return _freeze_known_slots(spec, previous, modified_time, str(error))

    observations: list[SurfaceObservation] = []
    for slot_key in sorted(slot_map):
        location = KeyedMapSlot(file=spec.file, slot=slot_key)
        tool_surface = ToolSurface(spec.tool, spec.kind, location, spec.surface_format)
        slot_value = slot_map[slot_key]
        content_digest = _slot_digest(slot_value)
        prior = previous.get(location)
        if prior is not None and prior.content_digest == content_digest:
            observations.append(replace(prior, modified_time=modified_time))
            continue
        observations.append(
            SurfaceObservation(
                tool_surface=tool_surface,
                embedded_id=extract_artifact_id(text, tool_surface),
                content_digest=content_digest,
                modified_time=modified_time,
                parsed=_parse_slot_or_failure(text, tool_surface, slot_value),
            )
        )
    return observations


def _parse_slot_or_failure(
    text: str, tool_surface: ToolSurface, slot_value: Any
) -> CanonicalDocument | ParseFailure:
    """Parse one slot, first refusing values the JSON-shaped pipeline cannot carry.

    A legal-but-foreign deserialized value (e.g. an unquoted TOML date) would
    survive parsing into the canonical and crash its JSON digest later — content
    the pipeline cannot represent is malformed content, frozen per slot."""
    try:
        json.dumps(slot_value, ensure_ascii=False)
    except TypeError:
        return ParseFailure("slot value is not JSON-representable (e.g. an unquoted TOML date)")
    return _parse_or_failure(text, tool_surface)


def _navigate_slot_map(root: dict[str, Any], map_key_path: tuple[str, ...]) -> dict[str, Any]:
    current: Any = root
    for key in map_key_path:
        current = current.get(key) if isinstance(current, dict) else None
    if not isinstance(current, dict):
        raise MalformedSurfaceError(f"keyed-map file has no slot map at {'.'.join(map_key_path)!r}")
    return current


def _freeze_known_slots(
    spec: KeyedMapSurfaceSpec,
    previous: PreviousObservations,
    modified_time: float,
    reason: str,
) -> list[SurfaceObservation]:
    """The file no longer deserializes: its previously-known slots surface as
    ``ParseFailure`` (the planner freezes them) rather than vanish (a removal)."""
    return [
        replace(
            prior,
            # A frozen observation must carry NO reusable digest: it pairs a
            # file-level failure with last-good content, and a stale digest would
            # make a restore-to-identical-bytes reuse the failure forever
            # (freeze-until-fixed, not freeze-until-changed).
            content_digest="",
            modified_time=modified_time,
            parsed=ParseFailure(f"keyed-map file no longer deserializes: {reason}"),
        )
        for location, prior in sorted(previous.items(), key=lambda item: str(item[0]))
        if isinstance(location, KeyedMapSlot) and location.file == spec.file
    ]


# --- shared mechanics -----------------------------------------------------------------


def _parse_or_failure(text: str, tool_surface: ToolSurface) -> CanonicalDocument | ParseFailure:
    try:
        return file_to_canonical(text, tool_surface, None)
    except MalformedSurfaceError as error:
        return ParseFailure(str(error))


def _text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slot_digest(slot_value: Any) -> str:
    """One slot's content digest: its canonical JSON serialization, key-order free.

    ``default=repr`` keeps the digest total over everything ``deserialize`` can
    emit (e.g. TOML dates) — change detection must never raise."""
    payload = json.dumps(slot_value, sort_keys=True, ensure_ascii=False, default=repr)
    return _text_digest(payload)


def _modified_time(path: Path) -> float:
    """The surface's mtime; ``0.0`` on a stat race (file vanished between checks).

    The epoch sentinel makes the racing surface lose any freshest-content tiebreak
    this poll — the conservative outcome; the next poll re-stats it."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
