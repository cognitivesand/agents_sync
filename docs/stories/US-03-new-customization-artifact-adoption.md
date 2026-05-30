# US-03: Adoption and reconciliation of new customization artifacts across agentic_tools

## Persona

Both

## User Story

As a user who sometimes creates customizations directly in my agentic_tools — or who already has some in several tools before installing `agents_sync` — I want them picked up automatically and any duplicates merged into one synced copy, so I never have to adopt them by hand or end up with conflicting versions.

## Priority

Must Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`.

## Acceptance Criteria

### Single-agentic_tool adoption

- [ ] AC-1 [Normal]: Given a new customization artifact appears on exactly one participating agentic_tool (no counterpart exists on any other participating agentic_tool), When the watcher polls, Then within at most two polls: a fresh UUIDv4 `customization_artifact_id` is injected into that artifact, a canonical record is created, the original (pre-injection) bytes are archived under `archive/<customization_artifact_id>/<agentic_tool_name>/<original-filename>.<ISO-timestamp>`, and a counterpart is rendered on every other participating agentic_tool.
- [ ] AC-2 [Normal]: Given an artifact that already carries a `customization_artifact_id` and has a canonical record in state, When the watcher polls, Then the artifact is not re-adopted, no new `customization_artifact_id` is minted, and no archive entry is written.

### Multi-agentic_tool reconciliation

- [ ] AC-3 [Normal — duplicates merge by mtime]: Given new customization artifacts exist on two or more participating agentic_tools with the **same** reconciliation key `(customization_type, target_slug(name))`, When the watcher polls, Then the new customization artifacts are merged into a single new managed customization_artifact, as follows:
  - a fresh `customization_artifact_id` is minted;
  - the agentic_tool with the most recent `mtime` over the group is chosen as the **winner**;
  - every involved agentic_tool's pre-merge bytes are archived under the new `customization_artifact_id` (the winner's bytes are archived too, because they are about to be re-written with the new id injected);
  - the new id is injected into the winner's bytes;
  - the canonical is rendered to every loser agentic_tool, overwriting the loser's new customization artifact in place;
  - state is written with all involved agentic_tools recorded.

- [ ] AC-4 [Normal — non-duplicates adopted independently]: Given new customization artifacts on multiple agentic_tools with **different** reconciliation keys, When the watcher polls, Then each `(customization_type, target_slug(name))` group is processed independently per AC-1 or AC-3 with no cross-group interaction. The total number of managed customization_artifacts created equals the number of distinct reconciliation keys observed in the set of new artifacts this poll.

- [ ] AC-5 [Normal — union end state on first-boot library]: Given a first-boot library in which the user has been maintaining skills independently on multiple agentic_tools (e.g. agentic_tool X has skills `{A, B}`, agentic_tool Y has skills `{B, C}`, agentic_tool Z has skills `{C, D}`, all new), When the watcher polls, Then the end state is exactly four managed customization_artifacts (`A`, `B`, `C`, `D`), each present on every participating agentic_tool; `B` and `C` are resolved by mtime per AC-3 between their respective duplicate agentic_tools; `A` and `D` are adopted per AC-1; no skill is dropped; no collision block is raised.

- [ ] AC-6 [Normal — new + already-managed at same key]: Given a new customization artifact on one agentic_tool and an already-managed customization_artifact (with an existing `customization_artifact_id`) on one or more other agentic_tools with the same reconciliation key as the new customization artifact, When the watcher polls, Then the managed customization_artifact wins, as follows:
  - the new customization artifact's bytes are archived under the **existing** `customization_artifact_id` and the new artifact's agentic_tool name;
  - the canonical (from the managed customization_artifact) is rendered to overwrite the new customization artifact;
  - no new `customization_artifact_id` is minted;
  - the new artifact's agentic_tool is added to the managed customization_artifact's state entries.

- [ ] AC-7 [Normal — mtime tiebreaker]: Given an `mtime` tie at one-second precision among the duplicates of an AC-3 merge, When the watcher selects the winner, Then a deterministic tiebreaker by agentic_tool `name` (lexicographic ascending, after Unicode normalisation and case-folding) is applied, and a `WARN tied-mtime` log line names every tied agentic_tool and the chosen winner.

### Failure modes

- [ ] AC-8 [Failure — different customization_artifact_ids at same slug]: Given two or more **already-managed** artifacts on different agentic_tools carry **different** `customization_artifact_id` values but resolve to the same reconciliation key (a slug collision across customization_artifacts that should not exist), When the watcher polls, Then adoption, reconciliation, and sync are all aborted for the colliding customization_artifacts, every involved artifact is left untouched, and a structured error names every colliding `customization_artifact_id` and agentic_tool. User remediation is required (rename one of the conflicting artifacts on its source agentic_tool).

- [ ] AC-9 [Failure — archive write fails]: Given the archive write fails (permission denied, disk full, etc.) at any point during single-agentic_tool adoption or multi-agentic_tool reconciliation, When the tool attempts to archive, Then the destructive step that triggered the archive is aborted, every involved artifact retains its current bytes, and a structured error is logged. The next poll re-attempts.

- [ ] AC-10 [Failure — malformed new customization artifact]: Given a new customization artifact whose artifact metadata is malformed or missing the required `name` field, When discovery encounters it, Then the artifact is skipped (not adopted, not reconciled, not used to block any other reconciliation), and a structured warning names the agentic_tool, the path, and the underlying parse error.

- [ ] AC-11 [Failure — managed customization artifact became malformed]: Given an **already-managed** customization artifact whose on-disk artifact metadata has become malformed or unparseable (e.g. invalid YAML frontmatter) while its `customization_artifact_id` tag is still present and well-formed, When discovery encounters it, Then the artifact's owning `customization_artifact_id` is **frozen** — not reconciled, not synced, and **not interpreted as a removal** (no removal is propagated to other agentic_tools) — and a structured warning names the agentic_tool, the path, and the underlying parse error, until the user repairs the metadata.

## Notes

Reconciliation runs **between** discovery and per-customization_artifact processing, on the set of new customization artifacts only. It groups new customization artifacts by reconciliation key and decides each group in isolation. The total number of managed customization_artifacts after reconciliation equals the number of distinct keys observed across all new customization artifacts that poll, plus the count of already-managed customization_artifacts that were not absorbed under AC-6.

Last-mtime-wins is the project's stated conflict policy (see US-06). Field-level merge of differing artifact metadata or body content across duplicates is deliberately **not** attempted — the losers' bytes are recoverable from the archive, and field-merge would diverge from US-06's deterministic tiebreaker semantics.

The merge path under AC-3 archives every involved agentic_tool's bytes, **including the winner's**, because the winner's pre-injection content is about to be replaced by a version with the new `customization_artifact_id` injected. This makes the archive contract uniform: every byte that was on disk just before the merge is preserved in `archive/<customization_artifact_id>/<agentic_tool_name>/`. Recovery: if a user disagrees with a mtime outcome, the losing content is recoverable from the archive directory and can be re-applied manually.

This story is the only point at which the tool writes a `customization_artifact_id` into a previously untouched user file. The data-preservation rule (US-05) mandates archiving before injection — no exception.

There is no special "first-run mode": every poll runs the same discover → reconcile → process sequence. The N-agentic_tool reconciliation under AC-3 / AC-4 / AC-5 is what makes "first boot with pre-existing artifacts on every agentic_tool" converge cleanly to one managed customization_artifact per distinct logical artifact.

Related requirements: FR-02 (fault isolation across reconciliation groups), NFR-01 (data preservation during merge), NFR-07 (bounded archive growth — every loser's bytes archived once).
