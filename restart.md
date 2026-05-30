# Restart — 2026-05-29

> Last updated by Claude at 2026-05-29T21:27:33Z. Session-handoff snapshot.
> A fresh session reading this + the docs in section 1 should be able to resume
> without further explanation.

## 0. Git pin (do not edit by hand)

- `head_sha`: bb88865476f2ca3c297d9b111a4df881cdb2d1c3
- `head_short`: bb88865
- `branch`: fix/v0.5-unconfigured-root-extend-crash
- `dirty`: false
- `dirty_summary`: clean
- `remote_head`: 8424378 (upstream inherited from origin/feat/v0.5-plan; this
  branch is not yet pushed under its own name — see section 3.5)
- `saved_at`: 2026-05-29T21:27:33Z

## 1. Read these first

No `AGENTS.md` / `CLAUDE.md` at repo root (the project has none). Read, in order:

- `docs/project_description.md` — glossary + scope
- `docs/project_requirements.md` — FR/NFR (FR-07 rules matrix, FR-10 filename detection, NFR-06 round-trip)
- `docs/architecture.md`
- `docs/stories/US-11-graceful-agentic_tool-absence.md` — availability/removal semantics (directly relevant to the crash fix)
- `docs/stories/US-14/US-15/US-16-*.md` — global-rules work (US-15 = @import + framework guard, shipped on a different branch)

## 2. Working context (non-obvious, not in the docs)

- **The systemd user service `agents-sync.service` runs the EDITABLE install =
  the repo working tree.** So the live daemon executes whatever branch is
  currently checked out. Switching branches changes what the daemon runs.
  Right now it runs the fix branch and is healthy.
- **Live daemon config:** `~/.config/agents-sync/config.toml` configures only
  claude + codex `agents`/`skills`. No `rules` roots are configured, so the
  global `rules` pair has zero participating tools and is inert (no crash, no
  sync) after the fix.
- **Authoritative participation predicate:** `ToolStatusTracker.is_kind_available(tool, kind)`
  ("tool has a usable root for this kind"). The crash fix switched the engine +
  discovery planner from tool-level `is_available` to this. The discovery
  *walker* already used it.
- For shared-keyed-map (mcp_server) cells, `config_dir_keys[kind] == shared_path_config_key`,
  so kind-availability covers the shared key — that's why the cb8e35d band-aids
  were safe to delete.
- **Snapshot of current customizations:** `~/agents-sync-snapshot-20260529-2302.zip`
  (5 artifacts, v0.5.0, `contains_secret_literals: false`).
- **Open PRs:** #41 (`docs/v0.5-rules-us14-phase2` → `feat/v0.5-plan`: US-15
  @import + framework guard, US-14 done, US-16 scoped); #14 (`feat/v0.5-plan` →
  `main`, the v0.5 umbrella, parked). The crash-fix PR is being opened into
  `feat/v0.5-plan` (section 3.5).
- Global policy reminders: never `rm` (archive instead); git commits use the
  GitHub noreply alias, never a real email.

## 3. Active task

### 3.1 Goal
Have a healthy v0.5 `agents_sync` daemon running on this machine, and land the
fixes it surfaced.

### 3.2 Constraints
- Hard: daemon syncs REAL `~/.claude` / `~/.codex` dirs — changes there are
  outward-facing. Never `rm`. Commits use noreply email.
- Soft: clean fixes over band-aids (kind-level predicate, not scattered None checks).
- Out of scope (done elsewhere): US-15 @import work is PR #41, not this branch.

### 3.3 Status — done
- Diagnosed + fixed the daemon crash loop (unconfigured-root `TypeError` in the
  extend/project path). Branch `fix/v0.5-unconfigured-root-extend-crash` off
  `feat/v0.5-plan`, commit bb88865: kind-level participation in engine +
  discovery planner, deleted dead cb8e35d band-aids, added `UnconfiguredRootError`
  guardrail in `render_to_agentic_tool`, regression test
  `tests/test_unconfigured_root_extend.py`. Full suite 477 green, mypy/ruff clean.
- Restarted `agents-sync.service`; verified healthy: `Active: active (running)`,
  `failed=0`, no crash. (Was crash-looping with `failed=1`.)
- Exported the snapshot zip (see section 2).

### 3.4 Status — in progress
Working tree clean at bb88865. About to commit this restart.md, push the fix
branch, and open its PR (section 3.5).

### 3.5 Next concrete step
Push `fix/v0.5-unconfigured-root-extend-crash` (`git push -u origin HEAD`) and
open a PR into `feat/v0.5-plan` for the crash fix.

### 3.6 Open questions
None blocking.

## 4. Other tasks queued behind the active one

1. **Investigate the 48 blocked / ~80 duplicate-pair_id target collisions** — medium.
   - The healthy daemon now reports `blocked=48` every poll (graceful, NOT a
     crash): the collision-blocker refuses to clobber because multiple `pair_id`s
     map to the same target path.
   - Symptom: skills like `python-runner`, `user-questions`, `write-requirements`,
     `write-stories` each have **two** `pair_id`s competing for the same path
     across tools, e.g. `~/.cursor/skills/python-runner`, `~/.gemini/skills/...`,
     `~/.codex/skills/user-questions`, `~/.copilot/skills/...`. Those skills are
     stuck not syncing.
   - Goal: find **why** those skills have duplicate pair_ids (likely the same
     skill was independently adopted/minted on more than one tool, or a slug
     collision across distinct pair_ids) and how to reconcile/dedupe them.
   - Where to look: live state `~/.local/state/agents-sync/state.json`; the
     collision-blocker (`src/agents_sync/discovery/collision_blocker.py`) and the
     ERROR log lines `journalctl --user -u agents-sync.service | grep "Target collision"`;
     cross-reference with the snapshot zip's canonical/*.json.
   - Why queued: separate, pre-existing data/state issue; not a crash; deferred
     until after the crash fix lands.

2. **Land the v0.5 line to main** — small/coordination.
   - Merge order: crash-fix PR → `feat/v0.5-plan`; PR #41 → `feat/v0.5-plan`;
     then PR #14 (`feat/v0.5-plan` → `main`, awaiting user go-ahead).

## 5. Files touched this session (skim list)

- `src/agents_sync/rendering.py` [edited] — UnconfiguredRootError + guard
- `src/agents_sync/adoption/engine.py` [edited] — kind-level participation; deleted band-aid
- `src/agents_sync/discovery/adoption_planner.py` [edited] — kind-level participation; deleted band-aids
- `tests/test_unconfigured_root_extend.py` [created] — regression test
- `~/.config/agents-sync/config.toml` [read], `~/.local/state/agents-sync/state.json` [read]
- (On branch `docs/v0.5-rules-us14-phase2`, PR #41: rules_io.py, _rules_factory.py,
  privacy_gate.py, US-14/15/16 stories, test_rules_import_resolution.py — not this branch.)

## 6. Anything else the next session needs to know

- 2026-05-29 (passed-in note): the headline queued task is the duplicate-pair_id
  collision investigation (section 4 item 1). The crash fix it follows is on
  `fix/v0.5-unconfigured-root-extend-crash` (PR into `feat/v0.5-plan`); the daemon
  is currently healthy via `agents-sync.service` (editable install = working
  tree); snapshot at `~/agents-sync-snapshot-20260529-2302.zip`.
- The live daemon tracks the checked-out branch (editable install). If you switch
  branches for the investigation, the running daemon switches code with you —
  check `systemctl --user is-active agents-sync.service` after branch changes.
