# Amendment 019 — US-13 AC-4: retire the user-facing `private` flag (YAGNI)

- status: applied
- branch: fix/size-explosion-hardening
- date: 2026-06-08
- relates to: US-13 AC-4 + Notes; US-15 AC-7 + design notes (de-reference only,
  framework-specific behaviour unchanged); architecture proposal §4, §7, §12;
  implementation plan S8 row; `src_new/.../canonical_document.py`.

## Motivation

The user does not need a per-artifact "keep this local" flag. Tracing every
consumer of `private` confirms it is a **pure user-facing propagation/adoption
gate** with no internal dependency: the adapters (`copilot_io`, `rules_io`)
merely surface a user-authored `private:` frontmatter key; `sync.py`,
`adoption_planner.py`, and `privacy_gate.py` skip propagation/adoption when it is
set. No internal invariant — loop suppression/convergence, archiving, GC,
identity/mint, round-trip fidelity — reads it. Secret handling (NFR-15) does not
depend on it either: the `mcp_secret_policy` `private[_-]?key` token is a
secret-*value* regex, unrelated to the flag. With no user need and no internal
need, `private` is YAGNI.

## Principle / decision

Remove the user-facing `private` flag and its gate; sync ignores any `private:`
field. `private` and `framework_specific` are **separate** flags that only shared
a gate (`if is_private(canonical) or canonical.get("framework_specific")`):
`framework_specific` is a *derived* leak-prevention flag (US-15) that stops a
tool-private path in one tool's global-rules file from polluting another tool. It
is **unaffected** — the framework-specific clause simply stands alone.

## Governance edit (validated by the user)

### User stories — US-13 AC-4
The AC is retired (number kept, not renumbered): "The user-facing `private` flag
is removed. Artifacts are synced regardless of any `private:` field; no
propagation/adoption gate is keyed on it." The US-13 Notes sentence naming the
`private` field as load-bearing and listing its sources is removed; the
`provenance` note is retained.

### User stories — US-15 (de-reference only)
AC-7 and the "Guard mechanism" design note no longer describe the
framework-specific guard "as a `private` artifact" — the behaviour is unchanged,
the comparison to the removed flag is dropped.

## Design edits (applied after)

- Proposal §4: `private` removed from the planner's reasoning list.
- Proposal §7 step 4: the projection guard is now "framework-specific content →
  no projection (US-15)" only.
- Proposal §12: the "Privacy (`private: true`)" row is removed.
- Implementation plan S8 row: `private/framework predicates` dropped; S8 is the
  four cross-artifact guards; framework-specific projection hold-back stays at S12
  with its read-phase flag.

## Verification

Rebuild: the premature `private` field is removed from
`src_new/.../canonical_document.py` and its round-trip test assertion. The old
`src/` plumbing and `tests/test_privacy_gate.py` remain green until cutover (S25),
where the orphaned `private` code retires with the rest of the superseded modules.
