# Agentic-Tool Integration Protocol

This document specifies the contract that every agentic_tool module must satisfy. It is the implementation counterpart to US-10 "Extensible agentic_tool registry" and US-11 "Graceful agentic_tool absence."

An agentic_tool module integrates `agents_sync` with **one** agentic_tool. Adding a new agentic_tool means adding one new agentic_tool module that conforms to this protocol, plus a corresponding `[agentic_tools.<name>]` block in the user's config file. No changes to the sync algorithm are required.

## Terminology

User stories and the README use everyday prose; this protocol uses precise technical identifiers. Mapping:

| User-facing prose | Technical identifier (this doc, code, configs, schemas) | Meaning |
|---|---|---|
| my customizations (as a domain) | `user_customization` | Umbrella term for the whole domain of user-authored customizations across every `customization_type`. Conceptual, not an identifier of any single thing. |
| a customization / my agent / my skill | `customization_artifact` | A specific managed instance: identified by `customization_artifact_id`, present on N agentic_tools. The technical unit of synchronisation. |
| (no specific prose form; agent / skill / etc.) | `customization_type` | The category of a customization_artifact. Values today: `agent`, `skill`. Each customization_type has an associated `file_layout` describing how it is stored on disk (single file or folder). Open for future values. |
| (set of customization_types a tool supports) | `supported_customization_types` | The subset of registered customization_types that an agentic_tool's IO module can read and write. |
| my agentic_tools | `agentic_tool` | Both the external application that consumes customization_artifacts and `agents_sync`'s in-codebase integration with that application (1:1; no separate "side" or "peer" abstraction). |
| (legacy) | `kind`, `pair`, `side` | **Deprecated**. `kind` and `pair` were the pre-v0.4 internal names for `customization_type` and `customization_artifact` respectively. `side` was the pre-v0.4 alias for `agentic_tool`. Do not introduce in new code; may appear only in legacy migration code paths. |

An agentic_tool module is therefore the code that reads and writes `customization_artifact` instances on disk for one specific agentic_tool, for each `customization_type` that tool supports.

Implementation note: the current on-disk and in-code identity field is still named `pair_id` for state-schema compatibility. This document uses the broader term `customization_artifact_id` where it describes the domain model.

## Module layout

One Python module per agentic_tool, named after the agentic_tool:

```
src/agents_sync/agentic_tools/<agentic_tool_name>.py
```

Examples:

```
src/agents_sync/agentic_tools/claude.py
src/agents_sync/agentic_tools/codex.py
src/agents_sync/agentic_tools/antigravity.py
src/agents_sync/agentic_tools/opencode.py
```

`<agentic_tool_name>` is the agentic_tool's unique identifier. It is lowercase ASCII, matches `^[a-z][a-z0-9_]{1,30}$`, and is the same string used throughout:

- in the config file: `[agentic_tools.<agentic_tool_name>]`;
- in archive paths: `archive/<customization_artifact_id>/<agentic_tool_name>/`;
- in state entries: `state.customization_artifacts[<customization_artifact_id>].agentic_tools[<agentic_tool_name>]`;
- in canonical per-agentic_tool bags: `per_agentic_tool_only[<agentic_tool_name>]`, `per_agentic_tool_extra[<agentic_tool_name>]`.

## What every module must declare

Each agentic_tool module exports exactly one top-level constant named `AGENTIC_TOOL`, of type `AgenticToolSpec`:

```python
# src/agents_sync/agentic_tools/<agentic_tool_name>.py
from agents_sync.agentic_tool_spec import AgenticToolSpec, CustomizationTypeIO

AGENTIC_TOOL: AgenticToolSpec = AgenticToolSpec(
    name="<agentic_tool_name>",
    supported_customization_types=frozenset({...}),   # subset of {"agent", "skill", ...}
    io_per_customization_type={
        "agent": CustomizationTypeIO(...),            # present iff "agent" in supported_customization_types
        "skill": CustomizationTypeIO(...),            # present iff "skill" in supported_customization_types
    },
    config_roots={
        "agent": "<config_key_for_agent_root>",
        "skill": "<config_key_for_skill_root>",
    },
    file_layout={
        "agent": AgentFileLayout(extension=".<ext>"),
        "skill": SkillFileLayout(skill_md_name="SKILL.md"),
    },
)
```

The daemon's agentic_tool registry imports `AGENTIC_TOOL` from every module under `src/agents_sync/agentic_tools/` at startup. A module that omits `AGENTIC_TOOL`, or whose `AGENTIC_TOOL` is not an `AgenticToolSpec`, causes a fail-closed configuration error per US-10 AC-8.

## The three questions every module answers

### 1. What is synced

The `supported_customization_types` field. The registered `customization_type` values are:

| `customization_type` | Since | Unit on disk |
|---|---|---|
| `agent` | v0.4 | A single file (e.g. `.md`, `.toml`) per managed customization_artifact |
| `skill` | v0.4 | A folder containing `SKILL.md` plus optional auxiliary files |
| `rules` | v0.5 | A single file (`.md` or `.mdc`) per rule, with optional YAML frontmatter |
| `slash_command` | v0.5 | A single file (`.md` or `.toml`) per command, with optional frontmatter |
| `mcp_server` | v0.5 | One MCP server definition per managed customization_artifact, projected to a slot inside a shared keyed-map file |

`supported_customization_types` is a `frozenset[str]`, subset of the registered `customization_type` set. An agentic_tool that supports none is rejected at registry init.

The detailed semantics of each v0.5 customization_type are specified in §v0.5 customization_types below. Future values will extend this set when concrete agentic_tools demand them. Adding a new `customization_type` requires updating `agents_sync.agentic_tool_spec` to declare it and the corresponding `file_layout` descriptor. Agentic_tool modules that do not support the new `customization_type` are unaffected.

### 2. Where the files are

Two declarations:

- **`config_roots`** — maps each supported `customization_type` to the config-file key under `[agentic_tools.<agentic_tool_name>]` that names the on-disk root for that `customization_type`. Example: `{"agent": "agents_dir", "skill": "skills_dir"}` means the config file is expected to contain:

  ```toml
  [agentic_tools.<agentic_tool_name>]
  agents_dir = "/path/to/agents"
  skills_dir = "/path/to/skills"
  ```

- **`file_layout`** — maps each supported `customization_type` to a layout descriptor:

  - `AgentFileLayout(extension: str)` — `agent` artifacts are single files whose basename is `<target_slug>.<extension>`.
  - `SkillFileLayout(skill_md_name: str)` — `skill` artifacts are folders. Inside each folder, the agentic_tool-rendered file has the name given by `skill_md_name` (today always `"SKILL.md"`, but future open-spec evolutions may diverge per tool).
  - `RulesFileLayout(extension: str)` *(v0.5)* — `rules` artifacts are single files whose basename is `<target_slug>.<extension>`. Cursor declares `extension=".mdc"`; every other agentic_tool declares `extension=".md"`.
  - `SlashCommandFileLayout(extension: str)` *(v0.5)* — `slash_command` artifacts are single files whose basename is `<target_slug>.<extension>`. Gemini CLI declares `extension=".toml"`; every other agentic_tool declares `extension=".md"`.
  - `SharedKeyedMapLayout(shared_path: str, map_key_path: tuple[str, ...], key_field: str = "name")` *(v0.5)* — the artifact is one slot inside a shared keyed-map file. `shared_path` is the config key naming the file (e.g. `mcp_servers_file`); `map_key_path` is the JSON/TOML path to the map inside (e.g. `("mcpServers",)`); `key_field` is the field name the canonical uses for the slot's identity (`"name"`). Used by `mcp_server` artifacts in v0.5. See §SharedKeyedMapLayout semantics for read/write/archive behaviour.

An agentic_tool may declare additional `file_layout` flags as the protocol evolves (e.g. case-sensitivity hints, filename-character restrictions beyond Windows reserved names). v0.5 ships with the five layouts above.

### 3. How to translate to and from the canonical form

For each `customization_type` in `supported_customization_types`, the module supplies a `CustomizationTypeIO` triple:

```python
class ParseFn(Protocol):
    def __call__(
        self,
        text: str,
        prior_canonical: dict | None,
        *,
        artifact_path: Path | None = None,
    ) -> dict:
        ...


@dataclass(frozen=True)
class CustomizationTypeIO:
    extract_customization_artifact_id: Callable[[str], str | None]
    parse: ParseFn
    render: Callable[[dict, str | None], str]
```

For the `agent` customization_type, the input to `extract_customization_artifact_id` / `parse` is the file's full text, and the output of `render` is the file's full text.

For the `skill` customization_type, the input/output text is the contents of the `SKILL.md` file only; auxiliary files in the skill folder are propagated verbatim by the sync core (not by the agentic_tool module).

Function contracts:

- **`extract_customization_artifact_id(text) -> str | None`**
  Pure. Returns the `customization_artifact_id` if the artifact metadata carries one and it parses as a UUID; returns `None` otherwise. Must not raise on malformed input — return `None`.

- **`parse(text, prior_canonical, *, artifact_path=None) -> canonical`**
  Pure. Reads the agentic_tool's native format and folds its content into a canonical dict (see `docs/project_description.md` for the canonical schema). If `prior_canonical` is provided, fields not present in `text` retain their canonical state; fields present in `text` overwrite. Agentic_tool-specific fields the canonical does not know about are stashed in `canonical["per_agentic_tool_extra"][<agentic_tool_name>]`. Agentic_tool-only-meaningful fields go in `canonical["per_agentic_tool_only"][<agentic_tool_name>]`. Required behaviour:
    - Round-trip stability: `parse(render(c), c) == c` over the agentic_tool-relevant subset of `c`.
    - Malformed input raises a clearly-named exception that the sync core catches and converts to a structured warning per US-03 AC-10.
    - If a native format derives identity from the filename rather than artifact metadata (for example opencode agents), the parser may use `artifact_path` to recover the filename stem. Parsers that do not need the path must accept and ignore it.

- **`render(canonical, prior_text=None) -> text`**
  Pure. Projects the canonical into the agentic_tool's native format. When `prior_text` is provided, the renderer should preserve existing key order, comments, and quoting style in the agentic_tool's artifact metadata where the underlying format supports it. Fields owned by other agentic_tools must not leak into the rendered output — see "Cross-agentic_tool field ownership" in the v0.4 implementation plan.

## Registration

Agentic_tools are discovered by the daemon at startup via:

```python
# src/agents_sync/agentic_tool_registry.py (sketch)
import pkgutil
from agents_sync import agentic_tools as agentic_tools_pkg

REGISTRY: dict[str, AgenticToolSpec] = {}
for module_info in pkgutil.iter_modules(agentic_tools_pkg.__path__):
    module = importlib.import_module(f"agents_sync.agentic_tools.{module_info.name}")
    spec = getattr(module, "AGENTIC_TOOL", None)
    if not isinstance(spec, AgenticToolSpec):
        raise ConfigError(f"agentic_tools/{module_info.name}.py does not export an AGENTIC_TOOL: AgenticToolSpec")
    if spec.name in REGISTRY:
        raise ConfigError(f"duplicate agentic_tool name: {spec.name}")
    REGISTRY[spec.name] = spec
```

Registration is purely structural. A registered agentic_tool that is not also enabled in config (see `enabled = false`) is excluded from runtime per US-10 AC-7. A registered, enabled agentic_tool whose configured root is missing is `unavailable` per US-11.

## Adding a new agentic_tool: end-to-end checklist

1. Create `src/agents_sync/agentic_tools/<tool_name>.py`.
2. Implement the three `CustomizationTypeIO` callables (`extract_customization_artifact_id`, `parse`, `render`) for each `customization_type` the tool supports — wired into a `CustomizationTypeIO` instance in the spec.
3. Export a top-level `AGENTIC_TOOL = AgenticToolSpec(...)`.
4. Add a `[agentic_tools.<tool_name>]` block to the sample config in the installer.
5. Add the agentic_tool's default root paths to the per-OS defaults in `config.py`.
6. Write unit tests in `tests/agentic_tools/test_<tool_name>.py` covering parse/render round-trip, unknown-field passthrough, BOM and CRLF tolerance, malformed-artifact-metadata handling.
7. Add the new agentic_tool to the integration test matrix for US-01, US-03, US-06, US-11.
8. Document the agentic_tool in README's "What It Syncs" table and add an entry to the Default Paths table.

No changes to `sync.py`, `state.py`, `canonical.py`, `archive.py`, or any other module are required. If any change to those modules is needed to make the new agentic_tool work, the design has failed US-10 AC-2 — fix the protocol instead of working around it.

## Example: minimal agentic_tool supporting only the `skill` customization_type

```python
# src/agents_sync/agentic_tools/example.py
from agents_sync.agentic_tool_spec import AgenticToolSpec, CustomizationTypeIO, SkillFileLayout
from agents_sync.io_helpers.skill_md import (
    extract_customization_artifact_id_from_skill_md,
    parse_open_spec_skill_md,
    render_open_spec_skill_md,
)

KNOWN_FIELDS = frozenset({
    "customization_artifact_id", "name", "description",
    "license", "compatibility", "metadata", "allowed-tools",
})

AGENTIC_TOOL = AgenticToolSpec(
    name="example",
    supported_customization_types=frozenset({"skill"}),
    io_per_customization_type={
        "skill": CustomizationTypeIO(
            extract_customization_artifact_id=extract_customization_artifact_id_from_skill_md,
            parse=lambda text, prior: parse_open_spec_skill_md(
                text, prior, agentic_tool_name="example", known_fields=KNOWN_FIELDS,
            ),
            render=lambda canonical, prior_text: render_open_spec_skill_md(
                canonical, prior_text, agentic_tool_name="example", known_fields=KNOWN_FIELDS,
            ),
        ),
    },
    config_roots={"skill": "skills_dir"},
    file_layout={"skill": SkillFileLayout(skill_md_name="SKILL.md")},
)
```

The shared `io_helpers.skill_md` module hosts the open-spec `SKILL.md` parse/render that every agentic_tool speaking the open Agent Skills Specification can share; per-agentic_tool specialisation is confined to `known_fields` and the agentic_tool name. This is the recommended pattern for any agentic_tool whose on-disk format follows the open spec.

## v0.5 customization_types

v0.5 adds three customization_types: `rules`, `slash_command`, and `mcp_server`. Each is specified below to the same level of detail as `agent` and `skill`.

### `rules` (v0.5)

A `rules` artifact is a single Markdown file (`.md` or `.mdc`) optionally carrying YAML frontmatter, providing always-on or conditionally-injected instructions to the agentic_tool's agent loop.

- **`file_layout`**: `RulesFileLayout(extension: str)`. Cursor declares `".mdc"`; every other agentic_tool declares `".md"`.
- **`config_roots`**: single key naming the directory where rule files live. By convention `rules_dir` for `.md`-using tools and `cursor_rules_dir` for Cursor; the key name is the adapter's choice.
- **Identity**: the filename stem (slug). When a `customization_artifact_id` is present in frontmatter, the adapter MUST inject and recover it via `extract_customization_artifact_id` per US-04.
- **Canonical document fields** (in addition to those defined by the agentic_tool):
  - `name` (string, required) — the slug.
  - `description` (string, optional) — natural-language summary.
  - `body` (string, required) — the Markdown body verbatim.
  - `globs` (string | list[string], optional) — file globs that auto-attach the rule.
  - `applyTo` (string, optional) — single glob; Copilot-style synonym for `globs`.
  - `alwaysApply` (bool, optional) — Cursor-style flag.
  - `trigger` (string, optional) — Windsurf-style activation mode (`always_on` / `manual` / `model_decision` / `glob`).
  - `provenance` (`"user" | "agent"`, default `"user"`) — set by the adapter at parse time. Adapter declarations enumerate the source paths that produce `"agent"` provenance (e.g. Gemini CLI's `~/.gemini/GEMINI.md`-after-`/memory add` marker, Claude Code's `/memories/*.md`, Goose's `memory/<category>.txt`).
  - `private` (bool, default `false`) — set by the adapter at parse time. When `true`, the sync engine excludes the artifact end-to-end: no canonical entry, no archive write, no propagation. Adapter declarations enumerate the source paths that produce `private: true` (e.g. `.goosehints.local`, Windsurf hash-keyed memories, Junie user-scope memory).
- **Parser contract**: as for `agent`. Frontmatter fields not in the canonical schema are stashed in `per_agentic_tool_extra`. Frontmatter fields meaningful only to one tool (e.g. Cursor's exact derived-rule-type semantics, Windsurf's character budget) go in `per_agentic_tool_only`.
- **Renderer contract**: as for `agent`. When an adapter does not natively support `provenance` or `private`, those fields are not rendered to the artifact but are retained in the canonical (round-trip stable).

### `slash_command` (v0.5)

A `slash_command` artifact is a single file (`.md` or `.toml`) optionally carrying YAML frontmatter (Markdown) or top-level TOML keys (Gemini CLI), defining a reusable named prompt invoked as `/<name>` in the agentic_tool's chat surface.

- **`file_layout`**: `SlashCommandFileLayout(extension: str)`. Gemini CLI declares `".toml"`; every other agentic_tool declares `".md"`.
- **`config_roots`**: single key naming the directory where command files live. By convention `commands_dir`.
- **Identity**: the filename stem, optionally namespaced by subdirectory under `commands/`. For path-namespaced commands (`commands/git/commit.md` → `/git:commit` per Claude/Codex/Gemini convention), the canonical's `name` field carries the namespaced form (`git:commit`); the adapter is responsible for the on-disk separator (`/` or `\`) per platform.
- **Canonical document fields**:
  - `name` (string, required).
  - `description` (string, optional).
  - `argument_hint` (string, optional) — Claude/Roo/Junie's `argument-hint`; Copilot's `hint`. Stored canonically as `argument_hint`; per-tool spelling differences live in `per_agentic_tool_only`.
  - `allowed_tools` (list[string], optional) — the canonical stores a list; per-tool syntax (`Bash(git:*)`, glob-tool keys, flat lists) lives in `per_agentic_tool_only`.
  - `model` (string, optional).
  - `agent` or `mode` (string, optional) — per-tool semantics; stored in `per_agentic_tool_only`.
  - `body` (string, required) — the prompt template verbatim. Interpolation grammars (`$ARGUMENTS`, `$1..N`, `!`-shell, `@`-file, `{{args}}`, `{{{ input }}}`, Handlebars) are NOT normalised. The adapter parser preserves the body byte-for-byte; the renderer emits it byte-for-byte.
- **Reserved names**: Each agentic_tool may declare a set of reserved built-in command names that the sync engine refuses to create or rename onto. opencode's reserved set (`build`, `plan`, `general`, `explore`, `scout`) is the prototype. Reserved-name violations are reported as structured warnings per US-03 AC-10.
- **TOML variant (Gemini CLI)**: the entire file is a TOML document. `prompt` and `description` are top-level keys. The parser MUST translate `prompt` ↔ `body` when converting to/from the canonical. The shell-injection (`!{cmd}`) and file-injection (`@{path}`) grammars are stored verbatim in `body` and not interpreted by the sync engine.

### `mcp_server` (v0.5)

An `mcp_server` artifact is one MCP-server definition. Unlike `agent`/`skill`/`rules`/`slash_command`, the on-disk projection is **one slot inside a shared keyed-map file**, not a single dedicated file.

- **`file_layout`**: `SharedKeyedMapLayout(shared_path: str, map_key_path: tuple[str, ...], key_field: str = "name")`.
  - `shared_path` is the config key naming the file the map lives in. Examples: `mcp_servers_file = "~/.cursor/mcp.json"`, `mcp_servers_file = "~/.gemini/settings.json"`, `mcp_servers_file = "~/.copilot/mcp-config.json"`.
  - `map_key_path` is the JSON/TOML/YAML path to the map inside the file. Examples: `("mcpServers",)` for `~/.cursor/mcp.json`; `("mcpServers",)` for `~/.gemini/settings.json`; `("mcp_servers",)` for OpenAI Codex's `config.toml`. Encoded as a tuple of keys; nesting is allowed.
  - `key_field` is the canonical identity field. Almost always `"name"`.
- **`config_roots`**: single key naming the shared file. The same key name is reused as `SharedKeyedMapLayout.shared_path`.
- **Identity**: the map key (server name). When the canonical injects a `customization_artifact_id`, the v0.5 JSON slot convention stores it as top-level `pair_id` inside the slot. `extract_customization_artifact_id` / `extract_pair_id` MUST recover that value.
- **Canonical document fields**:
  - `name` (string, required) — the slot key.
  - `transport` (`"stdio" | "http" | "sse" | "streamable-http"`, required) — canonical transport name. Per-tool aliases (`local`/`remote` from opencode, `streamableHttp` from Cline, `httpUrl` vs `url` from Gemini CLI) are normalised to the canonical name on parse and reverted on render via `per_agentic_tool_only`.
  - For `transport: "stdio"`:
    - `command` (string, required).
    - `args` (list[string], optional).
    - `env` (object, optional).
    - `cwd` (string, optional).
    - `timeout` (int, optional, seconds or milliseconds — see per-tool aliasing in `per_agentic_tool_only`).
  - For `transport: "http"` / `"sse"` / `"streamable-http"`:
    - `url` (string, required).
    - `headers` (object, optional).
    - `auth` (object, optional) — used by tools that carry OAuth client credentials inline.
  - `disabled` (bool, optional) — most tools support this; passthrough where they do not.
  - `always_allow` (list[string], optional) — Cline/Roo/Kilo style. Stored canonically as `always_allow`; per-tool spellings (`alwaysAllow`, `allowedTools`) in `per_agentic_tool_only`.
  - `secret_redactions` (list[object], optional) — populated only under `mcp_server_secret_policy = "redact"`; each entry records `{ field_path, original_env_var | null }` so the user can re-resolve manually.
- **Secret-redaction policy (`mcp_server_secret_policy`)**: a top-level config key in the user's `agents_sync` config, accepted values `"refuse"` (default), `"redact"`, `"permissive"`. Evaluated by the sync core (not per adapter) at parse time and again at render time. The detection heuristic flags string values in `env`, `headers["Authorization"]`, `headers["X-API-Key"]`, `auth.client_secret`, and any field name matching `(?i)(api[_-]?key|token|secret|password)` whose value is not already an `${env:VAR}` reference.
  - `"refuse"`: parse fails with a structured error per US-03 AC-10. The artifact is NOT adopted; the prior on-disk file is left untouched. Per-tool tests verify the error shape.
  - `"redact"`: literals are replaced with `${env:AGENTS_SYNC_REDACTED_<n>}`; original variable hints (if recoverable, e.g. a sibling `env_key = "FOO"` in Codex) are stored in `canonical.secret_redactions`; otherwise `original_env_var: null`. Renders emit the placeholder; the user is expected to set the env var on each target host.
  - `"permissive"`: literals propagate unchanged. The sync engine emits one structured warning per artifact per poll naming the field path. Loop suppression is unaffected (warning is informational).
- **SharedKeyedMapLayout semantics** (read / write / archive):
  - **Read**: discovery enumerates `shared_path` once per poll. The parser is invoked once per slot (one `parse(slot_text, prior_canonical)` per server). On a malformed slot, the artifact is skipped with a structured warning; sibling slots are still processed.
  - **Write**: rendering produces a slot value. The sync core reads the current `shared_path`, replaces (or inserts) the slot under `map_key_path`, and atomically writes the merged file. Sibling slots are preserved byte-for-byte. The file's keys outside `map_key_path` are preserved byte-for-byte.
  - **Archive granularity**: per-slot, matching US-05 AC-1 without exception. When a slot's bytes change, the prior slot value is serialised independently (one JSON or TOML fragment) and written to `archive/<customization_artifact_id>/<agentic_tool_name>/<slot-key>.<file-extension>.<ISO-timestamp>`. Sibling slots whose bytes did not change produce no archive entries on this poll, even if the slot we are writing forces a rewrite of the shared file as a whole. The bytes of the shared file outside the slot's `map_key_path` entry are never archived — they are preserved on disk byte-for-byte.
  - **Identity injection**: when the sync engine creates a JSON slot, it writes the managed identity as top-level `pair_id`. TOML / YAML adapter PRs may introduce format-specific handlers, but they must preserve the same recoverable canonical identity.
  - **Format support in `feat/v0.5-mcp-server`**: only the JSON shared-keyed-map format handler is registered in this PR. TOML (`config.toml[mcp_servers]`) and YAML handlers land with the tool-adapter PRs that need them.

## Versioning

This protocol is versioned with `agents_sync` itself. Breaking changes (e.g. adding a required field to `AgenticToolSpec`, or changing a function signature) require a major version bump. Non-breaking extensions (new optional `customization_type` values, new optional `file_layout` flags) require only the new field to default to a backwards-compatible value.
