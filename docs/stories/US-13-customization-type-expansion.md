# US-13: Customization-type expansion (rules, slash_command, mcp_server)

## Persona

Alice

## User Story

As a power user maintaining a library of rules, slash commands, and MCP-server configurations across multiple agentic_tools, I want each of those artefacts to be a first-class managed customization_artifact — discovered, adopted, propagated, reconciled, and archived using the same mechanisms that already work for agents and skills — so that I can edit a rule in any tool and see it appear in every other tool that supports the same customization_type within one polling interval.

## Priority

Should Have

## Terminology

Vocabulary used in this story is defined in the project glossary at `docs/project_description.md`. The `rules`, `slash_command`, and `mcp_server` customization_types and their file_layouts are specified in `docs/agentic_tool_integration_protocol.md` §v0.5 customization_types.

## Acceptance Criteria

- [ ] AC-1 [Normal]: Given an agentic_tool registers `"rules"` in its `supported_customization_types`, When the user creates a Markdown rule file under the tool's configured rules root, Then within two polling intervals every other available agentic_tool that registers `"rules"` exposes an equivalent rule file under its own configured rules root, with the same `customization_artifact_id` injected and recoverable via that tool's `extract_customization_artifact_id`.

- [ ] AC-2 [Normal]: Given an agentic_tool registers `"slash_command"`, When the user creates a command file under the tool's configured commands root, Then within two polling intervals every other available agentic_tool that registers `"slash_command"` exposes an equivalent command file. Body interpolation grammars (`$ARGUMENTS`, `!`-shell, `@`-file, `{{args}}`, `!{cmd}`, `@{path}`) are preserved byte-for-byte by the renderer.

- [ ] AC-3 [Normal]: Given an agentic_tool registers `"mcp_server"`, When the user adds a new server slot under the tool's `SharedKeyedMapLayout.shared_path`, Then within two polling intervals every other available agentic_tool that registers `"mcp_server"` exposes an equivalent slot under its own shared file, with sibling slots in those files preserved byte-for-byte.

- [ ] AC-4 [Normal]: Given a `rules` artifact whose canonical document sets `private: true` (as declared by the source adapter's `parse` function), When the daemon runs, Then no canonical entry is created, no archive write occurs, and the artifact is not propagated to any other agentic_tool. The `private: true` artifact remains on disk untouched on its origin tool.

- [ ] AC-5 [Failure]: Given `secret_policy = "secrets_refused"` (the default), When a customization_artifact is parsed and its canonical document carries a literal value matching the secret-detection heuristics declared by that customization_type's adapter, Then the daemon emits a structured error per US-03 AC-10 naming the artifact, the offending field path, and the configured policy. The artifact is NOT adopted. The on-disk file is left untouched. (Today only the `mcp_server` adapter declares secret-detection heuristics on `env`, `headers`, and `auth.*`; future customization_types fall under the same contract without amendment.)

- [ ] AC-6 [Normal]: Given `secret_policy = "secrets_accepted"`, When a customization_artifact is parsed and its canonical document carries a literal value matching the secret-detection heuristics, Then the artifact propagates unchanged and the daemon logs one structured warning per artifact per poll naming the field path. Loop suppression is unaffected.

- [ ] AC-7 [Normal]: Given an `mcp_server` artifact's slot inside the shared keyed-map file is modified by the daemon, When the prior slot bytes differ from the new slot bytes, Then the prior bytes of that slot only (serialised independently from the surrounding shared file) are archived under `archive/<customization_artifact_id>/<agentic_tool_name>/<slot-key>.<file-extension>.<ISO-timestamp>` per US-05 AC-1's per-artifact attribution rule. Sibling slots in the same shared file whose bytes did not change produce no archive entries on this poll.

- [ ] AC-8 [Failure]: Given a `slash_command` artifact whose `name` collides with an agentic_tool's reserved built-in command names (e.g. opencode's `build` / `plan` / `general` / `explore` / `scout`), When the daemon would create or rename onto that name on that tool, Then the daemon emits a structured warning per US-03 AC-10 and skips that propagation step for that tool only. Other tools receive the artifact normally.

## Notes

- Conflict resolution for `rules`, `slash_command`, and `mcp_server` artifacts uses US-06's existing `most-recent-modification-time wins` rule unchanged. No customization_type-specific conflict semantics are introduced in v0.5.

- The `private` field on the canonical is load-bearing (AC-4 above). The `provenance: "user" | "agent"` field is informational only in v0.5 — it is recorded on the canonical for diagnostics and future reference but has no associated policy. Sources of `provenance: "agent"`: Goose memory extension, Claude Code memory tool output, Gemini CLI `/memory add`-appended blocks. Sources of `private: true`: Windsurf hash-keyed memories, Junie user-scope memory, `.goosehints.local`. Adapters set both at parse time based on the source path.

- Archive granularity for `mcp_server` artifacts follows US-05 AC-1 without exception. The slot's prior bytes are serialised independently (one JSON or TOML fragment per archive entry); the bytes of the surrounding shared file outside the slot's `map_key_path` entry are never archived. This keeps archive browsing symmetric across customization_types.

- Cursor's adapter ships with `rules`, `slash_command`, and `mcp_server` support — no `agent`, no `skill` — because Cursor has no file-based equivalents for the latter two. See `docs/project_description.md` "Out of scope" for the SQLite-only surfaces.

- Gemini CLI's adapter ships with `agent`, `rules`, `slash_command`, and `mcp_server`. It does NOT declare `skill`; Antigravity remains the canonical owner of `~/.gemini/antigravity/skills/` per the path-ownership model (see plan §Resolved design decisions D3).

- GitHub Copilot's adapter ships with `agent`, `skill`, `rules`, `slash_command`, and `mcp_server`. Coverage spans the CLI half (`~/.copilot/`) and the VS Code user-profile half (the per-OS `prompts/` directory plus user `mcp.json`).

Related requirements: FR-07 (rules matrix — load-bearing for AC-1), FR-08 (slash_command matrix — AC-2, AC-8), FR-09 (mcp_server matrix — AC-3, AC-7), NFR-11 (extensibility), NFR-15 (secret handling — AC-5, AC-6).
