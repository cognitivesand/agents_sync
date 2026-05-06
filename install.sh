#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="agents-sync"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"
BIN_DIR="${HOME}/.local/bin"
STATE_DIR="${HOME}/.local/state/${APP_NAME}"
CONFIG_DIR="${HOME}/.config/${APP_NAME}"
SERVICE_DIR="${HOME}/.config/systemd/user"

INSTALL_SERVICE=false

usage() {
  cat <<'EOF'
Usage:
  ./install.sh [--service]

What it does:
  - verifies uv is available
  - creates/updates .venv with uv sync
  - installs/updates ~/.local/bin/agents-sync launcher
  - creates ~/.config/agents-sync/config.toml if missing
  - optionally installs/updates a systemd user service that runs the daemon
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      INSTALL_SERVICE=true
      shift
      ;;
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

mkdir -p "${BIN_DIR}" "${STATE_DIR}" "${CONFIG_DIR}"

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

codex_agents_dir = "~/.codex/agents"
codex_skills_dir = "~/.agents/skills"
EOF
fi

if [[ "${INSTALL_SERVICE}" == "true" ]]; then
  mkdir -p "${SERVICE_DIR}"

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
fi

echo "Installed ${APP_NAME}"
echo "Run:      ${BIN_DIR}/${APP_NAME} --config ${CONFIG_FILE}"

if [[ "${INSTALL_SERVICE}" == "true" ]]; then
  echo "Service:  systemctl --user status ${APP_NAME}.service"
fi
