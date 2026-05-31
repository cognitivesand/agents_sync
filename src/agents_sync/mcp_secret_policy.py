"""Secret detection and policy handling for ``mcp_server`` artifacts."""

from __future__ import annotations

import copy
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

#: New, type-agnostic spellings — the only values the internal pipeline sees
#: after :func:`normalize_secret_policy` runs at the config boundary. The
#: ``redact`` mode that lived in earlier v0.5 drafts is intentionally gone —
#: NFR-15 (2026-05-22 rewrite) is binary.
ALLOWED_SECRET_POLICIES = frozenset({"secrets_refused", "secrets_accepted"})

#: Maps the v0.5 pre-hardening spellings to the new ones. ``redact`` maps to
#: ``secrets_refused`` (the safer default) — the rewrite removed the redact
#: behaviour entirely; legacy redaction placeholders already in canonicals
#: keep working because they are env-references, not literals.
_OLD_POLICY_VALUE_MAP: dict[str, str] = {
    "refuse": "secrets_refused",
    "permissive": "secrets_accepted",
    "redact": "secrets_refused",
}

#: Kept as a deprecated alias so external callers still resolve the symbol
#: for one release. New code uses :data:`ALLOWED_SECRET_POLICIES`.
ALLOWED_MCP_SECRET_POLICIES = ALLOWED_SECRET_POLICIES | frozenset(_OLD_POLICY_VALUE_MAP)
_ENV_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
ENV_NAME_RE = re.compile(rf"^{_ENV_NAME}$")
_ENV_REFERENCE_TOKEN_RE = re.compile(
    rf"\$\{{(?:env:)?({_ENV_NAME})\}}|\{{env:({_ENV_NAME})\}}|"
    rf"\$({_ENV_NAME})|%({_ENV_NAME})%",
    re.IGNORECASE,
)
ENV_REFERENCE_RE = re.compile(
    rf"^(?:\$\{{(?:env:)?({_ENV_NAME})\}}|\{{env:({_ENV_NAME})\}}|"
    rf"\$({_ENV_NAME})|%({_ENV_NAME})%)$",
    re.IGNORECASE,
)
_BEARER_ENV_REFERENCE_RE = re.compile(
    rf"^Bearer\s+(?:\$\{{(?:env:)?({_ENV_NAME})\}}|\{{env:({_ENV_NAME})\}}|"
    rf"\$({_ENV_NAME})|%({_ENV_NAME})%)$",
    re.IGNORECASE,
)
SECRET_FIELD_RE = re.compile(
    r"(api[_-]?key|authentication[_-]?blob|auth[_-]?blob|"
    r"license[_-]?key|connection[_-]?string|private[_-]?key|"
    r"passphrase|credentials?|token|secret|password|dsn|cookie|"
    r"session|jwt|(?:^|[_-])pat(?:$|[_-]))"
)
# A menu of high-confidence credential prefixes. Each shape is distinctive
# enough that a literal match is almost never a false positive. This is the
# value-shape leg of detection; literals under env/headers/auth fields and under
# secret-named fields are caught by SECRET_FIELD_RE and the path checks
# regardless of shape. A literal of an arbitrary shape outside all of those is
# the documented residual (NFR-15) — place such credentials in env/headers.
HIGH_CONFIDENCE_SECRET_VALUE_RE = re.compile(
    r"("
    r"sk-[A-Za-z0-9_-]{8,}|"  # OpenAI / Anthropic-style
    r"sk_live_[A-Za-z0-9]{16,}|"  # Stripe secret key
    r"rk_live_[A-Za-z0-9]{16,}|"  # Stripe restricted key
    r"ghp_[A-Za-z0-9_]{8,}|"  # GitHub PAT (classic)
    r"github_pat_[A-Za-z0-9_]{16,}|"  # GitHub PAT (fine-grained)
    r"glpat-[A-Za-z0-9_-]{16,}|"  # GitLab PAT
    r"npm_[A-Za-z0-9]{36}|"  # npm token
    r"AKIA[0-9A-Z]{16}|"  # AWS access key id
    r"xox[baprs]-[A-Za-z0-9-]{16,}|"  # Slack bot/user/app/refresh/workspace
    r"AIza[0-9A-Za-z_-]{35}|"  # Google API key
    r"ya29\.[A-Za-z0-9_-]{20,}|"  # Google OAuth access token
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"  # JWT
    r")"
)
_PERMISSIVE_WARNING_CACHE: set[tuple[str, tuple[str, ...]]] = set()
"""Module-level fallback cache. Kept for back-compat with callers that do not
pass a per-context cache (and with the existing
``reset_mcp_secret_warning_cache`` shim that ``Syncer.sync_once`` calls each
poll). New code should construct its own cache and pass it explicitly so
two independent ``Syncer`` instances (tests, future MCP server) do not share
warning de-duplication state."""


@dataclass(frozen=True)
class SecretFinding:
    """One literal secret-like value inside an MCP server document.

    ``path`` is the tuple of dict keys and list indices traversed from the
    root. Dict keys are :class:`str`; list indices are :class:`int`. The
    distinction lets ``field_path`` render lists with bracket syntax
    (``env[0]``) so a dict key called ``"0"`` is not confused with a list
    index at position 0.
    """

    path: tuple[str | int, ...]

    @property
    def field_path(self) -> str:
        rendered: list[str] = []
        for part in self.path:
            if isinstance(part, int):
                if rendered:
                    rendered[-1] = f"{rendered[-1]}[{part}]"
                else:
                    rendered.append(f"[{part}]")
            else:
                rendered.append(part)
        return ".".join(rendered)


class McpSecretLeakError(ValueError):
    """Raised when ``secret_policy = secrets_refused`` detects literals."""

    def __init__(
        self,
        findings: list[SecretFinding],
        *,
        policy: str,
        artifact: str | None = None,
    ) -> None:
        self.findings = findings
        self.policy = policy
        self.artifact = artifact
        fields = [finding.field_path for finding in findings]
        location = f" artifact={artifact}" if artifact else ""
        super().__init__(
            f"MCP server secret policy refused literal secret values:{location} fields={fields}"
        )


def normalize_secret_policy(
    policy: str,
    *,
    source: str = "config",
    warn_deprecated: bool = True,
) -> str:
    """Return the canonical (post-2026-05-22) spelling of ``policy``.

    Accepts both the new spellings (``secrets_refused``, ``secrets_accepted``)
    and the v0.5 pre-hardening spellings (``refuse``, ``redact``,
    ``permissive``). When an old spelling is supplied, logs one WARNING
    naming ``source`` (typically a config file or CLI flag) so the operator
    knows where to make the change. The deprecation shim is intended to be
    removed in v0.6.

    Raises :class:`ValueError` for any other input.
    """
    if policy in ALLOWED_SECRET_POLICIES:
        return policy
    if policy in _OLD_POLICY_VALUE_MAP:
        new_value = _OLD_POLICY_VALUE_MAP[policy]
        if warn_deprecated:
            extra_note = (
                " — note that 'redact' mode is gone in v0.5; treating as "
                "'secrets_refused' (safer default)"
                if policy == "redact"
                else ""
            )
            logging.warning(
                "DEPRECATED secret_policy value %r (from %s) — use %r instead%s",
                policy,
                source,
                new_value,
                extra_note,
            )
        return new_value
    raise ValueError(
        f"secret_policy must be {'|'.join(sorted(ALLOWED_SECRET_POLICIES))}, got {policy!r}"
    )


def validate_mcp_secret_policy(policy: str) -> str:
    """Backwards-compatible alias for :func:`normalize_secret_policy`.

    Kept for callers that previously imported the function under this name.
    Emits no deprecation log on its own (the wrapped function handles that);
    new code should call :func:`normalize_secret_policy` directly.
    """
    return normalize_secret_policy(policy, source="validate_mcp_secret_policy")


def env_reference_name(value: str) -> str | None:
    """Return the env var name for supported native env-reference syntaxes."""
    match = ENV_REFERENCE_RE.match(value)
    if match is None:
        return None
    return next(group for group in match.groups() if group is not None)


def bearer_env_reference_name(value: str) -> str | None:
    """Return the env var name for ``Bearer <env-ref>`` header values."""
    match = _BEARER_ENV_REFERENCE_RE.match(value)
    if match is None:
        return None
    return next(group for group in match.groups() if group is not None)


def is_valid_env_var_name(name: str) -> bool:
    """Whether ``name`` is a valid environment variable name."""
    return ENV_NAME_RE.fullmatch(name) is not None


def format_env_reference(name: str, *, style: str = "canonical") -> str:
    """Render an env-reference in the target tool's native syntax."""
    if not is_valid_env_var_name(name):
        raise ValueError(f"invalid env var name: {name!r}")
    if style == "canonical":
        return f"${{env:{name}}}"
    if style == "claude":
        return f"${{{name}}}"
    if style == "gemini":
        return f"${{{name}}}"
    if style == "opencode":
        return f"{{env:{name}}}"
    raise ValueError(f"unknown env reference style: {style!r}")


def convert_env_references(value: str, *, style: str) -> str:
    """Convert every supported env-reference token in ``value`` to ``style``."""

    def replace(match: re.Match[str]) -> str:
        name = next(group for group in match.groups() if group is not None)
        return format_env_reference(name, style=style)

    return _ENV_REFERENCE_TOKEN_RE.sub(replace, value)


def is_safe_secret_reference(value: str) -> bool:
    """Whether a secret-looking field value delegates to the environment."""
    if env_reference_name(value) is not None:
        return True
    if bearer_env_reference_name(value) is not None:
        return True
    if _ENV_REFERENCE_TOKEN_RE.search(value) is None:
        return False
    literal_remainder = _ENV_REFERENCE_TOKEN_RE.sub("", value)
    return HIGH_CONFIDENCE_SECRET_VALUE_RE.search(literal_remainder) is None


def apply_mcp_secret_policy(
    data: dict[str, Any],
    *,
    policy: str,
    artifact: str | None = None,
    warning_cache: set[tuple[str, tuple[str, ...]]] | None = None,
) -> dict[str, Any]:
    """Return ``data`` after applying the configured secret policy.

    Always returns a deep-copied object: even when no findings exist or the
    policy is ``permissive``, the caller gets a fresh dict that it may mutate
    without aliasing the input. (Earlier behaviour returned the input by
    reference on those two paths, which made caller-side mutations leak back
    into the canonical state for ``no findings`` and into the source document
    for ``permissive``.)

    ``warning_cache`` lets callers scope the ``secrets_accepted``-warning
    de-duplication memory. If omitted, the module-level
    ``_PERMISSIVE_WARNING_CACHE`` is used (which ``Syncer.sync_once`` resets
    each poll via :func:`reset_mcp_secret_warning_cache`). New code that
    instantiates a ``Syncer`` from a test should pass its own ``set`` so
    parallel tests do not share warning state.

    ``policy`` is normalized via :func:`normalize_secret_policy`, so both
    the new spellings (``secrets_refused``, ``secrets_accepted``) and the
    deprecated v0.5 spellings (``refuse``, ``permissive``, ``redact``) are
    accepted. The ``redact`` mode is gone — it maps to ``secrets_refused``
    so a policy that previously redacted now refuses.
    """
    normalized_policy = normalize_secret_policy(policy, source="apply_mcp_secret_policy")
    findings = find_mcp_secret_literals(data)
    if not findings:
        return copy.deepcopy(data)

    field_paths = [finding.field_path for finding in findings]
    if normalized_policy == "secrets_refused":
        raise McpSecretLeakError(findings, policy=normalized_policy, artifact=artifact)

    # secrets_accepted: admit literals verbatim with one deduplicated WARNING.
    artifact_key = artifact or "<unknown>"
    cache_key = (artifact_key, tuple(field_paths))
    cache = warning_cache if warning_cache is not None else _PERMISSIVE_WARNING_CACHE
    if cache_key not in cache:
        logging.warning(
            "secret_policy=secrets_accepted: artifact=%s fields=%s",
            artifact_key,
            field_paths,
        )
        cache.add(cache_key)
    return copy.deepcopy(data)


def find_mcp_secret_literals(data: Any) -> list[SecretFinding]:
    """Return every string literal matching the v0.5 MCP secret heuristic.

    Path elements are :class:`str` for dict keys and :class:`int` for list
    indices, so a finding at ``env[0]`` is distinguishable from a finding
    at ``env."0"`` (the dict-key case). The ``_is_secret_literal``
    classifier consumes the same heterogenous path so its checks operate
    on the structurally-correct types.
    """
    findings: list[SecretFinding] = []
    seen: set[tuple[str | int, ...]] = set()

    def visit(value: Any, path: tuple[str | int, ...]) -> None:
        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = str(raw_key)
                child_path = path + (key,)
                if (
                    isinstance(child, str)
                    and _is_secret_literal(child_path, key, child)
                    and child_path not in seen
                ):
                    findings.append(SecretFinding(child_path))
                    seen.add(child_path)
                visit(child, child_path)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, path + (index,))

    visit(data, ())
    return findings


def reset_mcp_secret_warning_cache() -> None:
    """Reset per-poll permissive warning de-duplication."""
    _PERMISSIVE_WARNING_CACHE.clear()


def _is_secret_literal(
    path: tuple[str | int, ...],
    key: str,
    value: str,
) -> bool:
    normalized_path = _normalize_path(path)
    normalized_key = _normalize_key(key)
    if _expects_env_var_name(normalized_path):
        return not _is_safe_env_var_name_value(value)
    if is_safe_secret_reference(value):
        return False
    if _is_env_secret_path(normalized_path):
        return True
    if _is_secret_header_path(normalized_path):
        return True
    if SECRET_FIELD_RE.search(normalized_key) is not None:
        return True
    return HIGH_CONFIDENCE_SECRET_VALUE_RE.search(value) is not None


def _normalize_key(key: str) -> str:
    return unicodedata.normalize("NFKC", key).casefold()


def _normalize_path(path: tuple[str | int, ...]) -> tuple[str | int, ...]:
    """Apply NFKC + casefold to dict-key elements; list indices unchanged."""
    return tuple(_normalize_key(part) if isinstance(part, str) else part for part in path)


def _expects_env_var_name(normalized_path: tuple[str | int, ...]) -> bool:
    """Whether the path lands in a place that contractually holds an env var name.

    List-index components never carry the env-var-name marker — only string
    keys do.
    """
    return any(
        isinstance(part, str)
        and (part == "env_http_headers" or part.endswith(("env_var", "env_vars")))
        for part in normalized_path
    )


def _is_safe_env_var_name_value(value: str) -> bool:
    if not is_valid_env_var_name(value):
        return False
    if HIGH_CONFIDENCE_SECRET_VALUE_RE.search(value):
        return False
    return not value.startswith(("ghp_", "github_pat_"))


def _is_env_secret_path(normalized_path: tuple[str | int, ...]) -> bool:
    """Whether the path lands under an ``env`` block at any nesting depth."""
    return any(part == "env" for part in normalized_path[:-1])


def _is_secret_header_path(normalized_path: tuple[str | int, ...]) -> bool:
    """Whether the path lands in a request header that conventionally holds a
    secret (``Authorization`` / ``X-API-Key``).

    Works at any nesting depth (e.g. ``mcpServers.<name>.headers.Authorization``);
    not only at the top-level depth that the earlier heuristic required.
    """
    if len(normalized_path) < 2:
        return False
    if any(part == "env_http_headers" for part in normalized_path[:-1]):
        return False
    parent = normalized_path[-2]
    leaf = normalized_path[-1]
    if not isinstance(parent, str) or not isinstance(leaf, str):
        return False
    if parent not in {"headers", "http_headers"}:
        return False
    return leaf in {"authorization", "x-api-key"}


__all__ = [
    "ALLOWED_SECRET_POLICIES",
    "ALLOWED_MCP_SECRET_POLICIES",
    "McpSecretLeakError",
    "SecretFinding",
    "apply_mcp_secret_policy",
    "bearer_env_reference_name",
    "convert_env_references",
    "env_reference_name",
    "find_mcp_secret_literals",
    "format_env_reference",
    "is_safe_secret_reference",
    "is_valid_env_var_name",
    "normalize_secret_policy",
    "reset_mcp_secret_warning_cache",
    "validate_mcp_secret_policy",
]
