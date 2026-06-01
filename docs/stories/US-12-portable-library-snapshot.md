# US-12: Customization library — export and import

## Persona

Alice

## User Story

As a power user who curates a library of agents and skills, I want to export my full customization library to a single transportable file and re-import it later — either to restore after a clean install or to seed another workstation — so that my library survives machine moves and can be shared without copying each agentic_tool's files by hand.

## Priority

Should Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`.

## Acceptance Criteria

> Retired AC numbers (not reused): AC-3, AC-8, AC-11, AC-17, AC-19.

### Export

- [ ] AC-1 [Normal]: Given a state directory containing N canonical documents, When the user runs `agents-sync export <export-file>`, Then an export is produced containing one entry per managed customization_artifact at `canonical/<customization_artifact_id>.json` plus a top-level `manifest.json` with `{schema_version, exported_at, source_host, source_platform, agents_sync_version, artifact_count, contains_secret_literals}`. The source state directory is unchanged.
- [ ] AC-2 [Normal]: Given the export runs concurrently with a live daemon, When the export completes, Then the export is a coherent point-in-time view — every entry is a single atomic read of the canonical store at one moment.
- [ ] AC-4 [Failure]: Given the export-file path is not writable (parent missing, permission denied, disk full), When `export` runs, Then the command aborts with a non-zero exit code and a structured error (NFR-13); no partial export is left behind.
- [ ] AC-5 [Normal]: Given a customization library export produced by AC-1 and a fresh install, When the user runs `agents-sync import <export-file>`, Then each canonical document in the export is written to the local state directory, and the next `sync_once` adopts each imported canonical (FR-16).

### Import

- [ ] AC-6 [Normal]: Given the export carries a customization_artifact with the same `customization_artifact_id` as a locally-managed one, When `import` runs, Then the `last_modified_wins` rule (FR-12) selects the prevailing candidate.
- [ ] AC-7 [Normal — cross-identity merge]: Given the export carries a customization_artifact whose `target_slug(name)` matches a *different* locally-managed artifact under the same `customization_type` (a different `customization_artifact_id` — e.g. the same skill created independently on two machines, then one machine's library imported onto the other), When `import` runs, Then the two are reconciled into a single managed customization_artifact by the `last_modified_wins` rule (FR-12); the surviving content is written under the **local** `customization_artifact_id` — reused so on-disk files are not re-stamped — and the other id is retired.
- [ ] AC-9 [Failure]: Given the export lacks `manifest.json`, or `manifest.schema_version` exceeds the supported version, or any `canonical/<id>.json` is unparseable or carries an invalid `customization_artifact_id`, When `import` runs, Then the command aborts with a non-zero exit code and a structured error (NFR-13) naming the offending entry; no canonical or state entry is created.
- [ ] AC-10 [Failure]: Given an import that fails partway through writing canonical documents, When `import` runs, Then per-artifact atomic import holds (FR-13): each customization_artifact is either fully imported or not imported at all — none is left half-written. Each fully-imported canonical is adopted on the next poll (FR-16); the rest are absent until a later import completes them.
- [ ] AC-18 [Normal — preview honesty]: Given an import that would merge or displace any local customization_artifact, When the user runs `agents-sync import`, Then a preview enumerates, **before any disk write**, every imported `customization_artifact_id` that will merge-by-slug or overwrite a local customization_artifact; the run requires `--force` if any local customization_artifact would be displaced.

### Secret handling at egress

These scenarios apply the cross-cutting `secret_policy` (NFR-15) at this story's two egress points — export and import. The contract is type-agnostic: today only the `mcp_server` customization_type can carry literal secret material, but any future customization_type whose adapter declares secret-detection heuristics falls under the same rules without amendment. Whenever an artifact carries literal secret material, the daemon logs one structured WARNING (NFR-13) naming its `customization_artifact_id` and field path, whether the artifact is skipped (`secrets_refused`) or passed through (`secrets_accepted`).

- [ ] AC-12 [Normal]: Given `secret_policy = secrets_refused` and no canonical carries secret material, When `export` runs, Then every canonical is written to the export and `manifest.contains_secret_literals` is `false`.
- [ ] AC-13 [Normal]: Given `secret_policy = secrets_refused` and at least one canonical carries secret material, When `export` runs, Then the export ships every clean canonical, skips every secret-bearing one, and `manifest.contains_secret_literals` is `false`.
- [ ] AC-14 [Normal]: Given `secret_policy = secrets_accepted` and at least one canonical carries secret material, When `export` runs, Then literal secret material is included verbatim and `manifest.contains_secret_literals` is `true`.
- [ ] AC-15 [Normal]: Given an export carrying secret material is imported on a `secrets_refused` host, When `import` runs, Then every clean canonical is imported (AC-5, AC-6) and every secret-bearing canonical is skipped.
- [ ] AC-16 [Normal]: Given an export carrying secret material is imported on a `secrets_accepted` host, When `import` runs, Then every canonical is imported verbatim.

## Notes

Today the export is a single `.zip` file, chosen for cross-platform parity (Windows, macOS, Linux) and OS-native inspection; the acceptance criteria are written format-neutrally so the container can change without rewording them. The export contains only the canonical store — it omits `state.json` (host-specific) and the on-disk archive (local audit history, not portable content).

Import reconciliation is fixed at the `last_modified_wins` rule, mirroring the daemon's runtime conflict-resolution rule (US-06): the candidate with the higher `last_modified` prevails, ties favouring the locally-present artifact. It is not configurable — there is no config key or CLI flag.

Related requirements: FR-12, FR-13, FR-15, FR-16, NFR-01, NFR-07, NFR-13, NFR-15. Related stories: US-03, US-05, US-06, US-13.
