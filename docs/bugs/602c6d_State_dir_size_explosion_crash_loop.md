# 602c6d — State dir size explosion crash loop

**Status:** phases 1–3 complete (root causes verified, tests defined); phase 4+
pending.
**Flow:** `bug_remediation` skill (Poirot/Columbo investigate, Freedman plans,
Kitano tests).
**Branch:** `fix/size-explosion-hardening`.

> Paths use `~`; host name and concrete `pair_id` UUIDs are placeholders. No
> credentials or secrets were involved.

## Symptom

A long-running daemon (poll `2.0 s`) reached: state dir ~56 GB; `archive/` =
1,650,961 `pair_id` dirs; daemon RSS ~3.9 GB; 6,082,779 `Target collision`
ERROR lines in one boot; crash loop after the 0.6.0 upgrade (`NRestarts=11`).
Trigger: one skill whose `SKILL.md` had invalid YAML frontmatter — an unquoted
`description:` value containing `": "` (`…structure): this skill…`).

---

## 1. Root_causes_identification  *(Poirot)*

All causes traced to code; the trigger file is external (a user/author-written
skill), not produced by the tool.

- **RC-1 — amnesiac re-mint of id-less artifacts.**
  `discovery/enumerator.py` (`_add_agentic_tool_artifact` ~ll. 238-241; slot twin
  `_add_keyed_map_slot_artifact` ~ll. 137-140): when a file yields no embedded
  `pair_id` and has no state owner, it calls `new_pair_id()` — a fresh random id
  with no memory, on every discovery pass.
- **RC-2 — id recovery needs a `pair_id:` line to survive bad YAML.**
  `markdown_yaml_metadata_block.py::extract_pair_id_from_md` (ll. 282-291): on
  `YAMLError` it regex-recovers an isolated `pair_id:` line; with no such line it
  returns `None`, feeding RC-1.
- **RC-3 — blocked-churn with no dedup / backoff / quarantine.**
  `discovery/collision_blocker.py` (logs ERROR per collision; pops the pair; it
  is re-discovered and re-blocked next poll). Steady-state fault ⇒ identical
  ERROR every 2 s (the 6.08 M lines) + constant CPU.
- **RC-4 — crash-loop on sustained failure, no artifact isolation.**
  `daemon.py` (ll. 93-101): exits after 5 consecutive polls with `failed>0`;
  the supervisor restarts ⇒ loop. One unresolvable artifact downs the whole
  daemon. (`blocked` does not count toward this; only `failed`.)
- **RC-5 — archive growth has no cap or GC.**
  `adoption/canonical_projection.py` (l. 193) archives displaced bytes per
  projection under `archive/<pair_id>/…`; nothing bounds total size/age/count.
- **RC-6 (structural / DRY) — identity minting is duplicated across 19 sites.**
  `new_pair_id()` has one *definition* (`canonical.py:27`) but is *called* from
  19 places — every adapter `parse()`, both `enumerator.py` discovery sites, and
  `empty_canonical`. There is no single chokepoint owning the mint-and-record
  invariant, so RC-1's "mint without recording" has 19 independent places to
  arise. The DRY mandate: one minting method **and** one minting *process*.

---

## 2. Root_cause_verification  *(Columbo)*

Probe: `tmp/probe_rc.py` (archived to `archive/` after this run) drives the real
`DiscoveryWalker` through a tmp-rooted `Syncer`. **The first probe was itself
wrong** — it called `discover()` without `tool_status.refresh()`, so the tool
read as unavailable and discovery returned empty (a false "no re-mint").
Corrected to mirror the daemon (`ensure_roots()` + `refresh()` before
`discover()`); evidence below is from the corrected probe.

| RC | Verdict | Evidence |
|----|---------|----------|
| RC-1 | **confirmed** | malformed/id-less skill minted a *different* id each pass (`1b572e32…` then `c27a8638…`); a skill *with* an embedded id stayed stable across both passes |
| RC-2 | **confirmed** | `extract_pair_id_from_md(malformed, no pair_id line)` → `None` |
| trigger | **external, not a serializer bug** | `yaml_load(yaml_dump({"description": "<value with ': '>"}))` round-trips equal — the tool quotes such values when it writes them |
| RC-3 | **confirmed** | re-mint each pass (above) + code: collision is logged at ERROR and popped every poll with no memory; matches the 6.08 M identical lines observed |
| RC-4 | **confirmed** | `daemon.py` exits at 5 consecutive `failed` polls; the live upgrade showed `NRestarts=11` driven by an unowned-target `failed=3` |
| RC-5 | **confirmed (0.5.x); mitigated (0.6.0)** | 56 GB / 1.65 M dirs observed on 0.5.x; on 0.6.0 the re-minted pair is blocked *before* projection, so archive stayed tiny — but no cap/GC exists, so the mode is unprevented |
| RC-6 | **confirmed** | `grep new_pair_id() src/` → 19 call sites across 13 adapters + 2 discovery sites + `empty_canonical`; one generator definition |

**Consequences / blast radius.** RC-1+RC-2+RC-3 form the engine: an unadoptable
artifact churns forever (CPU + log spam + a new identity each poll). On 0.5.x
that engine fed RC-5 (projection+archive per minted id) → the 56 GB / 1.65 M /
3.9 GB explosion. RC-4 is independent: a separate unresolvable artifact (an
unowned rules target) crash-loops the daemon.

**Wider class (the "have I seen this trick elsewhere?").**
- The *amnesiac-mint-and-churn* class covers both `enumerator.py` minting sites
  (per-file and keyed-map-slot) — same anti-pattern, two rooms. The adapter
  `new_pair_id()` sites (e.g. `claude_io.py`, `codex_io.py`, …) mint during
  *parse / first adoption*, which is legitimate **only because** adoption then
  persists the id; the defect is minting that is **never durably recorded**.
- RC-4 (no graceful degradation) and RC-5 (no resource cap) are individual
  structural gaps, not instances of the mint class.

**Gate:** met — every RC has reproducible evidence; the wider-class question is
answered.

---

## 3. Non_regression_tests_definition  *(Kitano)*

Two diagonally opposed means per root cause; a class-level test where a class
exists. Test module: `tests/test_size_explosion_regression.py` (marked
`integration` where it drives a `Syncer`).

- **RC-1**
  - `test_idless_artifact_keeps_stable_identity_across_discovery` — *white-box,
    in-process*: drive `discover()` twice on an id-less artifact; the assigned
    `pair_id` must be identical across passes (pins the internal invariant).
  - `test_unadoptable_skill_does_not_grow_identities_over_many_polls` —
    *black-box, end-to-end*: `sync_once()` N times over a malformed skill; the
    set of distinct `pair_id`s ever seen stays bounded (pins the outcome).
- **RC-2**
  - `test_extract_pair_id_recovers_id_from_malformed_yaml` — *example-based*:
    malformed YAML *with* a `pair_id:` line recovers the id (FR-11 path).
  - `test_extract_pair_id_never_fabricates_an_id` — *property-based* (Hughes):
    over generated frontmatter, the result is a present id or `None`, never a
    fabricated id.
- **RC-3**
  - `test_repeated_collision_logs_are_rate_limited` — *behavioural*: a steady
    collision over K polls emits a bounded number of ERROR lines, not K.
  - `test_unadoptable_path_is_quarantined_after_threshold` — *white-box*: after
    K failed passes a path is quarantined and stops being re-processed.
- **RC-4**
  - `test_one_poisoned_artifact_does_not_fail_whole_poll` — *behavioural*: a poll
    with one unresolvable artifact still projects the healthy ones and does not
    increment the crash-loop counter.
  - `test_consecutive_failure_counter_ignores_quarantined` — *white-box*.
- **RC-5**
  - `test_never_adoptable_artifact_creates_bounded_archive` — *end-to-end*.
  - `test_archive_gc_prunes_beyond_retention` — *unit*.
- **RC-6 / DRY**
  - `test_new_pair_id_has_single_caller` — *static white-box*: `new_pair_id()`
    is invoked from exactly one module/function (the identity-assignment
    process), not 19 sites.
  - `test_minting_routes_through_identity_service` — *behavioural*: identity is
    assigned only via the single process, which records as it mints.
- **class**
  - `test_no_discovery_path_mints_without_recording` — pins the mint-class: no
    discovery pass assigns an id that is neither recovered nor persisted.

**Gate:** met — ≥2 opposed means per RC + a class test, each tracing to an RC.

---

## 4. Non_regression_tests_validation  *(Kitano)* — pending

Implement the above and run against unfixed code; all must fail (red). Output
captured here once run.

---

## 5. Bug_remediation_plan  *(Freedman)* — draft

**Spine (DRY mandate): a single identity-assignment process.** One function is
the *sole* caller of `new_pair_id()`. It mints an id only at the moment the
artifact is durably recorded (first successful adoption / canonical write), and
**never on a bare discovery pass**. The 19 current call sites route through it or
are removed. This makes RC-1 structurally impossible (you cannot mint without
recording) and satisfies DRY / SRP / SoC.

Open design questions (need a decision before coding):
1. Where the single mint-and-record chokepoint lives (adoption engine vs a small
   `identity` service) and how discovery references an as-yet-unadopted artifact
   without minting (e.g. a path-derived provisional key).
2. Quarantine threshold: consecutive failed reads/adoptions of a path before it
   is quarantined and skipped (RC-3).
3. Whether quarantined artifacts are excluded from the crash-loop counter so the
   daemon stays up (RC-4).
4. Archive retention policy: max age / entries / bytes, and daemon vs separate
   maintenance command (RC-5).

## 6. Docs_update — pending
## 7. Code_correction — pending
## 8. Code_non_regression_testing — pending
