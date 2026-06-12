"""Secret policy — credential detection + egress enforcement (NFR-15, US-13).

The one enforcer applied at every artifact-egress boundary (parse/adopt, render,
library export, library import — the call sites live in the planner, executor and
portable library). Detection scans a canonical document's wire-shaped structured
fields (command, args, env, cwd, url, headers, auth, per_tool_extra) — never
prose (name, description, body) or the per-tool bookkeeping bags. A string is a
finding when it sits under ``env``/``headers``/``auth``, under a field whose name
matches the secret-field set, or matches a high-confidence credential shape; a
value that delegates to the environment (an env reference in any spelling, incl.
``Bearer ${X}``) is safe. Two documented residuals: an arbitrary-shaped literal
outside all of those locations (NFR-15's residual — such credentials belong in
``env`` or ``headers``), and a literal that EMBEDS an env-reference token whose
remainder matches no credential shape (``"hunter2-$SUFFIX"`` under ``env``) — the
reference-delegation check must run first or normal path composition like
``"$HOME/bin:$PATH"`` would be refused.

``secrets_refused`` (default) fails closed per artifact with a structured
``SecretLeakError`` naming the artifact, field paths, and policy;
``secrets_accepted`` returns the findings so the caller logs one structured
warning per affected artifact (logging is the daemon's, S22). Env-reference
SYNTAX conversion is per-tool recipe data (S20), not policy.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agents_sync.domain_model.canonical_document import CanonicalDocument

SECRET_POLICY_REFUSED = "secrets_refused"
SECRET_POLICY_ACCEPTED = "secrets_accepted"
ALLOWED_SECRET_POLICIES = frozenset({SECRET_POLICY_REFUSED, SECRET_POLICY_ACCEPTED})

_ENV_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_ENV_REFERENCE_TOKEN_PATTERN = re.compile(
    rf"\$\{{(?:env:)?({_ENV_NAME})\}}|\{{env:({_ENV_NAME})\}}|\$({_ENV_NAME})|%({_ENV_NAME})%",
    re.IGNORECASE,
)
_ENV_REFERENCE_PATTERN = re.compile(
    rf"^(?:\$\{{(?:env:)?{_ENV_NAME}\}}|\{{env:{_ENV_NAME}\}}|\${_ENV_NAME}|%{_ENV_NAME}%)$",
    re.IGNORECASE,
)
_BEARER_ENV_REFERENCE_PATTERN = re.compile(
    rf"^Bearer\s+(?:\$\{{(?:env:)?{_ENV_NAME}\}}|\{{env:{_ENV_NAME}\}}|\${_ENV_NAME}|%{_ENV_NAME}%)$",
    re.IGNORECASE,
)
_ENV_VAR_NAME_PATTERN = re.compile(rf"^{_ENV_NAME}$")
_SECRET_FIELD_PATTERN = re.compile(
    r"(api[_-]?key|authentication[_-]?blob|auth[_-]?blob|"
    r"license[_-]?key|connection[_-]?string|private[_-]?key|"
    r"passphrase|credentials?|token|secret|password|dsn|cookie|"
    r"session|jwt|(?:^|[_-])pat(?:$|[_-]))"
)
# A menu of high-confidence credential prefixes: each shape is distinctive enough
# that a literal match is almost never a false positive. Literals under
# env/headers/auth and under secret-named fields are caught regardless of shape.
_HIGH_CONFIDENCE_SECRET_VALUE_PATTERN = re.compile(
    r"("
    r"sk-[A-Za-z0-9_-]{8,}|"  # OpenAI / Anthropic-style
    r"sk_live_[A-Za-z0-9]{16,}|"  # Stripe secret key
    r"rk_live_[A-Za-z0-9]{16,}|"  # Stripe restricted key
    r"ghp_[A-Za-z0-9_]{8,}|"  # GitHub PAT (classic)
    r"github_pat_[A-Za-z0-9_]{16,}|"  # GitHub PAT (fine-grained)
    r"glpat-[A-Za-z0-9_-]{16,}|"  # GitLab PAT
    r"npm_[A-Za-z0-9]{36}|"  # npm token
    r"AKIA[0-9A-Z]{16}|"  # AWS access key id
    r"xox[baprs]-[A-Za-z0-9-]{16,}|"  # Slack tokens
    r"AIza[0-9A-Za-z_-]{35}|"  # Google API key
    r"ya29\.[A-Za-z0-9_-]{20,}|"  # Google OAuth access token
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"  # JWT
    r")"
)


@dataclass(frozen=True)
class SecretFinding:
    """One literal secret-like value: the path of keys/indices from the document root."""

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


class SecretLeakError(ValueError):
    """``secrets_refused`` detected literal credentials — the artifact fails closed."""

    def __init__(
        self, findings: tuple[SecretFinding, ...], *, policy: str, artifact_label: str
    ) -> None:
        self.findings = findings
        self.policy = policy
        self.artifact_label = artifact_label
        paths = ", ".join(finding.field_path for finding in findings)
        super().__init__(
            f"secret literal(s) in artifact {artifact_label!r} at {paths} refused by "
            f"secret_policy={policy} — supply credentials via env references instead"
        )


def enforce_secret_policy(
    document: CanonicalDocument, policy: str, *, artifact_label: str
) -> tuple[SecretFinding, ...]:
    """Apply ``policy`` to ``document`` at an egress boundary.

    Returns the findings (empty when clean). ``secrets_refused`` raises
    ``SecretLeakError`` on any finding — the artifact must not propagate.
    An unknown policy is a configuration bug: a loud recipe error."""
    if policy not in ALLOWED_SECRET_POLICIES:
        raise ValueError(
            f"unknown secret_policy: {policy!r} (allowed: {sorted(ALLOWED_SECRET_POLICIES)})"
        )
    findings = find_secret_literals(document)
    if findings and policy == SECRET_POLICY_REFUSED:
        raise SecretLeakError(findings, policy=policy, artifact_label=artifact_label)
    return findings


def find_secret_literals(document: CanonicalDocument) -> tuple[SecretFinding, ...]:
    """Every literal credential in the document's wire-shaped structured fields."""
    findings: list[SecretFinding] = []

    def visit(value: Any, path: tuple[str | int, ...]) -> None:
        if isinstance(value, Mapping):  # covers the canonical's frozen MappingProxy bags
            for raw_key, child in value.items():
                key = str(raw_key)
                child_path = (*path, key)
                if isinstance(child, str) and _is_secret_literal(child_path, key, child):
                    findings.append(SecretFinding(child_path))
                visit(child, child_path)
            return
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                if isinstance(child, str) and _is_secret_literal((*path, index), "", child):
                    findings.append(SecretFinding((*path, index)))
                visit(child, (*path, index))

    visit(_wire_shaped_fields(document), ())
    return tuple(findings)


def _wire_shaped_fields(document: CanonicalDocument) -> dict[str, Any]:
    """The structured fields a tool file carries — prose and bookkeeping excluded.

    The visitor is read-only over Mappings, so the frozen fields walk as-is."""
    fields: dict[str, Any] = {
        "command": document.command,
        "args": document.args,
        "env": document.env,
        "cwd": document.cwd,
        "url": document.url,
        "headers": document.headers,
        "auth": document.auth,
        "per_tool_extra": document.per_tool_extra,
    }
    return {name: value for name, value in fields.items() if value}


def _is_secret_literal(path: tuple[str | int, ...], key: str, value: str) -> bool:
    normalized_path = _normalize_path(path)
    if _expects_env_var_name(normalized_path):
        return not _is_safe_env_var_name(value)
    if _is_safe_secret_reference(value):
        return False
    if _is_env_headers_or_auth_path(normalized_path):
        return True
    if key and _SECRET_FIELD_PATTERN.search(_normalize_key(key)) is not None:
        return True
    return _HIGH_CONFIDENCE_SECRET_VALUE_PATTERN.search(value) is not None


def _normalize_key(key: str) -> str:
    return unicodedata.normalize("NFKC", key).casefold()


def _normalize_path(path: tuple[str | int, ...]) -> tuple[str | int, ...]:
    return tuple(_normalize_key(part) if isinstance(part, str) else part for part in path)


def _is_safe_secret_reference(value: str) -> bool:
    """Whether a secret-looking value delegates to the environment."""
    if _ENV_REFERENCE_PATTERN.match(value) is not None:
        return True
    if _BEARER_ENV_REFERENCE_PATTERN.match(value) is not None:
        return True
    if _ENV_REFERENCE_TOKEN_PATTERN.search(value) is None:
        return False
    literal_remainder = _ENV_REFERENCE_TOKEN_PATTERN.sub("", value)
    return _HIGH_CONFIDENCE_SECRET_VALUE_PATTERN.search(literal_remainder) is None


def _expects_env_var_name(normalized_path: tuple[str | int, ...]) -> bool:
    """A field that contractually holds an env var NAME (a tool's env carrier)."""
    return any(
        isinstance(part, str)
        and (part == "env_http_headers" or part.endswith(("env_var", "env_vars")))
        for part in normalized_path
    )


def _is_safe_env_var_name(value: str) -> bool:
    if _ENV_VAR_NAME_PATTERN.match(value) is None:
        return False
    if _HIGH_CONFIDENCE_SECRET_VALUE_PATTERN.search(value) is not None:
        return False
    # belt-and-braces from the proven module: a GitHub-PAT prefix too short to
    # trip the shape pattern is still no env var name — fail closed.
    return not value.startswith(("ghp_", "github_pat_"))


def _is_env_headers_or_auth_path(normalized_path: tuple[str | int, ...]) -> bool:
    """NFR-15: location alone suffices — a literal under an ``env``, ``headers``,
    or ``auth`` block (at any depth) is detected regardless of shape, except the
    embedded-env-token residual documented in the module docstring.
    ``env_http_headers`` carrier paths never reach here — the caller's
    env-var-name branch early-returns for them."""
    return any(part in {"env", "headers", "http_headers", "auth"} for part in normalized_path[:-1])
