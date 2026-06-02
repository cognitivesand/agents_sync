#!/usr/bin/env bash
# scripts/ci.sh — local CI gate.
#
# Runs the checks the GitHub workflow deliberately leaves out (ruff, mypy)
# plus the full test suite, so the AGENTS.md §11 commit gate is enforced
# locally before a push. GitHub CI keeps the cross-platform pytest matrix;
# the static analysis lives here, on purpose.
#
#   ruff check    — lint (rule families E, F, I, W, UP, B)
#   mypy --strict — types (src/, per pyproject [tool.mypy])
#   pytest        — full suite (no -m 'not slow' filter; this gates commits)
#
# Run from anywhere; the script roots itself at the repo:
#   ./scripts/ci.sh
#
# Exit 0 = every stage passed. The first failing stage aborts (non-zero).

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
readonly REPO_ROOT
cd "$REPO_ROOT"

CURRENT_STAGE="startup"
trap 'printf "\n\033[31m✗ Local CI failed at: %s\033[0m\n" "$CURRENT_STAGE" >&2' ERR

run_stage() {
  CURRENT_STAGE=$1
  shift
  printf '\n\033[1m▶ %s\033[0m\n' "$CURRENT_STAGE"
  "$@"
}

run_stage "ruff check (lint)" uv run ruff check .
run_stage "mypy --strict (types)" uv run mypy
run_stage "pytest (full suite)" uv run pytest

printf '\n\033[32m✓ Local CI passed.\033[0m\n'
