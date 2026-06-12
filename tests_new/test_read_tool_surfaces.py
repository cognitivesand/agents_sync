"""Unit tests for the read phase (rebuild S17 increment 1, FR-10/FR-11).

``read_tool_surfaces`` turns declarative surface specs into the
``SurfaceObservation``s the pure planner consumes: raw-text digest, mtime,
isolation-extracted id, and a parse that catches malformed content into
``ParseFailure`` (recipe errors stay loud). Re-parse happens only for changed
digests — an unchanged surface reuses the prior poll's parsed result, proven here
with a sentinel canonical rather than a mock. A malformed keyed-map file yields
``ParseFailure`` for its previously-known slots (freeze, never removal).
Real filesystem via tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.observation import ParseFailure, SurfaceObservation
from agents_sync.domain_model.tool_surface import KeyedMapSlot, SurfaceFormat
from agents_sync.read_tool_surfaces import (
    DirectorySurfaceSpec,
    KeyedMapSurfaceSpec,
    RulesFileSurfaceSpec,
    read_tool_surfaces,
)

_EMBEDDED_ID = "11111111-1111-4111-8111-111111111111"

_MARKDOWN = SurfaceFormat(
    dialect="markdown_frontmatter",
    id_field="pair_id",
    known_fields=(("name", "name"), ("description", "description")),
)
_MCP = SurfaceFormat(
    dialect="mcp_server",
    id_field="pair_id",
    map_key_path=("mcpServers",),
    file_format="json",
)


def _agent_text(name: str = "reviewer", with_id: bool = True) -> str:
    id_line = f"pair_id: {_EMBEDDED_ID}\n" if with_id else ""
    return f"---\n{id_line}name: {name}\n---\nBe terse.\n"


def _directory_spec(directory: Path) -> DirectorySurfaceSpec:
    return DirectorySurfaceSpec(
        tool="claude",
        kind="agent",
        directory=directory,
        filename_suffix=".md",
        surface_format=_MARKDOWN,
    )


def _keyed_map_spec(file: Path) -> KeyedMapSurfaceSpec:
    return KeyedMapSurfaceSpec(tool="cursor", kind="mcp_server", file=file, surface_format=_MCP)


def _sentinel(name: str = "sentinel") -> CanonicalDocument:
    return CanonicalDocument(artifact_id=_EMBEDDED_ID, kind="agent", name=name)


# --- directory specs ----------------------------------------------------------------


def test_each_matching_file_yields_one_observation(tmp_path: Path) -> None:
    (tmp_path / "alpha.md").write_text(_agent_text("alpha"))
    (tmp_path / "beta.md").write_text(_agent_text("beta", with_id=False))

    observations = read_tool_surfaces((_directory_spec(tmp_path),))

    assert len(observations) == 2
    by_name = {obs.tool_surface.location.name: obs for obs in observations}
    assert isinstance(by_name["alpha.md"].parsed, CanonicalDocument)
    assert by_name["alpha.md"].parsed.name == "alpha"
    assert by_name["alpha.md"].embedded_id == _EMBEDDED_ID
    assert by_name["beta.md"].embedded_id is None


def test_a_missing_directory_yields_no_observations(tmp_path: Path) -> None:
    assert read_tool_surfaces((_directory_spec(tmp_path / "absent"),)) == ()


def test_a_non_matching_suffix_is_not_observed(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("not an artifact")

    assert read_tool_surfaces((_directory_spec(tmp_path),)) == ()


def test_digest_and_mtime_are_populated(tmp_path: Path) -> None:
    path = tmp_path / "alpha.md"
    path.write_text(_agent_text())

    [observation] = read_tool_surfaces((_directory_spec(tmp_path),))

    assert observation.content_digest != ""
    assert observation.modified_time == path.stat().st_mtime


def test_two_different_contents_have_different_digests(tmp_path: Path) -> None:
    (tmp_path / "alpha.md").write_text(_agent_text("alpha"))
    (tmp_path / "beta.md").write_text(_agent_text("beta"))

    first, second = read_tool_surfaces((_directory_spec(tmp_path),))

    assert first.content_digest != second.content_digest


def test_malformed_content_is_a_parse_failure_with_a_digest(tmp_path: Path) -> None:
    # The digest is still computed (the content rule needs it to detect the edit);
    # the parse failure routes the artifact to freeze, never a raise (FR-11).
    (tmp_path / "broken.md").write_text("---\nname: [unclosed\n---\nbody\n")

    [observation] = read_tool_surfaces((_directory_spec(tmp_path),))

    assert isinstance(observation.parsed, ParseFailure)
    assert observation.content_digest != ""


def test_unreadable_bytes_are_a_parse_failure(tmp_path: Path) -> None:
    (tmp_path / "binary.md").write_bytes(b"\xff\xfe not utf-8 \xff")

    [observation] = read_tool_surfaces((_directory_spec(tmp_path),))

    assert isinstance(observation.parsed, ParseFailure)


# --- re-parse only changed (the previous-observations reuse) -------------------------


def _prior_for(
    tmp_path: Path, parsed: CanonicalDocument
) -> dict[Path | KeyedMapSlot, SurfaceObservation]:
    # A prior observation for alpha.md whose parsed is a recognizable sentinel and
    # whose digest matches the CURRENT file content.
    [current] = read_tool_surfaces((_directory_spec(tmp_path),))
    prior = SurfaceObservation(
        tool_surface=current.tool_surface,
        embedded_id=_EMBEDDED_ID,
        content_digest=current.content_digest,
        modified_time=0.0,
        parsed=parsed,
    )
    return {current.tool_surface.location: prior}


def test_an_unchanged_digest_reuses_the_prior_parse(tmp_path: Path) -> None:
    # No mock: the prior observation carries a sentinel canonical a fresh parse
    # could never produce; seeing it in the output proves the parse was skipped.
    (tmp_path / "alpha.md").write_text(_agent_text("alpha"))
    previous = _prior_for(tmp_path, _sentinel())

    [observation] = read_tool_surfaces((_directory_spec(tmp_path),), previous)

    assert observation.parsed == _sentinel()
    assert observation.modified_time != 0.0  # mtime is re-stated fresh, not reused


def test_a_changed_digest_is_re_parsed(tmp_path: Path) -> None:
    (tmp_path / "alpha.md").write_text(_agent_text("alpha"))
    previous = _prior_for(tmp_path, _sentinel())
    (tmp_path / "alpha.md").write_text(_agent_text("renamed"))

    [observation] = read_tool_surfaces((_directory_spec(tmp_path),), previous)

    assert isinstance(observation.parsed, CanonicalDocument)
    assert observation.parsed.name == "renamed"  # fresh parse, not the sentinel


# --- keyed-map specs -----------------------------------------------------------------


def _mcp_file(tmp_path: Path) -> Path:
    file = tmp_path / "mcp.json"
    file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {"pair_id": _EMBEDDED_ID, "command": "npx"},
                    "gitlab": {"command": "glab"},
                }
            }
        )
    )
    return file


def test_each_slot_yields_one_observation(tmp_path: Path) -> None:
    file = _mcp_file(tmp_path)

    observations = read_tool_surfaces((_keyed_map_spec(file),))

    assert {obs.tool_surface.location.slot for obs in observations} == {"github", "gitlab"}
    by_slot = {obs.tool_surface.location.slot: obs for obs in observations}
    assert by_slot["github"].embedded_id == _EMBEDDED_ID
    assert by_slot["gitlab"].embedded_id is None
    assert isinstance(by_slot["github"].parsed, CanonicalDocument)
    assert by_slot["github"].parsed.command == "npx"


def test_slot_digests_differ_between_slots(tmp_path: Path) -> None:
    observations = read_tool_surfaces((_keyed_map_spec(_mcp_file(tmp_path)),))

    digests = [obs.content_digest for obs in observations]
    assert digests[0] != digests[1]


def test_an_unchanged_slot_reuses_the_prior_parse(tmp_path: Path) -> None:
    file = _mcp_file(tmp_path)
    [github_now] = [
        obs
        for obs in read_tool_surfaces((_keyed_map_spec(file),))
        if obs.tool_surface.location.slot == "github"
    ]
    sentinel = CanonicalDocument(artifact_id=_EMBEDDED_ID, kind="mcp_server", name="sentinel")
    previous = {
        github_now.tool_surface.location: SurfaceObservation(
            tool_surface=github_now.tool_surface,
            content_digest=github_now.content_digest,
            parsed=sentinel,
        )
    }

    observations = read_tool_surfaces((_keyed_map_spec(file),), previous)

    by_slot = {obs.tool_surface.location.slot: obs for obs in observations}
    assert by_slot["github"].parsed == sentinel  # reused
    assert isinstance(by_slot["gitlab"].parsed, CanonicalDocument)  # parsed fresh


def test_a_changed_slot_is_re_parsed(tmp_path: Path) -> None:
    # The keyed-map mirror of the changed-digest test: editing one slot's CONTENT
    # (same key) must defeat the reuse cache and parse fresh.
    file = _mcp_file(tmp_path)
    [github_now] = [
        obs
        for obs in read_tool_surfaces((_keyed_map_spec(file),))
        if obs.tool_surface.location.slot == "github"
    ]
    sentinel = CanonicalDocument(artifact_id=_EMBEDDED_ID, kind="mcp_server", name="sentinel")
    previous = {
        github_now.tool_surface.location: SurfaceObservation(
            tool_surface=github_now.tool_surface,
            content_digest=github_now.content_digest,
            parsed=sentinel,
        )
    }
    file.write_text(
        json.dumps({"mcpServers": {"github": {"pair_id": _EMBEDDED_ID, "command": "uvx"}}})
    )

    observations = read_tool_surfaces((_keyed_map_spec(file),), previous)

    by_slot = {obs.tool_surface.location.slot: obs for obs in observations}
    assert isinstance(by_slot["github"].parsed, CanonicalDocument)
    assert by_slot["github"].parsed.command == "uvx"  # fresh parse, not the sentinel


def test_a_reused_slot_observation_has_a_fresh_mtime(tmp_path: Path) -> None:
    file = _mcp_file(tmp_path)
    [github_now] = [
        obs
        for obs in read_tool_surfaces((_keyed_map_spec(file),))
        if obs.tool_surface.location.slot == "github"
    ]
    previous = {
        github_now.tool_surface.location: SurfaceObservation(
            tool_surface=github_now.tool_surface,
            content_digest=github_now.content_digest,
            modified_time=0.0,
            parsed=github_now.parsed,
        )
    }

    observations = read_tool_surfaces((_keyed_map_spec(file),), previous)

    by_slot = {obs.tool_surface.location.slot: obs for obs in observations}
    assert by_slot["github"].modified_time == file.stat().st_mtime  # re-stated, not reused


def test_a_deleted_file_with_history_yields_no_observation(tmp_path: Path) -> None:
    # Deletion is a deliberate removal the planner propagates — NOT a freeze: a
    # vanished surface must simply not be observed, history or no history.
    (tmp_path / "alpha.md").write_text(_agent_text())
    [prior] = read_tool_surfaces((_directory_spec(tmp_path),))
    (tmp_path / "alpha.md").unlink()

    observations = read_tool_surfaces(
        (_directory_spec(tmp_path),), {prior.tool_surface.location: prior}
    )

    assert observations == ()


def test_a_deleted_keyed_map_file_with_history_yields_no_observations(tmp_path: Path) -> None:
    file = _mcp_file(tmp_path)
    previous = {
        obs.tool_surface.location: obs for obs in read_tool_surfaces((_keyed_map_spec(file),))
    }
    file.unlink()

    assert read_tool_surfaces((_keyed_map_spec(file),), previous) == ()


def test_a_recovered_keyed_map_unfreezes_its_slots(tmp_path: Path) -> None:
    # Freeze-until-FIXED: corrupt the file (slots freeze), then restore it to
    # byte-identical good content — the slots must parse again, not stay frozen
    # because the frozen observation still carried the last good digest.
    file = _mcp_file(tmp_path)
    good_bytes = file.read_bytes()
    previous = {
        obs.tool_surface.location: obs for obs in read_tool_surfaces((_keyed_map_spec(file),))
    }
    file.write_text("{broken json")
    frozen = {
        obs.tool_surface.location: obs
        for obs in read_tool_surfaces((_keyed_map_spec(file),), previous)
    }
    file.write_bytes(good_bytes)

    observations = read_tool_surfaces((_keyed_map_spec(file),), frozen)

    assert all(isinstance(obs.parsed, CanonicalDocument) for obs in observations)


def test_a_non_json_representable_slot_value_is_a_parse_failure(tmp_path: Path) -> None:
    # A legal TOML date in a slot is content the JSON-shaped pipeline cannot carry:
    # it must surface as a per-slot ParseFailure (freeze), never crash the poll.
    file = tmp_path / "config.toml"
    file.write_text('[mcp_servers.github]\ncommand = "npx"\nreleased = 2024-01-01\n')
    spec = KeyedMapSurfaceSpec(
        tool="codex",
        kind="mcp_server",
        file=file,
        surface_format=SurfaceFormat(
            dialect="mcp_server",
            id_field="pair_id",
            map_key_path=("mcp_servers",),
            file_format="toml",
        ),
    )

    [observation] = read_tool_surfaces((spec,))

    assert isinstance(observation.parsed, ParseFailure)
    assert observation.content_digest != ""  # the digest stays total for change detection


def test_a_malformed_keyed_map_freezes_previously_known_slots(tmp_path: Path) -> None:
    # The file no longer deserializes: its previously-known slots must surface as
    # ParseFailure (-> freeze) rather than vanish (-> removal propagation).
    file = _mcp_file(tmp_path)
    previous = {
        obs.tool_surface.location: obs for obs in read_tool_surfaces((_keyed_map_spec(file),))
    }
    file.write_text("{broken json")

    observations = read_tool_surfaces((_keyed_map_spec(file),), previous)

    assert {obs.tool_surface.location.slot for obs in observations} == {"github", "gitlab"}
    assert all(isinstance(obs.parsed, ParseFailure) for obs in observations)


def test_a_malformed_keyed_map_with_no_history_yields_no_observations(tmp_path: Path) -> None:
    file = tmp_path / "mcp.json"
    file.write_text("{broken json")

    assert read_tool_surfaces((_keyed_map_spec(file),)) == ()


def test_a_missing_keyed_map_file_yields_no_observations(tmp_path: Path) -> None:
    assert read_tool_surfaces((_keyed_map_spec(tmp_path / "absent.json"),)) == ()


# --- rules filename precedence (FR-10) ----------------------------------------------


def _rules_spec(directory: Path) -> RulesFileSurfaceSpec:
    return RulesFileSurfaceSpec(
        tool="claude",
        kind="rules",
        directory=directory,
        candidate_filenames=("AGENTS.md", "CLAUDE.md"),
        surface_format=_MARKDOWN,
    )


def test_the_highest_precedence_rules_file_wins(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("agents rules\n")
    (tmp_path / "CLAUDE.md").write_text("claude rules\n")

    [observation] = read_tool_surfaces((_rules_spec(tmp_path),))

    assert observation.tool_surface.location.name == "AGENTS.md"


def test_a_lower_precedence_rules_file_is_observed_when_alone(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("claude rules\n")

    [observation] = read_tool_surfaces((_rules_spec(tmp_path),))

    assert observation.tool_surface.location.name == "CLAUDE.md"


def test_an_unlisted_filename_is_never_observed_as_rules(tmp_path: Path) -> None:
    (tmp_path / "RULES.md").write_text("not on the declared list\n")

    assert read_tool_surfaces((_rules_spec(tmp_path),)) == ()


# --- @import resolution (S17 increment 2, US-15) -------------------------------------


def _rules_text(body: str) -> str:
    return f"---\npair_id: {_EMBEDDED_ID}\n---\n{body}"


def test_an_import_is_inlined_into_the_effective_body(tmp_path: Path) -> None:
    (tmp_path / "extra.md").write_text("imported line\n")
    (tmp_path / "AGENTS.md").write_text(_rules_text("before\n@extra.md\nafter\n"))

    [observation] = read_tool_surfaces((_rules_spec(tmp_path),))

    assert isinstance(observation.parsed, CanonicalDocument)
    # the dialect's body convention strips the trailing newline; the imported
    # file's own trailing newline survives as the blank line after its content.
    assert observation.parsed.body == "before\nimported line\n\nafter"


def test_the_source_body_is_preserved_for_the_origin_tool(tmp_path: Path) -> None:
    # The effective body propagates to other tools; the origin tool re-renders the
    # user's own @import pointer, not the inlined text (US-15 AC-2).
    (tmp_path / "extra.md").write_text("imported line\n")
    (tmp_path / "AGENTS.md").write_text(_rules_text("@extra.md\n"))

    [observation] = read_tool_surfaces((_rules_spec(tmp_path),))

    assert isinstance(observation.parsed, CanonicalDocument)
    assert observation.parsed.per_tool_only["claude"]["rules_source_body"] == "@extra.md"


def test_a_body_without_imports_is_untouched(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(_rules_text("plain rules\n"))

    [observation] = read_tool_surfaces((_rules_spec(tmp_path),))

    assert isinstance(observation.parsed, CanonicalDocument)
    assert observation.parsed.body == "plain rules"  # the dialect strips the trailing newline
    assert "rules_source_body" not in observation.parsed.per_tool_only.get("claude", {})


def test_nested_imports_resolve_depth_first(tmp_path: Path) -> None:
    (tmp_path / "inner.md").write_text("innermost\n")
    (tmp_path / "outer.md").write_text("outer-before\n@inner.md\nouter-after\n")
    (tmp_path / "AGENTS.md").write_text(_rules_text("top\n@outer.md\nbottom\n"))

    [observation] = read_tool_surfaces((_rules_spec(tmp_path),))

    assert isinstance(observation.parsed, CanonicalDocument)
    # exact body pins both placement and depth-first order (each imported file's
    # trailing newline survives as a blank line after its inlined content).
    assert observation.parsed.body == "top\nouter-before\ninnermost\n\nouter-after\n\nbottom"


def test_a_malformed_rules_file_with_imports_stays_a_parse_failure(tmp_path: Path) -> None:
    # The import resolver must pass a front-matter ParseFailure through untouched,
    # never crash trying to resolve a body that was never parsed (FR-11).
    (tmp_path / "AGENTS.md").write_text("---\nname: [unclosed\n---\n@extra.md\n")

    [observation] = read_tool_surfaces((_rules_spec(tmp_path),))

    assert isinstance(observation.parsed, ParseFailure)


def test_an_import_escaping_the_rules_root_is_a_parse_failure(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (tmp_path / "outside.md").write_text("secret\n")
    (rules_dir / "AGENTS.md").write_text(_rules_text("@../outside.md\n"))

    [observation] = read_tool_surfaces((_rules_spec(rules_dir),))

    assert isinstance(observation.parsed, ParseFailure)
    assert "escapes" in observation.parsed.reason


def test_an_import_cycle_is_a_parse_failure(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("@b.md\n")
    (tmp_path / "b.md").write_text("@a.md\n")
    (tmp_path / "AGENTS.md").write_text(_rules_text("@a.md\n"))

    [observation] = read_tool_surfaces((_rules_spec(tmp_path),))

    assert isinstance(observation.parsed, ParseFailure)
    assert "cycle" in observation.parsed.reason


def test_a_missing_import_target_is_a_parse_failure(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(_rules_text("@absent.md\n"))

    [observation] = read_tool_surfaces((_rules_spec(tmp_path),))

    assert isinstance(observation.parsed, ParseFailure)
    assert "unreadable" in observation.parsed.reason


def test_import_nesting_beyond_the_depth_limit_is_a_parse_failure(tmp_path: Path) -> None:
    for depth in range(12):
        (tmp_path / f"level{depth}.md").write_text(f"@level{depth + 1}.md\n")
    (tmp_path / "level12.md").write_text("bottom\n")
    (tmp_path / "AGENTS.md").write_text(_rules_text("@level0.md\n"))

    [observation] = read_tool_surfaces((_rules_spec(tmp_path),))

    assert isinstance(observation.parsed, ParseFailure)
    assert "depth" in observation.parsed.reason


def test_editing_an_imported_file_changes_the_observation_digest(tmp_path: Path) -> None:
    # Imported content IS the artifact's content: an edit behind the pointer must
    # surface as a digest change, or it would never propagate.
    (tmp_path / "extra.md").write_text("v1\n")
    (tmp_path / "AGENTS.md").write_text(_rules_text("@extra.md\n"))
    [before] = read_tool_surfaces((_rules_spec(tmp_path),))

    (tmp_path / "extra.md").write_text("v2\n")
    [after] = read_tool_surfaces((_rules_spec(tmp_path),))

    assert before.content_digest != after.content_digest


# --- mixed specs ---------------------------------------------------------------------


def test_observations_from_multiple_specs_are_combined(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "alpha.md").write_text(_agent_text())
    file = _mcp_file(tmp_path)
    (tmp_path / "AGENTS.md").write_text(_rules_text("rules\n"))

    observations = read_tool_surfaces(
        (_directory_spec(agents_dir), _keyed_map_spec(file), _rules_spec(tmp_path))
    )

    locations = {(obs.tool_surface.tool, str(obs.tool_surface.location)) for obs in observations}
    assert locations == {
        ("claude", str(agents_dir / "alpha.md")),
        ("cursor", str(KeyedMapSlot(file=file, slot="github"))),
        ("cursor", str(KeyedMapSlot(file=file, slot="gitlab"))),
        ("claude", str(tmp_path / "AGENTS.md")),
    }
