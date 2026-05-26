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

# GitHub Copilot CLI agents and skills are enabled by default.
# VS Code user-profile instructions/prompts are path-configured because
# profile locations vary by install.
# copilot_cli_agents_dir = "~/.copilot/agents"
# copilot_cli_skills_dir = "~/.copilot/skills"
# copilot_vscode_user_instructions_dir = "/path/to/vscode/profile/instructions"
# copilot_vscode_user_prompts_dir = "/path/to/vscode/profile/prompts"
# copilot_enabled = false
EOF
fi

# Migrate any pre-v0.4-fix state. Idempotent and silent on fresh installs.
# Pre-fix installs (codex_skills_dir=~/.agents/skills, -skill suffix on
# counterparts) get a one-shot re-baseline: backup, suffix duplicates moved
# aside, ~/.agents/skills migrated to ~/.codex/skills, pair_id frontmatter
# stripped, state wiped. Everything is moved into a timestamped backup
# under ${STATE_DIR}/backups/, never deleted outright.
uv run python "${PROJECT_DIR}/scripts/migrate_v0.4.py" --yes

cat > "${SERVICE_DIR}/${APP_NAME}.service" <<EOF
[Unit]
Description=Bidirectional sync of Claude Code, Codex, Cursor, Gemini CLI, Antigravity, and opencode customizations

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
