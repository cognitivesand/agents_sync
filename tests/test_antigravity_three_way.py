"""Plan §4 deliverable: 3-tool test matrix with Antigravity in the registry.

Covers the cases enumerated under "Phase 4 — wire Antigravity into the sync
loop" in docs/v0.4_implementation_plan.md:

  - 3-way no-op poll.
  - Edit on each of the 3 tools propagates to the other 2.
  - 2-way and 3-way conflict resolution with mtime + alphabetical tiebreak.
  - Removal on each tool archives + removes the other 2.
  - Archive-failure short-circuit on removal.
  - First-boot adoption of an Antigravity-only skill.
  - §5 extension of an existing 2-tool managed pair to Antigravity.
  - §5.5 first-boot reconciliation across all 3 tools.
  - Mixed first-boot library {A,B} / {B,C} / {C,D}.
  - Antigravity does not participate in agent sync.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from agents_sync import archive as archive_module
from agents_sync.sync import Syncer


# ---------- helpers ----------

def _skill_md(name: str, description: str = "x", body: str = "body") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}\n"


def _write_skill(root: Path, name: str, description: str = "x", body: str = "body") -> Path:
    """Create a skill directory at <root>/<name>/SKILL.md and return the dir."""
    skill_dir = root / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_skill_md(name, description=description, body=body))
    return skill_dir


def _set_mtime(path: Path, value: float) -> None:
    """Set mtime on a path; for skill dirs we set it on the SKILL.md file
    because discovery's mtime comes from the artifact path itself."""
    os.utime(path, (value, value))


def _set_skill_mtimes(skill_dir: Path, value: float) -> None:
    """Make the skill directory and its SKILL.md both have the given mtime."""
    _set_mtime(skill_dir / "SKILL.md", value)
    _set_mtime(skill_dir, value)


def _replace_in_skill_md(skill_dir: Path, old: str, new: str) -> None:
    """Mutate a SKILL.md in place by string-replace, preserving frontmatter
    (notably `pair_id:`) so the daemon sees it as the same managed pair."""
    md = skill_dir / "SKILL.md"
    md.write_text(md.read_text().replace(old, new))


def _read_state(syncer: Syncer) -> dict:
    state_file = syncer.state_dir / "state.json"
    if not state_file.exists():
        return {}
    return json.loads(state_file.read_text())


def _the_only_pair(syncer: Syncer) -> tuple[str, dict]:
    state = _read_state(syncer)
    pairs = state["customization_artifacts"]
    assert len(pairs) == 1
    pair_id = next(iter(pairs))
    return pair_id, pairs[pair_id]


def _archive_files(syncer: Syncer, pair_id: str, tool_name: str) -> list[Path]:
    archive_dir = syncer.state_dir / "archive" / pair_id / tool_name
    if not archive_dir.exists():
        return []
    return sorted(archive_dir.iterdir())


# ---------- 3-way no-op ----------

def test_three_way_noop_poll(syncer: Syncer):
    _write_skill(Path(syncer.claude_skills_dir), "demo")
    syncer.sync_once()
    changed = syncer.sync_once()
    assert changed == 0


# ---------- 3-way edit propagation ----------

def test_claude_skill_edit_propagates_to_codex_and_antigravity(syncer: Syncer):
    claude_dir = _write_skill(Path(syncer.claude_skills_dir), "fmt", description="original")
    syncer.sync_once()
    _, entry = _the_only_pair(syncer)
    assert set(entry["agentic_tools"].keys()) == {"claude", "codex", "antigravity"}

    _replace_in_skill_md(claude_dir, "original", "EDITED")
    syncer.sync_once()

    codex_md = Path(entry["agentic_tools"]["codex"]["path"]) / "SKILL.md"
    antigravity_md = Path(entry["agentic_tools"]["antigravity"]["path"]) / "SKILL.md"
    assert "EDITED" in codex_md.read_text()
    assert "EDITED" in antigravity_md.read_text()


def test_codex_skill_edit_propagates_to_claude_and_antigravity(syncer: Syncer):
    _write_skill(Path(syncer.claude_skills_dir), "fmt", description="original")
    syncer.sync_once()
    _, entry = _the_only_pair(syncer)
    codex_dir = Path(entry["agentic_tools"]["codex"]["path"])

    _replace_in_skill_md(codex_dir, "original", "CODEX-EDIT")
    syncer.sync_once()

    claude_md = Path(entry["agentic_tools"]["claude"]["path"]) / "SKILL.md"
    antigravity_md = Path(entry["agentic_tools"]["antigravity"]["path"]) / "SKILL.md"
    assert "CODEX-EDIT" in claude_md.read_text()
    assert "CODEX-EDIT" in antigravity_md.read_text()


def test_antigravity_skill_edit_propagates_to_claude_and_codex(syncer: Syncer):
    _write_skill(Path(syncer.claude_skills_dir), "fmt", description="original")
    syncer.sync_once()
    _, entry = _the_only_pair(syncer)
    antigravity_dir = Path(entry["agentic_tools"]["antigravity"]["path"])

    _replace_in_skill_md(antigravity_dir, "original", "AG-EDIT")
    syncer.sync_once()

    claude_md = Path(entry["agentic_tools"]["claude"]["path"]) / "SKILL.md"
    codex_md = Path(entry["agentic_tools"]["codex"]["path"]) / "SKILL.md"
    assert "AG-EDIT" in claude_md.read_text()
    assert "AG-EDIT" in codex_md.read_text()


# ---------- conflict resolution at N=3 ----------

def test_two_tools_newer_than_third_winner_overwrites_third(syncer: Syncer):
    """Claude + Codex both edited newer than Antigravity ⇒ Antigravity loses to
    the winner picked from {claude, codex} (alphabetical tiebreak: claude)."""
    _write_skill(Path(syncer.claude_skills_dir), "fmt", description="original")
    syncer.sync_once()
    _, entry = _the_only_pair(syncer)
    claude_dir = Path(entry["agentic_tools"]["claude"]["path"])
    codex_dir = Path(entry["agentic_tools"]["codex"]["path"])
    antigravity_dir = Path(entry["agentic_tools"]["antigravity"]["path"])

    _replace_in_skill_md(claude_dir, "original", "CLAUDE-NEW")
    _replace_in_skill_md(codex_dir, "original", "CODEX-NEW")
    # Antigravity stays unchanged.
    _set_skill_mtimes(claude_dir, 3000.0)
    _set_skill_mtimes(codex_dir, 3000.0)
    _set_skill_mtimes(antigravity_dir, 1000.0)

    syncer.sync_once()

    # Tiebreak alphabetical ⇒ claude wins ⇒ both codex and antigravity converge
    # to claude content. Codex's prior bytes archived.
    assert "CLAUDE-NEW" in (claude_dir / "SKILL.md").read_text()
    assert "CLAUDE-NEW" in (codex_dir / "SKILL.md").read_text()
    assert "CLAUDE-NEW" in (antigravity_dir / "SKILL.md").read_text()
    pair_id, _ = _the_only_pair(syncer)
    assert _archive_files(syncer, pair_id, "codex"), "codex bytes should be archived"


def test_three_way_conflict_picks_argmax_mtime_archives_losers(syncer: Syncer):
    """All three tools edit; the latest mtime wins; the other two are archived."""
    _write_skill(Path(syncer.claude_skills_dir), "fmt", description="original")
    syncer.sync_once()
    pair_id, entry = _the_only_pair(syncer)
    claude_dir = Path(entry["agentic_tools"]["claude"]["path"])
    codex_dir = Path(entry["agentic_tools"]["codex"]["path"])
    antigravity_dir = Path(entry["agentic_tools"]["antigravity"]["path"])

    _replace_in_skill_md(claude_dir, "original", "CLAUDE-MID")
    _replace_in_skill_md(codex_dir, "original", "CODEX-LATEST")
    _replace_in_skill_md(antigravity_dir, "original", "AG-OLDEST")
    _set_skill_mtimes(claude_dir, 2000.0)
    _set_skill_mtimes(codex_dir, 3000.0)
    _set_skill_mtimes(antigravity_dir, 1000.0)

    syncer.sync_once()

    # Codex wins (latest mtime); claude and antigravity converge; their prior
    # bytes archived.
    assert "CODEX-LATEST" in (claude_dir / "SKILL.md").read_text()
    assert "CODEX-LATEST" in (codex_dir / "SKILL.md").read_text()
    assert "CODEX-LATEST" in (antigravity_dir / "SKILL.md").read_text()
    assert _archive_files(syncer, pair_id, "claude"), "claude bytes archived"
    assert _archive_files(syncer, pair_id, "antigravity"), "antigravity bytes archived"


# ---------- 3-way removal propagation ----------

def test_removal_on_antigravity_archives_claude_and_codex(syncer: Syncer):
    _write_skill(Path(syncer.claude_skills_dir), "fmt")
    syncer.sync_once()
    pair_id, entry = _the_only_pair(syncer)
    claude_dir = Path(entry["agentic_tools"]["claude"]["path"])
    codex_dir = Path(entry["agentic_tools"]["codex"]["path"])
    antigravity_dir = Path(entry["agentic_tools"]["antigravity"]["path"])

    shutil.rmtree(antigravity_dir)
    syncer.sync_once()

    assert not claude_dir.exists()
    assert not codex_dir.exists()
    assert _archive_files(syncer, pair_id, "claude"), "claude bytes archived"
    assert _archive_files(syncer, pair_id, "codex"), "codex bytes archived"
    # pair_id dropped from state because no entries remain.
    assert _read_state(syncer).get("customization_artifacts", {}) == {}


def test_removal_on_claude_archives_codex_and_antigravity(syncer: Syncer):
    _write_skill(Path(syncer.claude_skills_dir), "fmt")
    syncer.sync_once()
    pair_id, entry = _the_only_pair(syncer)
    claude_dir = Path(entry["agentic_tools"]["claude"]["path"])
    codex_dir = Path(entry["agentic_tools"]["codex"]["path"])
    antigravity_dir = Path(entry["agentic_tools"]["antigravity"]["path"])

    shutil.rmtree(claude_dir)
    syncer.sync_once()

    assert not codex_dir.exists()
    assert not antigravity_dir.exists()
    assert _archive_files(syncer, pair_id, "codex")
    assert _archive_files(syncer, pair_id, "antigravity")


def test_removal_on_codex_archives_claude_and_antigravity(syncer: Syncer):
    _write_skill(Path(syncer.claude_skills_dir), "fmt")
    syncer.sync_once()
    pair_id, entry = _the_only_pair(syncer)
    claude_dir = Path(entry["agentic_tools"]["claude"]["path"])
    codex_dir = Path(entry["agentic_tools"]["codex"]["path"])
    antigravity_dir = Path(entry["agentic_tools"]["antigravity"]["path"])

    shutil.rmtree(codex_dir)
    syncer.sync_once()

    assert not claude_dir.exists()
    assert not antigravity_dir.exists()
    assert _archive_files(syncer, pair_id, "claude")
    assert _archive_files(syncer, pair_id, "antigravity")


def test_archive_failure_short_circuits_removal(syncer: Syncer, monkeypatch: pytest.MonkeyPatch):
    """If archiving a survivor fails, the survivors stay on disk and state is
    preserved so the next poll retries."""
    _write_skill(Path(syncer.claude_skills_dir), "fmt")
    syncer.sync_once()
    pair_id, entry = _the_only_pair(syncer)
    claude_dir = Path(entry["agentic_tools"]["claude"]["path"])
    codex_dir = Path(entry["agentic_tools"]["codex"]["path"])
    antigravity_dir = Path(entry["agentic_tools"]["antigravity"]["path"])

    state_before = _read_state(syncer)

    def boom(*args, **kwargs):
        raise OSError("simulated archive failure")

    monkeypatch.setattr("agents_sync.sync.archive.archive_move", boom)

    shutil.rmtree(antigravity_dir)
    syncer.sync_once()

    # Survivors untouched; state preserved.
    assert claude_dir.exists()
    assert codex_dir.exists()
    assert _read_state(syncer) == state_before


# ---------- adoption from antigravity-only ----------

def test_first_boot_adoption_of_antigravity_only_skill(syncer: Syncer):
    """A skill present only on antigravity gets adopted and rendered to claude and codex."""
    antigravity_root = Path(syncer.config["antigravity_skills_dir"])
    _write_skill(antigravity_root, "ag-only-skill", description="from-antigravity")

    syncer.sync_once()

    pair_id, entry = _the_only_pair(syncer)
    assert set(entry["agentic_tools"].keys()) == {"claude", "codex", "antigravity"}
    claude_md = Path(entry["agentic_tools"]["claude"]["path"]) / "SKILL.md"
    codex_md = Path(entry["agentic_tools"]["codex"]["path"]) / "SKILL.md"
    assert "from-antigravity" in claude_md.read_text()
    assert "from-antigravity" in codex_md.read_text()


# ---------- §5 extension ----------

def test_extension_of_existing_two_tool_pair_to_antigravity(tmp_path: Path):
    """An already-managed claude+codex pair gains an antigravity entry once
    the antigravity dir becomes available on a later poll."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for sub in ("ca", "cs", "xs"):
        (tmp_path / sub).mkdir()
    # Start with antigravity disabled so the first sync_once registers only claude+codex.
    config_two_tool = {
        "poll_interval_seconds": 1.0,
        "state_path": str(state_dir / "state.json"),
        "claude_agents_dir": str(tmp_path / "ca"),
        "claude_skills_dir": str(tmp_path / "cs"),
        "codex_skills_dir": str(tmp_path / "xs"),
        "antigravity_skills_dir": str(tmp_path / "as"),  # doesn't exist yet
        "antigravity_enabled": False,
    }
    syncer = Syncer(dict(config_two_tool))
    _write_skill(Path(syncer.claude_skills_dir), "fmt")
    syncer.sync_once()

    # State currently has {claude, codex} only.
    _, entry = _the_only_pair(syncer)
    assert set(entry["agentic_tools"].keys()) == {"claude", "codex"}

    # Now provision the antigravity dir and re-enable.
    (tmp_path / "as").mkdir()
    config_three_tool = dict(config_two_tool)
    config_three_tool["antigravity_enabled"] = True
    syncer2 = Syncer(config_three_tool)
    syncer2.sync_once()

    _, entry2 = _the_only_pair(syncer2)
    assert set(entry2["agentic_tools"].keys()) == {"claude", "codex", "antigravity"}
    ag_path = Path(entry2["agentic_tools"]["antigravity"]["path"])
    assert (ag_path / "SKILL.md").exists()


# ---------- §5.5 reconciliation across 3 tools ----------

def test_three_tool_new_duplicate_with_drifted_content_merges(syncer: Syncer):
    """The same name on all 3 tools, drifted content. argmax(mtime) wins;
    every other tool's bytes archived under the merged pair_id."""
    cs_dir = _write_skill(Path(syncer.claude_skills_dir), "demo", description="claude-version")
    xs_dir = _write_skill(Path(syncer.codex_skills_dir), "demo", description="codex-version")
    ag_root = Path(syncer.config["antigravity_skills_dir"])
    ag_dir = _write_skill(ag_root, "demo", description="antigravity-version")
    _set_skill_mtimes(cs_dir, 1000.0)
    _set_skill_mtimes(xs_dir, 2000.0)
    _set_skill_mtimes(ag_dir, 3000.0)

    syncer.sync_once()

    pair_id, entry = _the_only_pair(syncer)
    assert set(entry["agentic_tools"].keys()) == {"claude", "codex", "antigravity"}
    # Antigravity won (latest mtime); all three converge to "antigravity-version".
    for tool in ("claude", "codex", "antigravity"):
        path = Path(entry["agentic_tools"][tool]["path"]) / "SKILL.md"
        assert "antigravity-version" in path.read_text()
    # Losers' bytes archived.
    assert _archive_files(syncer, pair_id, "claude")
    assert _archive_files(syncer, pair_id, "codex")


def test_mixed_first_boot_library_ABCD(syncer: Syncer):
    """Plan §5.5 mixed library: Claude {A, B}, Codex {B, C}, Antigravity {C, D}.

    After one poll: 4 managed pairs (A, B, C, D), each present on all 3 tools.
    B resolved between claude and codex; C resolved between codex and antigravity;
    A and D adopted as singletons. No collision blocks. No skills lost.
    """
    claude_root = Path(syncer.claude_skills_dir)
    codex_root = Path(syncer.codex_skills_dir)
    antigravity_root = Path(syncer.config["antigravity_skills_dir"])

    _write_skill(claude_root, "A", description="A-claude")
    b_claude = _write_skill(claude_root, "B", description="B-claude")
    b_codex = _write_skill(codex_root, "B", description="B-codex")
    c_codex = _write_skill(codex_root, "C", description="C-codex")
    c_ag = _write_skill(antigravity_root, "C", description="C-ag")
    _write_skill(antigravity_root, "D", description="D-ag")
    # B: codex newer; C: antigravity newer.
    _set_skill_mtimes(b_claude, 1000.0)
    _set_skill_mtimes(b_codex, 2000.0)
    _set_skill_mtimes(c_codex, 1000.0)
    _set_skill_mtimes(c_ag, 2000.0)

    syncer.sync_once()

    state = _read_state(syncer)
    pairs = state["customization_artifacts"]
    assert len(pairs) == 4, f"expected 4 managed pairs, got {len(pairs)}"

    # Every pair must be present on every tool.
    by_name: dict[str, dict] = {}
    for entry in pairs.values():
        claude_path = Path(entry["agentic_tools"]["claude"]["path"]) / "SKILL.md"
        text = claude_path.read_text()
        # Pull "name: X" from frontmatter to map back.
        for line in text.splitlines():
            if line.startswith("name:"):
                key = line.split(":", 1)[1].strip()
                by_name[key] = entry
                break

    assert set(by_name.keys()) == {"A", "B", "C", "D"}
    for name, entry in by_name.items():
        assert set(entry["agentic_tools"].keys()) == {"claude", "codex", "antigravity"}

    # B converged to codex content (codex won mtime); C converged to antigravity content.
    b_claude_text = (Path(by_name["B"]["agentic_tools"]["claude"]["path"]) / "SKILL.md").read_text()
    assert "B-codex" in b_claude_text
    c_claude_text = (Path(by_name["C"]["agentic_tools"]["claude"]["path"]) / "SKILL.md").read_text()
    assert "C-ag" in c_claude_text


# ---------- agent customization_type is Claude-only in v0.4 ----------

def test_agent_customization_type_is_claude_only(syncer: Syncer):
    """In v0.4, only claude supports the agent customization_type. Codex
    uses a single AGENTS.md file (not per-agent files), and Antigravity
    has no stable per-agent format. A claude agent adopts with paths
    containing only claude — no codex or antigravity projection."""
    claude_md = Path(syncer.claude_agents_dir) / "foo.md"
    claude_md.write_text("---\nname: foo\ndescription: x\n---\nbody\n")

    syncer.sync_once()

    _, entry = _the_only_pair(syncer)
    assert entry["customization_type"] == "agent"
    assert set(entry["agentic_tools"].keys()) == {"claude"}
    # Neither codex nor antigravity skills dir gets touched by the agent flow.
    assert list(Path(syncer.codex_skills_dir).iterdir()) == []
    assert list(Path(syncer.config["antigravity_skills_dir"]).iterdir()) == []
