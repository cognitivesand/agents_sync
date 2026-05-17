# US-12: Portable library snapshot — export, restore, and share

## Persona

Alice

## User Story

As a power user who curates a library of agents and skills, I want to export the entire set as a single archive file and re-import it later — either to restore after a clean install or to seed another workstation — so that my library survives machine moves and can be shared without copying each agentic_tool's files by hand.

## Priority

Should Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`. A **portable library snapshot** is a single archive file (`.zip` container at v0.4.2) whose contents are sufficient, on a target install, to materialise every customization_artifact recorded in the source's canonical store.

## Acceptance Criteria

### Export

- [ ] AC-1 [Normal]: Given a state directory containing N canonical documents, When the user runs `agents-sync export <file.zip>`, Then a zip file is produced containing one entry per managed customization_artifact at `canonical/<customization_artifact_id>.json` plus a top-level `manifest.json` with `{schema_version, exported_at, source_host, source_platform, agents_sync_version, artifact_count}`. The source state directory is unchanged.
- [ ] AC-2 [Normal]: Given the export runs concurrently with a live daemon, When the export completes, Then the zip contains a coherent point-in-time snapshot (every entry corresponds to a single, atomic read of the canonical store at one moment) and no canonical document is partially written.
- [ ] AC-3 [Normal]: Given a managed customization_artifact, When it is written into the export, Then the in-archive copy carries a `last_modified` field whose value equals the artifact's `last_modified` stored in the local `state.json` (a floating-point POSIX timestamp set every time the canonical for that pair is updated by the daemon). The local canonical and `state.json` are not modified by the export.
- [ ] AC-4 [Failure]: Given the target file path is not writable (parent missing, permission denied, disk full), When `export` runs, Then the command aborts with a non-zero exit code and a structured error; no partial zip is left behind.

### Import

- [ ] AC-5 [Normal]: Given a zip produced by AC-1 and a fresh install (no managed customization_artifacts locally), When the user runs `agents-sync import <file.zip>`, Then every canonical document in the zip is written to the local state directory, every imported customization_artifact is rendered onto every locally enabled, supporting, and `available` agentic_tool via the same rendering pipeline used by adoption, and `state.json` is updated with the resulting paths and digests. The command returns only after every projection is on disk. Any subsequent `sync_once` is a no-op per NFR-05, and no archive entries are created (no existing user-authored bytes were displaced).
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

## Notes

The archive file format is `.zip` for cross-platform parity (Windows, macOS, Linux) and to allow inspection with native OS tools without installing anything. The export contains only the canonical store; it omits `state.json` (host-specific) and the on-disk `archive/` directory (local audit history, not portable library content). Tool-side files (`~/.claude/agents/…`, etc.) are not packaged — they are re-derived from the canonical by the normal sync loop on the target host.

`import` never writes to an agentic_tool root directly. It writes canonicals and state stubs only; the next polling cycle of the existing sync engine adopts them via the unchanged adoption / extension code path. This keeps the import logic agentic-tool-agnostic and ensures the imported artifacts pass through the same atomic-write discipline as any other write.

The `import_collision_strategy` default of `mtime_wins` mirrors the daemon's runtime conflict-resolution rule (US-06). Users who treat a snapshot as authoritative restore data can switch to `overwrite`; users who treat it as supplementary can switch to `skip`. The strategy is per-install (config) and per-invocation (CLI flag).

Related requirements: FR-07 (portable library snapshot), FR-08 (configurable import collision strategy), NFR-01 (data preservation — AC-6, AC-7), NFR-03 (atomic visibility — AC-10), NFR-07 (bounded archive growth — AC-5), NFR-13 (structured errors — AC-4, AC-9). Related stories: US-05 (archive), US-06 (conflict resolution).
