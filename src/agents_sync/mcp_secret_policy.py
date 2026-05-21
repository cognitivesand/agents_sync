"""Secret detection and policy handling for ``mcp_server`` artifacts."""
from __future__ import annotations

import copy
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any


ALLOWED_MCP_SECRET_POLICIES = frozenset({"refuse", "redact", "permissive"})
_ENV_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
ENV_NAME_RE = re.compile(rf"^{_ENV_NAME}$")
_ENV_REFERENCE_TOKEN_RE = re.compile(
    rf"\$\{{(?:env:)?({_ENV_NAME})\}}|\{{env:({_ENV_NAME})\}}"
)
ENV_REFERENCE_RE = re.compile(
    rf"^(?:\$\{{(?:env:)?({_ENV_NAME})\}}|\{{env:({_ENV_NAME})\}})$"
)
_BEARER_ENV_REFERENCE_RE = re.compile(
    rf"^Bearer\s+(?:\$\{{(?:env:)?({_ENV_NAME})\}}|\{{env:({_ENV_NAME})\}})$",
    re.IGNORECASE,
)
SECRET_FIELD_RE = re.compile(
    r"(api[_-]?key|authentication[_-]?blob|auth[_-]?blob|"
    r"license[_-]?key|connection[_-]?string|private[_-]?key|"
    r"passphrase|credentials?|token|secret|password|dsn|cookie|"
    r"session|jwt|(?:^|[_-])pat(?:$|[_-]))"
)
HIGH_CONFIDENCE_SECRET_VALUE_RE = re.compile(
    r"("
    r"sk-[A-Za-z0-9_-]{8,}|"
    r"ghp_[A-Za-z0-9_]{8,}|"
    r"github_pat_[A-Za-z0-9_]{16,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"xoxb-[A-Za-z0-9-]{16,}|"
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r")"
)
_PERMISSIVE_WARNING_CACHE: set[tuple[str, tuple[str, ...]]] = set()


@dataclass(frozen=True)
class SecretFinding:
    """One literal secret-like value inside an MCP server document."""

    path: tuple[str, ...]

    @property
    def field_path(self) -> str:
        return ".".join(self.path)


class McpSecretLeakError(ValueError):
    """Raised when ``mcp_server_secret_policy = refuse`` detects literals."""

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
            "MCP server secret policy refused literal secret values:"
            f"{location} fields={fields}"
        )


def validate_mcp_secret_policy(policy: str) -> str:
    if policy not in ALLOWED_MCP_SECRET_POLICIES:
        raise ValueError(
            "mcp_server_secret_policy must be "
            f"{'|'.join(sorted(ALLOWED_MCP_SECRET_POLICIES))}, got {policy!r}"
        )
    return policy


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
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return ``data`` after applying the configured secret policy.

    ``redact`` returns a deep-copied object with placeholders and a list
    suitable for ``canonical["secret_redactions"]``. ``permissive`` logs a
    warning and returns the original values. ``refuse`` raises.
    """
    validate_mcp_secret_policy(policy)
    findings = find_mcp_secret_literals(data)
    if not findings:
        return data, []

    field_paths = [finding.field_path for finding in findings]
    if policy == "refuse":
        raise McpSecretLeakError(findings, policy=policy, artifact=artifact)
    if policy == "permissive":
        artifact_key = artifact or "<unknown>"
        cache_key = (artifact_key, tuple(field_paths))
        if cache_key not in _PERMISSIVE_WARNING_CACHE:
            logging.warning(
                "MCP server secret policy permissive: artifact=%s fields=%s",
                artifact_key,
                field_paths,
            )
            _PERMISSIVE_WARNING_CACHE.add(cache_key)
        return data, []

    redacted = copy.deepcopy(data)
    redactions: list[dict[str, Any]] = []
    for index, finding in enumerate(findings, start=1):
        placeholder_env_var = f"AGENTS_SYNC_REDACTED_{index}"
        placeholder = _placeholder_for_path(finding.path, placeholder_env_var)
        _set_at_path(redacted, finding.path, placeholder)
        redactions.append({
            "field_path": finding.field_path,
            "original_env_var": None,
            "placeholder_env_var": placeholder_env_var,
        })
    return redacted, redactions


def find_mcp_secret_literals(data: Any) -> list[SecretFinding]:
    """Return every string literal matching the v0.5 MCP secret heuristic."""
    findings: list[SecretFinding] = []
    seen: set[tuple[str, ...]] = set()

    def visit(value: Any, path: tuple[str, ...]) -> None:
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
                visit(child, path + (str(index),))

    visit(data, ())
    return findings


def reset_mcp_secret_warning_cache() -> None:
    """Reset per-poll permissive warning de-duplication."""
    _PERMISSIVE_WARNING_CACHE.clear()


def _is_secret_literal(path: tuple[str, ...], key: str, value: str) -> bool:
    normalized_path = tuple(_normalize_key(part) for part in path)
    normalized_key = _normalize_key(key)
    if _expects_env_var_name(normalized_path):
        return not _is_safe_env_var_name_value(value)
    if is_safe_secret_reference(value):
        return False
    if normalized_path and normalized_path[0] == "env":
        return True
    if _is_secret_header_path(normalized_path):
        return True
    if SECRET_FIELD_RE.search(normalized_key) is not None:
        return True
    return HIGH_CONFIDENCE_SECRET_VALUE_RE.search(value) is not None


def _normalize_key(key: str) -> str:
    return unicodedata.normalize("NFKC", key).casefold()


def _expects_env_var_name(normalized_path: tuple[str, ...]) -> bool:
    return any(
        part == "env_http_headers"
        or part.endswith(("env_var", "env_vars"))
        for part in normalized_path
    )


def _is_safe_env_var_name_value(value: str) -> bool:
    if not is_valid_env_var_name(value):
        return False
    if HIGH_CONFIDENCE_SECRET_VALUE_RE.search(value):
        return False
    return not value.startswith(("ghp_", "github_pat_"))


def _is_secret_header_path(normalized_path: tuple[str, ...]) -> bool:
    if len(normalized_path) < 2:
        return False
    if "env_http_headers" in normalized_path[:-1]:
        return False
    if normalized_path[-2] not in {"headers", "http_headers"}:
        return False
    return normalized_path[-1] in {"authorization", "x-api-key"}


def _placeholder_for_path(path: tuple[str, ...], placeholder_env_var: str) -> str:
    normalized_path = tuple(_normalize_key(part) for part in path)
    if _expects_env_var_name(normalized_path):
        return placeholder_env_var
    return format_env_reference(placeholder_env_var)


def _set_at_path(data: dict[str, Any], path: tuple[str, ...], value: str) -> None:
    node: Any = data
    for key in path[:-1]:
        if isinstance(node, list):
            node = node[int(key)]
        else:
            node = node[key]
    if isinstance(node, list):
        node[int(path[-1])] = value
    else:
        node[path[-1]] = value


__all__ = [
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
    "reset_mcp_secret_warning_cache",
    "validate_mcp_secret_policy",
]
