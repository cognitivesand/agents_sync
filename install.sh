#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="agents-sync"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"
BIN_DIR="${HOME}/.local/bin"
STATE_DIR="${HOME}/.local/state/${APP_NAME}"
CONFIG_DIR="${HOME}/.config/${APP_NAME}"
SERVICE_DIR="${HOME}/.config/systemd/user"

usage() {
  cat <<'EOF'
Usage:
  ./install.sh [-h|--help]

What it does:
  - verifies uv is available
  - creates/updates .venv with uv sync
  - installs/updates ~/.local/bin/agents-sync launcher
  - creates ~/.config/agents-sync/config.toml if missing
  - installs and enables the systemd user service so the daemon runs
    continuously and survives reboots
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but was not found." >&2
  echo
  echo "Install uv first, for example:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl is required (this script installs a systemd user service)." >&2
  exit 1
fi

mkdir -p "${BIN_DIR}" "${STATE_DIR}" "${CONFIG_DIR}" "${SERVICE_DIR}"

cd "${PROJECT_DIR}"

uv sync

cat > "${BIN_DIR}/${APP_NAME}" <<EOF
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/${APP_NAME}" "\$@"
EOF

chmod +x "${BIN_DIR}/${APP_NAME}"

CONFIG_FILE="${CONFIG_DIR}/config.toml"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  cat > "${CONFIG_FILE}" <<'EOF'
[agents-sync]
poll_interval_seconds = 2.0
state_path = "~/.local/state/agents-sync/state.json"

claude_agents_dir = "~/.claude/agents"
claude_skills_dir = "~/.claude/skills"

# Codex is skills-only in v0.4: it stores its global instructions in a single
# ~/.codex/AGENTS.md (not per-agent files).
codex_skills_dir = "~/.codex/skills"

# Google Antigravity (skills only). Enabled by default once
# ~/.gemini/antigravity/skills exists. To disable, uncomment antigravity_enabled.
# antigravity_skills_dir = "~/.gemini/antigravity/skills"
# antigravity_enabled = false
EOF
fi

cat > "${SERVICE_DIR}/${APP_NAME}.service" <<EOF
[Unit]
Description=Bidirectional sync of Claude Code agents and skills with Codex

[Service]
Type=simple
ExecStart=${BIN_DIR}/${APP_NAME} --config ${CONFIG_FILE}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "${APP_NAME}.service"

echo "Installed ${APP_NAME}"
echo "Service:  systemctl --user status ${APP_NAME}.service"
echo "Logs:     journalctl --user -u ${APP_NAME}.service -f"
