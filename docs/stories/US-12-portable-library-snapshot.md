# US-12: Customization library — export and import

## Persona

Alice

## User Story

As a power user who curates a library of agents and skills, I want to export my full customization library to a single transportable file and re-import it later — either to restore after a clean install or to seed another workstation — so that my library survives machine moves and can be shared without copying each agentic_tool's files by hand.

## Priority

Should Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`. The **customization library** is the full set of canonical documents the daemon manages. A **customization library export** packages this set as a single `.zip` file that another install can import.

## Acceptance Criteria

### Export

- [ ] AC-1 [Normal]: Given a state directory containing N canonical documents, When the user runs `agents-sync export <file.zip>`, Then a zip file is produced containing one entry per managed customization_artifact at `canonical/<customization_artifact_id>.json` plus a top-level `manifest.json` with `{schema_version, exported_at, source_host, source_platform, agents_sync_version, artifact_count, contains_secret_literals}`. The source state directory is unchanged.
- [ ] AC-2 [Normal]: Given the export runs concurrently with a live daemon, When the export completes, Then the zip contains a coherent point-in-time view (every entry corresponds to a single, atomic read of the canonical store at one moment) and no canonical document is partially written.
- [ ] AC-3 [Normal]: Given a managed customization_artifact, When it is written into the export, Then the in-archive copy carries a `last_modified` field whose value equals the artifact's `last_modified` stored in the local `state.json` (a floating-point POSIX timestamp set every time the canonical for that pair is updated by the daemon). The local canonical and `state.json` are not modified by the export.
- [ ] AC-4 [Failure]: Given the target file path is not writable (parent missing, permission denied, disk full), When `export` runs, Then the command aborts with a non-zero exit code and a structured error; no partial zip is left behind.

### Import

- [ ] AC-5 [Normal]: Given a zip produced by AC-1 and a fresh install (no managed customization_artifacts locally), When the user runs `agents-sync import <file.zip>`, Then every canonical document in the zip is written to the local state directory and `state.json` is updated with a state stub per imported customization_artifact; **import does not write to any agentic_tool root** — the next `sync_once` renders each imported customization_artifact onto every locally enabled, supporting, and `available` agentic_tool via the unchanged adoption pipeline. The command returns after the canonical store and `state.json` are durably written. That first `sync_once` performs the projection (it is not a no-op); every `sync_once` thereafter is a no-op per NFR-05, and no archive entries are created on a fresh install (no existing user-authored bytes were displaced).
- [ ] AC-6 [Normal]: Given the import zip carries a customization_artifact with the same `customization_artifact_id` as a locally-managed one, When `import` runs under the configured `import_collision_strategy`, Then the strategy is applied:
  - `skip`: the imported artifact is ignored; the local canonical is unchanged; a structured info log names the skipped `customization_artifact_id`.
  - `mtime_wins` (default): the candidate with the higher `last_modified` value replaces the loser. The local candidate's `last_modified` is read from the local `state.json`; the imported candidate's `last_modified` is the value carried in the zip. Ties are resolved in favour of the local artifact (default-deny on rewrite). If the import wins, the local canonical is overwritten and every agentic_tool's tool-side file is archived (NFR-01) before re-projection on the next poll. If the local wins, the imported artifact is ignored.
  - `overwrite`: the imported canonical replaces the local one unconditionally; every local tool-side file is archived (NFR-01) before re-projection.
- [ ] AC-7 [Normal]: Given the import zip carries a customization_artifact whose `target_slug(name)` collides with a *different* locally-managed artifact under the same `customization_type`, When `import` runs, Then the same `import_collision_strategy` is applied (treating the slug collision identically to a `customization_artifact_id` collision). The loser's bytes are archived per NFR-01 before any displacement.
- [ ] AC-8 [Normal]: Given an `import_collision_strategy` is provided on the CLI (`--collision-strategy {skip,mtime_wins,overwrite}`), When `import` runs, Then the CLI value takes precedence over the configured value.
- [ ] AC-9 [Failure]: Given the zip lacks `manifest.json`, or `manifest.schema_version` is greater than the local code's supported version, or any `canonical/<id>.json` file is unparseable or has an invalid `customization_artifact_id`, When `import` runs, Then the command aborts with a non-zero exit code and a structured error naming the offending entry; no canonical or state entry is created.
- [ ] AC-10 [Failure]: Given the import partially fails during canonical-file writes, When `import` runs, Then `state.json` is never updated and the local install retains exactly the customization_artifacts it had before the import. Orphan canonical files (canonicals without a state entry) may remain on disk; they are inert (the sync engine ignores canonicals without a state entry) and are overwritten by a subsequent successful import.

### Round-trip

- [ ] AC-11 [Normal]: Given an exported zip is immediately re-imported into the same install under any `import_collision_strategy`, When the import completes, Then the canonical store is bit-identical to before the export (a no-op round trip), no tool-side files are rewritten, and no archive entries are created.

### Secret handling at egress

The contract below is type-agnostic. Today only the `mcp_server` customization_type can carry literal secret material; future customization_types whose adapters declare secret-detection heuristics fall under the same rules without amendment.

- [ ] AC-12 [Normal]: Given `secret_policy = "secrets_refused"` and no canonical in the customization library contains literal secret material, When the user runs `agents-sync export <file.zip>`, Then every canonical is written to the export and the manifest field `contains_secret_literals` is `false`.

- [ ] AC-13 [Normal + Warning]: Given `secret_policy = "secrets_refused"` and at least one canonical in the customization library contains literal secret material (e.g. a stale canonical from before the policy was tightened), When the user runs `agents-sync export <file.zip>`, Then the export ships every clean canonical and **skips** every secret-bearing canonical; the daemon logs one structured WARNING per skipped artifact naming the `customization_artifact_id` and field path; the manifest field `contains_secret_literals` is `false`.

- [ ] AC-14 [Normal]: Given `secret_policy = "secrets_accepted"` and at least one canonical in the customization library contains literal secret material, When the user runs `agents-sync export <file.zip>`, Then literal secret material is included verbatim in the export, the manifest field `contains_secret_literals` is `true`, and the daemon logs one structured WARNING line listing the affected `customization_artifact_id`s.

- [ ] AC-15 [Normal + Warning]: Given an export carrying literal secret material is imported on a target install whose `secret_policy` is `secrets_refused`, When `agents-sync import` runs, Then every clean canonical is imported per AC-5 / AC-6 and every secret-bearing canonical is skipped with one structured WARNING per skipped artifact naming the `customization_artifact_id` and field path.

- [ ] AC-16 [Normal]: Given an export carrying literal secret material is imported on a target install whose `secret_policy` is `secrets_accepted`, When `agents-sync import` runs, Then every canonical is imported verbatim and the daemon logs one structured WARNING line listing the affected `customization_artifact_id`s.

### Cross-machine merge

- [ ] AC-17 [Normal — cross-identity merge]: Given an import zip in which two or more canonicals share the same `(customization_type, target_slug(name))` but carry **different** `customization_artifact_id`s (e.g. the same skill independently created on two machines), When `import` runs, Then they are reconciled into a **single** managed customization_artifact: the candidate with the higher wall-clock `last_modified` wins, ties favouring the locally-present artifact; when no candidate is locally present (a pure cross-host merge) and `last_modified` ties at stored precision, the candidate whose `customization_artifact_id` sorts first lexicographically wins — a deterministic last resort. The host-local `generation` counter is **not** used as a cross-host discriminator (clock skew across hosts is the user's responsibility, per US-06). The winner is written under its `customization_artifact_id`, and every **losing candidate's id is retired** — not written to the canonical store or `state` — with its bytes archived (NFR-01) under the winner's id. After import no two managed customization_artifacts share a slug (US-03 AC-8 is never provoked), and re-importing the same library is a no-op (FR-12, AC-11). This reconciliation is applied uniformly across the imported set and against local state.
- [ ] AC-18 [Normal — preview honesty]: Given an import that would merge or displace any local customization_artifact, When the user runs `agents-sync import`, Then a preview enumerates, **before any disk write**, every imported `customization_artifact_id` that will merge-by-slug or overwrite a local pair, including intra-import slug merges; under `overwrite`/`mtime_wins` the run requires `--force` if any local pair would be displaced.

## Notes

The export file format is `.zip` for cross-platform parity (Windows, macOS, Linux) and to allow inspection with native OS tools without installing anything. The export contains only the canonical store; it omits `state.json` (host-specific) and the on-disk `archive/` directory (local audit history, not portable library content). Tool-side files (`~/.claude/agents/…`, etc.) are not packaged — they are re-derived from the canonical by the normal sync loop on the target host.

`import` never writes to an agentic_tool root directly. It writes canonicals and state stubs only; the next polling cycle of the existing sync engine adopts them via the unchanged adoption / extension code path. This keeps the import logic agentic-tool-agnostic and ensures the imported artifacts pass through the same atomic-write discipline as any other write.

The `import_collision_strategy` default of `mtime_wins` mirrors the daemon's runtime conflict-resolution rule (US-06). Users who treat an export as authoritative restore data can switch to `overwrite`; users who treat it as supplementary can switch to `skip`. The strategy is per-install (config) and per-invocation (CLI flag).

AC-12 … AC-16 codify the cross-cutting NFR-15 contract (secret_policy applied at every artifact-egress boundary) at this story's two egress points. The defence-in-depth design: under `secrets_refused`, a stale or hand-edited canonical that still carries literal secret material is filtered at the egress boundary rather than aborting the entire export — the rest of the library still ships, and the operator gets a per-artifact warning naming the offender. The symmetric import-side filter (AC-15) means a `secrets_accepted` source host cannot bypass a `secrets_refused` target host.

Related requirements: NFR-01 (data preservation — AC-6, AC-7), NFR-03 (atomic visibility — AC-10), NFR-07 (bounded archive growth — AC-5), NFR-13 (structured errors — AC-4, AC-9, AC-13, AC-15), NFR-15 (secret handling — AC-12…16). Related stories: US-05 (archive), US-06 (conflict resolution), US-13 (customization-type expansion — parse-time secret_policy ACs).
