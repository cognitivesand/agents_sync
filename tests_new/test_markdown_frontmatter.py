"""Unit tests for the markdown-frontmatter dialect (rebuild S9).

The first wire-format dialect the centralized translation seam dispatches to: YAML
front-matter + Markdown body. It folds a tool file into the canonical document
(mapping `known_fields`, keeping `tool_only_fields` under `per_tool_only[tool]` and
every other front-matter key under `per_tool_extra[tool]` — the no-foreign-leak
contract, NFR-06/16) and renders the canonical back. Identity is recovered in
isolation and never minted (FR-11). Pure in-memory tests over `text: str`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents_sync.domain_model.canonical_document import CanonicalDocument
from agents_sync.domain_model.tool_surface import SurfaceFormat, ToolSurface
from agents_sync.translation import (
    MalformedSurfaceError,
    canonical_to_file,
    extract_artifact_id,
    file_to_canonical,
)

# A representative markdown recipe. The real per-tool recipes are data (S20); this
# fixture mirrors a claude-shaped surface so the dialect's mapping, tool-only, and
# camelCase-divergence behaviour are all exercised. `known_fields` is a mapping from
# the front-matter key to the canonical attribute, so claude's `permissionMode`
# folds into the canonical `permission_mode`.
_MARKDOWN = SurfaceFormat(
    dialect="markdown_frontmatter",
    id_field="pair_id",
    known_fields=(
        ("name", "name"),
        ("description", "description"),
        ("model", "model"),
        ("effort", "effort"),
        ("tools", "tools"),
        ("disallowedTools", "disallowed_tools"),
        ("permissionMode", "permission_mode"),
    ),
    tool_only_fields=("hooks", "mcpServers"),
)
_EMBEDDED_ID = "11111111-1111-4111-8111-111111111111"
_PRIOR_ID = "22222222-2222-4222-8222-222222222222"


def _surface(tool: str = "claude", kind: str = "agent", name: str = "reviewer") -> ToolSurface:
    return ToolSurface(
        tool=tool,
        kind=kind,
        location=Path(f"/u/.{tool}/{kind}s/{name}.md"),
        surface_format=_MARKDOWN,
    )


def _canonical(**overrides: object) -> CanonicalDocument:
    defaults: dict[str, object] = {
        "artifact_id": _EMBEDDED_ID,
        "kind": "agent",
        "name": "reviewer",
        "description": "Reviews code",
        "body": "Do the review.",
        "model": "opus",
        "tools": ("read", "write"),
        "disallowed_tools": ("danger",),
        "permission_mode": "ask",
        "per_tool_only": {"claude": {"hooks": {"PreToolUse": "guard"}}},
        "per_tool_extra": {"claude": {"customField": "kept"}},
    }
    defaults.update(overrides)
    return CanonicalDocument(**defaults)  # type: ignore[arg-type]


def test_render_then_parse_returns_an_equal_canonical() -> None:
    # The headline round-trip: parse(render(c)) == c for a canonical whose per-tool
    # bags belong to the rendered tool.
    canonical = _canonical()

    text = canonical_to_file(canonical, _surface(), None)
    folded = file_to_canonical(text, _surface(), None)

    assert folded == canonical


def test_parse_then_render_then_parse_is_stable() -> None:
    # Folding a real tool file is idempotent: a second fold of the rendered text
    # yields the same canonical (no drift across the codec).
    text = (
        "---\n"
        f"pair_id: {_EMBEDDED_ID}\n"
        "name: reviewer\n"
        "permissionMode: ask\n"
        "customField: kept\n"
        "---\n"
        "Do the review.\n"
    )

    once = file_to_canonical(text, _surface(), None)
    twice = file_to_canonical(canonical_to_file(once, _surface(), None), _surface(), None)

    assert twice == once


def test_unknown_frontmatter_field_is_preserved_in_per_tool_extra() -> None:
    # No-foreign-leak (NFR-06/16): a field the recipe does not own is neither dropped
    # nor folded into a known canonical attribute — it is kept verbatim under the
    # tool's extra bag and re-emitted on render.
    text = "---\npair_id: " + _EMBEDDED_ID + "\nname: reviewer\nweirdKey: 7\n---\nbody\n"

    canonical = file_to_canonical(text, _surface(), None)

    assert canonical.per_tool_extra["claude"]["weirdKey"] == 7
    assert canonical.name == "reviewer"  # the unknown field did not bleed into a known field
    assert "weirdKey: 7" in canonical_to_file(canonical, _surface(), None)


def test_another_tools_extra_bag_survives_folding_one_surface() -> None:
    # No-foreign-leak across tools: folding claude's surface must not discard the
    # extra/only bags the prior canonical holds for a different tool.
    prior = _canonical(
        per_tool_only={"codex": {"sandbox": "ro"}},
        per_tool_extra={"claude": {"customField": "old"}, "gemini": {"flag": "y"}},
    )
    text = "---\npair_id: " + _EMBEDDED_ID + "\nname: reviewer\ncustomField: new\n---\nbody\n"

    folded = file_to_canonical(text, _surface(), prior)

    assert folded.per_tool_only["codex"] == {"sandbox": "ro"}  # foreign tool-only bag survives
    assert folded.per_tool_extra["gemini"] == {"flag": "y"}  # foreign extra bag survives
    assert folded.per_tool_extra["claude"]["customField"] == "new"  # this tool's bag is folded


def test_camelcase_known_field_maps_to_the_canonical_attribute() -> None:
    # The recipe maps a tool's native spelling onto the canonical name and back.
    text = "---\npair_id: " + _EMBEDDED_ID + "\nname: reviewer\npermissionMode: plan\n---\nb\n"

    canonical = file_to_canonical(text, _surface(), None)

    assert canonical.permission_mode == "plan"
    assert "permissionMode: plan" in canonical_to_file(canonical, _surface(), None)


def test_tool_only_field_is_kept_under_per_tool_only() -> None:
    # A `tool_only_field` is preserved verbatim under per_tool_only[tool], not folded
    # into a shared canonical attribute, and round-trips.
    text = (
        "---\npair_id: " + _EMBEDDED_ID + "\nname: reviewer\nhooks:\n  PreToolUse: guard\n---\nb\n"
    )

    canonical = file_to_canonical(text, _surface(), None)

    assert canonical.per_tool_only["claude"]["hooks"] == {"PreToolUse": "guard"}
    # The render side must preserve the value, not just emit the key: re-folding the
    # rendered text recovers the same tool-only mapping.
    refolded = file_to_canonical(canonical_to_file(canonical, _surface(), None), _surface(), None)
    assert refolded.per_tool_only["claude"]["hooks"] == {"PreToolUse": "guard"}


def test_kind_is_stamped_from_the_surface() -> None:
    # The surface is authoritative for the artifact's kind (a CanonicalDocument
    # requires it and the text does not carry it).
    text = "---\npair_id: " + _EMBEDDED_ID + "\nname: deployer\n---\nb\n"

    canonical = file_to_canonical(text, _surface(kind="command"), None)

    assert canonical.kind == "command"


def test_an_id_less_surface_with_no_prior_is_not_minted() -> None:
    # file_to_canonical never mints (AD-2): a candidate surface with no embedded id
    # and no prior canonical yields the empty-id placeholder, not a fresh UUID.
    text = "---\nname: reviewer\n---\nbody\n"

    canonical = file_to_canonical(text, _surface(), None)

    assert canonical.artifact_id == ""


def test_embedded_id_is_carried_through() -> None:
    text = "---\npair_id: " + _EMBEDDED_ID + "\nname: reviewer\n---\nbody\n"

    canonical = file_to_canonical(text, _surface(), None)

    assert canonical.artifact_id == _EMBEDDED_ID


def test_prior_id_is_carried_when_the_surface_omits_one() -> None:
    # A managed surface need not repeat its id in every poll: the prior canonical
    # supplies it. Still never minted.
    prior = _canonical(artifact_id=_PRIOR_ID)
    text = "---\nname: reviewer\n---\nbody\n"

    canonical = file_to_canonical(text, _surface(), prior)

    assert canonical.artifact_id == _PRIOR_ID


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("tools:\n  - read\n  - write\n", ("read", "write")),
        ("tools: read, write\n", ("read", "write")),
    ],
)
def test_list_field_accepts_a_yaml_list_or_a_csv_string(
    raw: str, expected: tuple[str, ...]
) -> None:
    text = "---\npair_id: " + _EMBEDDED_ID + "\nname: reviewer\n" + raw + "---\nbody\n"

    canonical = file_to_canonical(text, _surface(), None)

    assert canonical.tools == expected


def test_body_is_preserved() -> None:
    text = "---\npair_id: " + _EMBEDDED_ID + "\nname: reviewer\n---\nLine one.\nLine two.\n"

    canonical = file_to_canonical(text, _surface(), None)

    assert canonical.body == "Line one.\nLine two."


@pytest.mark.parametrize(
    "malformed",
    [
        "---\n- a\n- b\n---\nbody\n",  # a YAML sequence, not a mapping
        "---\nname: [unclosed\n---\nbody\n",  # broken YAML (unclosed flow sequence)
    ],
)
def test_malformed_frontmatter_raises(malformed: str) -> None:
    # file_to_canonical raises; the read phase (S17) catches it into a ParseFailure.
    with pytest.raises(MalformedSurfaceError):
        file_to_canonical(malformed, _surface(), None)


def test_a_body_only_file_is_not_malformed() -> None:
    # No front-matter block at all is a valid metadata-less file, not an error.
    canonical = file_to_canonical("just a body, no frontmatter\n", _surface(), None)

    assert canonical.body == "just a body, no frontmatter"
    assert canonical.artifact_id == ""


def test_extract_id_reads_a_well_formed_id() -> None:
    text = "---\npair_id: " + _EMBEDDED_ID + "\nname: reviewer\n---\nbody\n"

    assert extract_artifact_id(text, _surface()) == _EMBEDDED_ID


def test_extract_id_recovers_in_isolation_from_malformed_yaml() -> None:
    # FR-11: identity is never lost to a field the dialect does not own — the id is
    # recovered from its own line even when the surrounding YAML will not parse, and
    # extract_artifact_id never raises.
    text = "---\npair_id: " + _EMBEDDED_ID + "\nbroken: : :\n---\nbody\n"

    assert extract_artifact_id(text, _surface()) == _EMBEDDED_ID


def test_extract_id_returns_none_when_absent() -> None:
    assert extract_artifact_id("---\nname: reviewer\n---\nbody\n", _surface()) is None
    assert extract_artifact_id("no frontmatter at all\n", _surface()) is None


def test_a_null_known_field_is_treated_as_absent_not_none() -> None:
    # A YAML-null value for a string-typed field (`description:` with no value) must not
    # write None onto the canonical's str attribute — that would crash the planner's
    # content_digest()/normalised(). It keeps the field's default instead.
    text = "---\npair_id: " + _EMBEDDED_ID + "\nname: reviewer\ndescription:\n---\nbody\n"

    canonical = file_to_canonical(text, _surface(), None)

    assert canonical.description == ""
    assert canonical.content_digest()  # would raise AttributeError if description were None


def test_an_empty_string_id_is_treated_as_absent() -> None:
    # The `and value` guard in id recovery: an empty-string id is not a valid id, so it
    # must fall through to the prior id rather than overwrite it with "".
    prior = _canonical(artifact_id=_PRIOR_ID)
    text = '---\npair_id: ""\nname: reviewer\n---\nbody\n'

    assert file_to_canonical(text, _surface(), prior).artifact_id == _PRIOR_ID
    assert extract_artifact_id(text, _surface()) is None


def test_an_empty_frontmatter_block_is_metadata_less_not_swallowed() -> None:
    # An idiomatic empty block (`---\n---\nbody`) is a valid metadata-less file; its
    # fences must not leak into the body (NFR-16 fidelity).
    canonical = file_to_canonical("---\n---\nReal body.\n", _surface(), None)

    assert canonical.body == "Real body."
    assert canonical.artifact_id == ""


def test_an_absent_optional_field_is_not_emitted() -> None:
    # Render drops a field whose value is empty/None, so it is absent on the wire rather
    # than emitted as `model: null`.
    canonical = _canonical(model=None, effort=None)

    rendered = canonical_to_file(canonical, _surface(), None)

    assert "model:" not in rendered
    assert "effort:" not in rendered
