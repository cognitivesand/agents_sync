# US-06: Conflict resolution by last-modified time across N agentic_tools

## Persona

Both

## User Story

As a user who may occasionally edit the same customization in more than one agentic_tool between polls, I want the most recently saved version to win — with every other version safely archived first — so that conflicts resolve automatically and predictably, no matter how many tools held a copy.

## Priority

Should Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`.

## Acceptance Criteria

- [ ] AC-1 [Normal — N-way conflict resolution]: Given a managed customization_artifact with N ≥ 2 participating agentic_tools and ≥ 2 agentic_tools in the changed-agentic_tools set (meaning ≥ 2 agentic_tools were edited since the previous reconciliation), When the watcher polls, Then, in order:
  - the changed agentic_tool with the most recent `mtime` is chosen as the **winner**;
  - the canonical is updated from the winner's content;
  - every other changed agentic_tool (the **losers**) has its prior bytes archived under `archive/<customization_artifact_id>/<agentic_tool_name>/<original-filename>.<ISO-timestamp>`;
  - every loser is then overwritten with a render of the updated canonical.

- [ ] AC-2 [Normal — one-way propagation, not a conflict]: Given a managed customization_artifact with N ≥ 2 participating agentic_tools and exactly **one** agentic_tool in the changed-agentic_tools set, When the watcher polls, Then this is treated as one-way propagation (not a conflict): the canonical is updated from the changed agentic_tool and rendered to every other participating agentic_tool; no archive entry is written for the unchanged agentic_tools; no conflict log line is emitted.

- [ ] AC-3 [Normal — conflict logging]: Given a conflict resolution completes per AC-1, When it completes, Then a `WARN conflict resolved` log line is emitted naming the `customization_artifact_id`, the participating agentic_tools and their respective `mtime` values, the chosen winner agentic_tool, and the archive paths of every loser agentic_tool's prior bytes.

- [ ] AC-4 [Normal — mtime tiebreaker]: Given two or more agentic_tools in the changed-agentic_tools set have identical `mtime` at one-second precision, When the watcher resolves the conflict, Then a deterministic tiebreaker by agentic_tool `name` (lexicographic ascending, after Unicode normalisation and case-folding) is applied, and a `WARN tied-mtime` log line names every tied agentic_tool and the chosen winner.

- [ ] AC-5 [Normal — unavailable agentic_tool excluded]: Given an agentic_tool has `supported_customization_types` including the customization_artifact's customization_type but its current status (per US-11) is `unavailable`, When the watcher polls the customization_artifact, Then that agentic_tool is excluded from this poll's participating-agentic_tools set, the changed-agentic_tools computation, and projection. Its state entry for the customization_artifact is preserved unchanged.

- [ ] AC-6 [Failure — atomic across losers]: Given the archive write fails for any one loser agentic_tool during conflict resolution, When the tool attempts to overwrite any loser, Then **no** loser is overwritten on this poll (atomic across the loser set): every participating agentic_tool retains its current bytes, no state entry is mutated, and a structured error names the failing loser agentic_tool and the underlying cause. The next poll re-attempts.

## Notes

The 2-second default polling window makes simultaneous human edits to multiple agentic_tools extremely unlikely; this story exists primarily as a safety net rather than a frequently-hit code path. Conflict **detection** compares each participating agentic_tool's current digest against its own `last_written` digest in state (per-agentic_tool digests, not against `mtime`); `mtime` is used only as the tiebreaker once a divergence on ≥ 2 agentic_tools has been confirmed.

The pre-v0.4 deterministic tiebreaker hard-coded one specific agentic_tool as the winner. v0.4 generalises this to lexicographic agentic_tool `name` so the rule scales to any number of agentic_tools without hard-coding a specific winner. The lexicographic rule is also stable as new agentic_tools are added: a newly-registered agentic_tool participates in the tiebreaker by virtue of its `name` alone, with no algorithm change.

AC-6 specifies an atomic-across-losers semantic: the daemon does not partially overwrite some losers and skip others. Either every loser is archived-then-overwritten on this poll, or no loser is. This preserves the invariant that a customization_artifact is consistent across every participating agentic_tool after every successful poll.

For the special case where ≥ 2 agentic_tools carry **new** (no-`customization_artifact_id`) artifacts with the same reconciliation key — i.e. there is no managed customization_artifact yet to detect a conflict against — see US-03 AC-3, which applies the same mtime-wins-and-archive rule at adoption time.

Related requirements: NFR-01 (no loser bytes lost), NFR-02 (conflicts must resolve within polling latency), FR-01 (the propagated winner does not re-trigger as a new change).
