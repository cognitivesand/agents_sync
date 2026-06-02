#!/usr/bin/env bash
# scripts/dev_setup.sh — one-time developer environment setup.
#
# Run once after cloning:
#   ./scripts/dev_setup.sh
#
# It installs the dev dependencies and enables the automatic pre-push gate
# (.githooks/pre-push runs ./scripts/ci.sh before every push). Bypass a single
# push deliberately with `git push --no-verify`.

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
readonly REPO_ROOT
cd "$REPO_ROOT"

printf '\n\033[1m▶ Installing dev dependencies (uv sync --dev)\033[0m\n'
uv sync --dev

printf '\n\033[1m▶ Enabling pre-push gate (core.hooksPath -> .githooks)\033[0m\n'
git config core.hooksPath .githooks

printf '\n\033[32m✓ Dev setup complete. ./scripts/ci.sh now runs automatically before every push.\033[0m\n'
