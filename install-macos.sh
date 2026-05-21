#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="agents-sync"
LAUNCHD_LABEL="com.agents-sync.daemon"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"
BIN_DIR="${HOME}/.local/bin"
STATE_DIR="${HOME}/.local/state/${APP_NAME}"
CONFIG_DIR="${HOME}/.config/${APP_NAME}"
LOG_DIR="${HOME}/Library/Logs/${APP_NAME}"
LAUNCH_AGENT_DIR="${HOME}/Library/LaunchAgents"
CONFIG_FILE="${CONFIG_DIR}/config.toml"
PLIST_FILE="${LAUNCH_AGENT_DIR}/${LAUNCHD_LABEL}.plist"

usage() {
  cat <<'EOF'
Usage:
  ./install-macos.sh [-h|--help]

What it does:
  - verifies this is macOS and uv is available
  - creates/updates .venv with uv sync
  - installs/updates ~/.local/bin/agents-sync launcher
  - creates ~/.config/agents-sync/config.toml if missing
  - installs and starts a per-user LaunchAgent so the daemon runs
    continuously and restarts at login
EOF
}

xml_escape() {
  local value="$1"
  value="${value//&/&amp;}"
  value="${value//</&lt;}"
  value="${value//>/&gt;}"
  value="${value//\"/&quot;}"
  value="${value//\'/&apos;}"
  printf '%s' "${value}"
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

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "install-macos.sh must be run on macOS." >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but was not found." >&2
  echo
  echo "Install uv first, for example:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo
  exit 1
fi

if ! command -v launchctl >/dev/null 2>&1; then
  echo "launchctl is required (this script installs a macOS LaunchAgent)." >&2
  exit 1
fi

mkdir -p "${BIN_DIR}" "${STATE_DIR}" "${CONFIG_DIR}" "${LOG_DIR}" "${LAUNCH_AGENT_DIR}"

cd "${PROJECT_DIR}"

uv sync

cat > "${BIN_DIR}/${APP_NAME}" <<EOF
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/${APP_NAME}" "\$@"
EOF

chmod +x "${BIN_DIR}/${APP_NAME}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  cat > "${CONFIG_FILE}" <<'EOF'
[agents-sync]
poll_interval_seconds = 2.0
state_path = "~/.local/state/agents-sync/state.json"

claude_agents_dir = "~/.claude/agents"
claude_commands_dir = "~/.claude/commands"
claude_skills_dir = "~/.claude/skills"
claude_rules_dir = "~/.claude"

codex_agents_dir = "~/.codex/agents"
codex_prompts_dir = "~/.codex/prompts"
codex_skills_dir = "~/.codex/skills"
codex_rules_dir = "~/.codex"

# Cursor. Enabled by default for user-level file surfaces.
# cursor_agents_dir = "~/.cursor/agents"
# cursor_commands_dir = "~/.cursor/commands"
# cursor_skills_dir = "~/.cursor/skills"
# cursor_rules_dir = "~/.cursor/rules"
# cursor_mcp_servers_file = "~/.cursor/mcp.json"
# cursor_enabled = false

# Google Antigravity (skills only). Enabled by default once
# ~/.gemini/antigravity/skills exists. To disable, uncomment antigravity_enabled.
# antigravity_skills_dir = "~/.gemini/antigravity/skills"
# antigravity_enabled = false

# opencode (agents + commands + skills). Enabled by default once the roots exist or can
# be created. To disable, uncomment opencode_enabled.
# opencode_agents_dir = "~/.config/opencode/agents"
# opencode_commands_dir = "~/.config/opencode/commands"
# opencode_skills_dir = "~/.config/opencode/skills"
# opencode_rules_dir = "~/.config/opencode"
# opencode_enabled = false
EOF
fi

# Migrate any pre-v0.4-fix state. Idempotent and silent on fresh installs.
# See scripts/migrate_v0.4.py for the contract.
uv run python "${PROJECT_DIR}/scripts/migrate_v0.4.py" --yes

cat > "${PLIST_FILE}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml_escape "${BIN_DIR}/${APP_NAME}")</string>
    <string>--config</string>
    <string>$(xml_escape "${CONFIG_FILE}")</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$(xml_escape "${PROJECT_DIR}")</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$(xml_escape "${LOG_DIR}/${APP_NAME}.log")</string>
  <key>StandardErrorPath</key>
  <string>$(xml_escape "${LOG_DIR}/${APP_NAME}.err.log")</string>
</dict>
</plist>
EOF

USER_DOMAIN="gui/$(id -u)"

launchctl bootout "${USER_DOMAIN}" "${PLIST_FILE}" >/dev/null 2>&1 || true
launchctl bootstrap "${USER_DOMAIN}" "${PLIST_FILE}"
launchctl enable "${USER_DOMAIN}/${LAUNCHD_LABEL}"
launchctl kickstart -k "${USER_DOMAIN}/${LAUNCHD_LABEL}"

echo "Installed ${APP_NAME}"
echo "LaunchAgent: ${PLIST_FILE}"
echo "Status:      launchctl print ${USER_DOMAIN}/${LAUNCHD_LABEL}"
echo "Logs:        tail -f ${LOG_DIR}/${APP_NAME}.log"
