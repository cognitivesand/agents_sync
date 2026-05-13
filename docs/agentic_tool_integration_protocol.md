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

The `supported_customization_types` field. v0.4 defines two `customization_type` values:

| `customization_type` | Unit on disk |
|---|---|
| `agent` | A single file (e.g. `.md`, `.toml`) per managed customization_artifact |
| `skill` | A folder containing `SKILL.md` plus optional auxiliary files |

`supported_customization_types` is a `frozenset[str]`, subset of the registered `customization_type` set. An agentic_tool that supports none is rejected at registry init.

Future `customization_type` values (e.g. `prompt-template`, `mcp-server-config`) will extend this set when concrete agentic_tools demand them. Adding a new `customization_type` requires updating `agents_sync.agentic_tool_spec` to declare it and the corresponding `file_layout` descriptor. Agentic_tool modules that do not support the new `customization_type` are unaffected.

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

An agentic_tool may declare additional `file_layout` flags as the protocol evolves (e.g. case-sensitivity hints, filename-character restrictions beyond Windows reserved names). v0.4 ships with the two layouts above.

### 3. How to translate to and from the canonical form

For each `customization_type` in `supported_customization_types`, the module supplies a `CustomizationTypeIO` triple:

```python
@dataclass(frozen=True)
class CustomizationTypeIO:
    extract_customization_artifact_id: Callable[[str], str | None]
    parse: Callable[[str, dict | None], dict]
    render: Callable[[dict, str | None], str]
```

For the `agent` customization_type, the input to `extract_customization_artifact_id` / `parse` is the file's full text, and the output of `render` is the file's full text.

For the `skill` customization_type, the input/output text is the contents of the `SKILL.md` file only; auxiliary files in the skill folder are propagated verbatim by the sync core (not by the agentic_tool module).

Function contracts:

- **`extract_customization_artifact_id(text) -> str | None`**
  Pure. Returns the `customization_artifact_id` if the artifact metadata carries one and it parses as a UUID; returns `None` otherwise. Must not raise on malformed input — return `None`.

- **`parse(text, prior_canonical) -> canonical`**
  Pure. Reads the agentic_tool's native format and folds its content into a canonical dict (see `docs/project_description.md` for the canonical schema). If `prior_canonical` is provided, fields not present in `text` retain their canonical state; fields present in `text` overwrite. Agentic_tool-specific fields the canonical does not know about are stashed in `canonical["per_agentic_tool_extra"][<agentic_tool_name>]`. Agentic_tool-only-meaningful fields go in `canonical["per_agentic_tool_only"][<agentic_tool_name>]`. Required behaviour:
    - Round-trip stability: `parse(render(c), c) == c` over the agentic_tool-relevant subset of `c`.
    - Malformed input raises a clearly-named exception that the sync core catches and converts to a structured warning per US-03 AC-10.

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

## Versioning

This protocol is versioned with `agents_sync` itself. Breaking changes (e.g. adding a required field to `AgenticToolSpec`, or changing a function signature) require a major version bump. Non-breaking extensions (new optional `customization_type` values, new optional `file_layout` flags) require only the new field to default to a backwards-compatible value.
