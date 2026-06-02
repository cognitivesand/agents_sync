# State-Dir Size Explosion — Root-Cause Analysis

**Status:** investigated; remediation pending.
**Affected:** daemon discovery/adoption loop. Observed on an `agents-sync` 0.5.x
daemon; the failure *engine* still exists in 0.6.0 (mitigated, not removed).
**Scope of this doc:** the chain by which a single malformed customization file
caused the state directory to grow to tens of GB with millions of archive
directories, a multi-GB resident daemon, and a systemd crash loop.

> All paths below use `~` for the user home. Specific `pair_id` UUIDs and the
> host name are replaced with placeholders. No credentials or secrets were
> involved in this bug or this analysis.

---

## 1. Observed symptoms

A long-running daemon (poll interval `2.0 s`) was found in this state:

| Symptom | Measured |
|---|---|
| State dir total size | ~56 GB |
| `archive/` immediate child dirs (one per `pair_id`) | 1,650,961 |
| Daemon resident memory (RSS) | ~3.9 GB |
| `Target collision` ERROR log lines (one boot) | 6,082,779 |
| `state.json` schema | 3 (pre-canonical-truth) |
| Managed pairs in `state.json` / canonical docs | 7 / 10 |

After upgrading the same machine to 0.6.0 and restarting, the daemon:

- migrated `state.json` schema 3 → 4 cleanly,
- held RSS flat at ~27 MB,
- did **not** re-grow the archive (stayed at single/low-double digits),
- but **could not sync**: every poll reported `failed=3 blocked=49`, and after
  5 consecutive failed polls the process exited (`daemon.py`), so systemd
  restarted it repeatedly (observed `NRestarts=11`) — a crash loop.

So 0.6.0 fixed the memory bloat and the silent multi-GB archiving, but the
underlying *engine* (below) was still running; it simply blocked instead of
archiving.

---

## 2. Trigger (external, not a tool defect)

One skill's `SKILL.md` had **invalid YAML frontmatter**: `description:` was an
unquoted block scalar whose text contained `": "` (a colon-space), e.g.

```
description: ... write-stories (which authors/audits structure): this skill subtracts. ...
```

`ruamel.yaml` rejects this with `mapping values are not allowed here`. The file
was authored outside `agents-sync`.

This is **not** a serializer/round-trip defect: the daemon emits frontmatter via
`markdown_yaml_metadata_block.yaml_dump` (ruamel round-trip mode, `preserve_quotes`),
which quotes such values automatically. The tool can read back anything it
writes. The damage came entirely from how discovery/adoption *reacts* to a file
it cannot parse.

---

## 3. Root causes (grounded in 0.6.0 source)

### RC-1 — Amnesiac re-mint of never-adoptable artifacts (the engine)

`src/agents_sync/discovery/enumerator.py` (`_add_agentic_tool_artifact`, and the
keyed-map slot twin `_add_keyed_map_slot_artifact`):

```python
pair_id = io.extract_pair_id(text)
...
if pair_id is None:
    pair_id = self.state_owner_for_path(path, state)
    if pair_id is None:
        pair_id = new_pair_id()        # <-- fresh random id, no memory
```

When a file yields **no embedded `pair_id`** and has **no state owner**, the
walker mints a brand-new random id. There is no record that this path was seen
before, so an artifact that can *never* be adopted (its YAML will not parse, so
it never gets written back with an id and never enters state) is assigned a
**new identity on every poll** — once every 2 s, indefinitely.

### RC-2 — Identity recovery only works if a `pair_id:` line already exists

`src/agents_sync/markdown_yaml_metadata_block.py` (`extract_pair_id_from_md`):

```python
try:
    loaded = yaml_load(block)
except YAMLError:
    # FR-11: recover our own id tag in isolation when YAML is malformed
    isolated = _PAIR_ID_LINE_RE.search(block)
    return isolated.group("id") if isolated else None
```

The isolated-line recovery saves identity **only when a `pair_id:` line is
present**. For a file that is *both* malformed YAML *and* has no `pair_id` yet
(a freshly authored skill that never successfully adopted), this returns
`None` — which feeds RC-1's `new_pair_id()` path. This is the exact combination
the trigger file was in.

### RC-3 — Unbounded blocked-churn: no backoff, no dedup, no quarantine

`src/agents_sync/discovery/collision_blocker.py`:

```python
for pair_id in blocked:
    discovery.pop(pair_id, None)        # dropped this poll …
```

Blocked pairs (collision or parse-failure-at-planning) are logged at ERROR
(`_detect_multi_pair_collisions`, `_collect_targets_and_detect_collisions`) and
popped — then re-discovered and re-blocked on the next poll, forever. There is
no "seen-bad → quarantine and warn once" path, so a steady-state fault emits an
identical ERROR line every poll (hence ~6 M lines) and burns CPU continuously.

### RC-4 — Crash-loop on sustained failure (no artifact isolation)

`src/agents_sync/daemon.py`:

```python
if result.failed:
    consecutive_failures += 1
...
if consecutive_failures >= max_consecutive_failures:   # default 5
    logging.error("Exiting after %d consecutive failed polls; ...")
    exit_code = 1
    break
```

A single unresolvable artifact (e.g. refusing to overwrite an unowned target)
makes `result.failed > 0` every poll, so the **whole daemon** exits after 5
polls and the supervisor restarts it — a crash loop. There is no isolation that
would let the healthy artifacts keep syncing while one poisoned artifact is
quarantined. (Note: `blocked` does *not* increment `consecutive_failures` — only
`failed` does — which is why a parse-failure churns silently while an
unowned-target failure crash-loops.)

### RC-5 — Archive growth has no ceiling or GC (the 56 GB)

`src/agents_sync/adoption/canonical_projection.py`:

```python
self._archive_existing_tool_bytes(pair_id, info.kind, tool, info)
```

Archiving happens per projection, into `~/.local/state/agents-sync/archive/<pair_id>/<tool>/…`.
Under the **old 0.5.x daemon**, RC-1's per-poll re-minting fed the
projection+archive path with a new `pair_id` each time, with no dedup and no
cap → 1,650,961 archive directories / ~56 GB. There is no retention policy,
size cap, or garbage collection on the archive tree, so nothing structurally
bounds this growth.

In 0.6.0 the re-minted pairs are *blocked* before projection, so they no longer
reach the archive path (observed: archive stayed tiny). The explosion is
therefore mitigated in 0.6.0 — but the absence of a cap/GC means the failure
mode is not prevented, only made harder to reach.

---

## 4. Causal chain

```
malformed YAML frontmatter (no pair_id line)
        │  extract_pair_id_from_md -> None            (RC-2)
        ▼
discovery mints new_pair_id() every poll             (RC-1)
        │
        ├─ adoption planning re-parses -> YAMLError -> "blocked"
        │        │  logged ERROR + popped, re-seen next poll, forever   (RC-3)
        │        ▼
        │   (0.5.x) projection archived displaced bytes per minted id
        │        ▼
        │   archive/<new id>/... accumulates, unbounded   (RC-5)  -> 56 GB, 3.9 GB RSS
        │
        └─ a *separate* unresolvable artifact (unowned rules target)
                 makes failed>0 every poll -> 5 fails -> daemon exits -> systemd loop  (RC-4)
```

---

## 5. Remediation plan (proposed)

| RC | Non-regression test | Detection / warning | Remediation |
|----|---------------------|---------------------|-------------|
| RC-1 | an unparseable, id-less artifact gets a **stable** identity (or none), never a fresh id per call | — | derive a deterministic id from the path, or quarantine, instead of `new_pair_id()` |
| RC-2 | malformed-YAML + no `pair_id` line ⇒ quarantined, not re-minted | — | after K failed reads of a path, quarantine it |
| RC-3 | a repeated block/parse failure logs **once**, not every poll | rate-limited / de-duplicated error logging + periodic summary; `quarantined_count` in daemon status | dedup error logging; maintain a quarantine set keyed by path |
| RC-4 | one poisoned artifact does not fail the whole poll; other artifacts still sync | daemon status surfaces quarantined artifacts | isolate the bad artifact; exclude quarantined artifacts from the consecutive-failure counter |
| RC-5 | a never-adoptable artifact produces a **bounded** number of archive entries | warn when `archive/` exceeds N entries or M bytes; warn on rapid growth rate | archive retention/cap + garbage collection |
| trigger | round-trip: a `description` containing `": "` and quotes survives `yaml_dump` → `yaml_load` | — | none (serializer already safe); the test locks the guarantee |

### Design questions to settle before coding

1. Quarantine threshold: how many consecutive failed reads/adoptions of a path
   before it is quarantined and stops being re-processed.
2. Keep or change the unconditional 5-failed-poll exit in `daemon.py` — should
   quarantined artifacts be excluded from the counter so the daemon stays up.
3. Archive retention policy: max age, max entries, or max bytes; and whether GC
   runs in the daemon or as a separate maintenance command.

---

## 6. Remediation for an already-exploded machine

If a state dir has already grown unbounded:

1. Stop the daemon.
2. Back up `state.json` and `canonical/` (small — the source of truth).
3. Delete the `archive/` tree to reclaim space (it is recovery-only data).
4. Fix or remove the malformed source file so it parses.
5. Restart and confirm a steady-state poll of `changed=0 failed=0 blocked=0`.
