from agents_sync.artifact_names import resolve_artifact_name


def test_agent_policy_prefers_frontmatter_then_path_then_prior():
    assert resolve_artifact_name(
        frontmatter_name="frontmatter",
        path_name="path",
        prior_name="prior",
        precedence=("frontmatter", "path", "prior"),
    ) == "frontmatter"
    assert resolve_artifact_name(
        path_name="path",
        prior_name="prior",
        precedence=("frontmatter", "path", "prior"),
    ) == "path"


def test_rules_policy_prefers_override_then_path_then_frontmatter():
    assert resolve_artifact_name(
        override_name="override",
        frontmatter_name="frontmatter",
        path_name="path",
        precedence=("override", "path", "frontmatter"),
    ) == "override"


def test_required_name_raises_after_all_sources_are_empty():
    try:
        resolve_artifact_name(
            frontmatter_name="",
            path_name=None,
            prior_name="",
            precedence=("frontmatter", "path", "prior"),
            required_label="agent",
        )
    except ValueError as exc:
        assert "agent needs a non-empty artifact name" in str(exc)
    else:
        raise AssertionError("expected missing name to raise")
