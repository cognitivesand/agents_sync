# agents_sync — Project Requirements

This document captures the formally numbered requirements for `agents_sync`, organized by category. Each requirement is a single "shall" statement, verifiable, and traced to one or more user stories where applicable.

Categories:

- **REQ-F-XX** — Functional requirements
- **REQ-P-XX** — Performance / timing requirements
- **REQ-R-XX** — Reliability / correctness requirements
- **REQ-D-XX** — Data / format requirements
- **REQ-I-XX** — Interface / configuration requirements
- **REQ-O-XX** — Operational requirements

---

## Functional requirements

- **REQ-F-01** [US-01]: The tool **shall** sync agent definitions bidirectionally between the Claude Code agents directory and the Codex agents directory.
- **REQ-F-02** [US-02]: The tool **shall** sync skill folders bidirectionally between the Claude Code skills directory and the Codex skills directory, including the `SKILL.md` and any auxiliary files.
- **REQ-F-03**: The tool **shall** maintain a per-pair canonical JSON document storing the union of fields from both sides as the single lossless source of truth.
- **REQ-F-04** [US-04]: The tool **shall** inject a UUIDv4 `pair_id` into both sides of every managed pair on first encounter (adoption or migration).
- **REQ-F-05** [US-04]: A `pair_id` value, once assigned, **shall** never be reused for another pair, even after both sides are archived.
- **REQ-F-06** [US-03]: The tool **shall** auto-adopt foreign artifacts (files lacking a `pair_id`) found on either side, archiving the pre-adoption content before injecting the `pair_id`.
- **REQ-F-07** [US-01, US-02]: The tool **shall** track per-pair last-seen and last-written digests for each side, persisted across restarts, and **shall not** propagate a change whose current digest matches the digest the tool itself last wrote (loop suppression).
- **REQ-F-08** [US-04]: When the `name` field changes on a side, the tool **shall** rename the counterpart file to match the new slug and **shall** archive the contents of the previous filename before the rename.
- **REQ-F-09** [US-05]: When a sync operation would overwrite content not reproducible from the current canonical, the tool **shall** archive the prior bytes before overwriting; if archive write fails the destructive operation **shall** be aborted.
- **REQ-F-10** [US-06]: When both sides of a pair have diverged from the canonical, the tool **shall** apply last-`mtime`-wins; the loser's content **shall** be archived; if `mtime` is tied, Claude **shall** win deterministically and the resolution **shall** be logged at WARN level.
- **REQ-F-11** [US-07]: The tool **shall** provide a `--watch` mode that continuously polls both sides at a configurable interval and syncs detected changes.
- **REQ-F-12** [US-08]: The tool **shall** provide a `--once` mode that performs a single sync pass and exits.
- **REQ-F-13** [US-10]: On detecting a v0.1 (`claude-codex-sync`) installation, the tool **shall** migrate state, configuration, and the systemd user unit to v0.2 (`agents-sync`) paths, archiving v0.1 artifacts.
- **REQ-F-14** [US-05]: The tool **shall** never invoke `rm` or `unlink` on user-authored files; deletions **shall** be implemented as moves into the archive directory.
- **REQ-F-15** [US-09]: The tool **shall not** rely on an on-disk lock for concurrency safety; instead, it **shall** rely on atomic writes (REQ-R-01) and self-healing polls (REQ-R-04, REQ-R-06) to remain correct under interrupted runs and rare concurrent invocations.

## Performance / timing requirements

- **REQ-P-01** [US-01, US-02, US-07]: Any single-side change **shall** be propagated to the other side within `2 × poll_interval_seconds` (default 4 seconds).
- **REQ-P-02** [US-02]: The atomic skill-folder swap **shall** bound the missing-target window by two `rename(2)` calls; no full `copytree` **shall** be in the critical path of the swap.
- **REQ-P-03** [US-07]: A poll cycle **shall** complete in time strictly less than `poll_interval_seconds` under nominal conditions; if exceeded, a `WARN poll-overrun` log entry **shall** be emitted.

## Reliability / correctness requirements

- **REQ-R-01** [US-01, US-02]: All file write operations **shall** be atomic from the perspective of external readers (write to `.tmp`, then `rename(2)`).
- **REQ-R-02** [US-01]: For every render / parse pair, `parse(render(c)) == c` **shall** hold for any canonical document `c` (round-trip stability).
- **REQ-R-03**: Render functions **shall** be deterministic: the same canonical input **shall** produce byte-identical output across runs and reboots.
- **REQ-R-04**: State **shall** be persisted to disk after every successful sync cycle so that a restart resumes without re-translating unchanged pairs.
- **REQ-R-05** [US-10]: Migration from v0.1 **shall** be idempotent.
- **REQ-R-06**: Watch-mode poll loops **shall** catch transient exceptions and resume on the next interval; only configuration errors **shall** terminate the process.

## Data / format requirements

- **REQ-D-01** [US-05]: The archive layout **shall** be `~/.local/state/agents-sync/archive/<pair_id>/<side>/<original-filename>.<ISO-timestamp>` for individual files; for skill folders, a tarball at the same path scheme **shall** be used.
- **REQ-D-02** [US-05]: Archive timestamps **shall** be ISO 8601 UTC with `:` replaced by `-` for filesystem portability (e.g., `2026-05-06T16-35-01Z`).
- **REQ-D-03** [US-04]: YAML frontmatter rewrites **shall** preserve key order, comments, and quoting style, using a roundtrip-preserving library.
- **REQ-D-04** [US-02]: Auxiliary skill files **shall** preserve POSIX mode bits when copied between sides.
- **REQ-D-05**: The canonical JSON **shall** include a `schema_version` field; bumping the version **shall** archive the prior canonical before any rewrite.
- **REQ-D-06**: Each side **shall** carry a `*_extra` passthrough bucket inside the canonical for fields not modeled explicitly, ensuring no field is silently dropped.

## Interface / configuration requirements

- **REQ-I-01**: The tool **shall** read configuration from a TOML file located by the `--config` flag, defaulting to `~/.config/agents-sync/config.toml`.
- **REQ-I-02**: All path values in configuration **shall** support `~` (home) expansion.
- **REQ-I-03**: Each configuration key **shall** be overridable by a corresponding command-line flag.
- **REQ-I-04**: The CLI binary **shall** be named `agents-sync` and **shall** be installed to `~/.local/bin/agents-sync`.

## Operational requirements

- **REQ-O-01** [US-06, US-03]: All conflict resolutions and adoptions **shall** be logged at WARN level or higher with structured context (pair_id, paths, timestamps, decision).
- **REQ-O-02** [US-08]: Process exit codes **shall** be: `0` success; `1` sync error; `2` configuration error.
- **REQ-O-03** [US-07]: A systemd user unit `agents-sync.service` **shall** be installable via `install.sh --service` and **shall** run `agents-sync --watch` with `Restart=on-failure`.
- **REQ-O-04** [US-07, US-10]: On startup the tool **shall** log its version and configured paths at INFO level; on shutdown it **shall** log the cause (signal, error) at INFO level.
- **REQ-O-05** [US-07]: SIGINT and SIGTERM in watch mode **shall** complete the current poll if in progress and exit cleanly with code 0.
