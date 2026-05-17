#!/usr/bin/env bash
# scripts/integration_tests.sh — end-to-end verification of agents-sync
# export/import against two fully-isolated throwaway installs.
#
# Isolation guarantees (do NOT touch the real install):
#   - Every path lives inside an mktemp -d workspace under TMPDIR.
#   - Every agents-sync invocation passes --config explicitly, so the
#     daemon never reads the user's ~/.config/agents-sync/config.toml.
#   - The test TOMLs only reference paths inside the workspace; the
#     script aborts before any agents-sync call if that invariant breaks.
#   - The workspace is removed on exit (success OR failure).
#
# Run from the repo root:
#   ./scripts/integration_tests.sh
#
# Exit code 0 = every assertion passed. Non-zero = first failure aborts.

set -euo pipefail

# ---------------- bootstrap ----------------

readonly SCRIPT_NAME="agents-sync-integration"
WORKSPACE=$(mktemp -d "${TMPDIR:-/tmp}/${SCRIPT_NAME}.XXXXXXXX")
readonly WORKSPACE
readonly SRC_ROOT="$WORKSPACE/src"
readonly TARGET_ROOT="$WORKSPACE/target"
readonly SRC_TOML="$WORKSPACE/src.toml"
readonly TARGET_TOML="$WORKSPACE/target.toml"
readonly ZIP_PATH="$WORKSPACE/library.zip"

cleanup() {
  local status=$?
  rm -rf "$WORKSPACE"
  if [[ $status -eq 0 ]]; then
    printf '\n\033[32m✓ Integration tests passed.\033[0m\n'
  else
    printf '\n\033[31m✗ Integration tests failed (exit %d). Workspace removed.\033[0m\n' "$status" >&2
  fi
  exit $status
}
trap cleanup EXIT

step() {
  printf '\n\033[1;34m▸ %s\033[0m\n' "$1"
}

fail() {
  printf '\033[31m  FAIL: %s\033[0m\n' "$1" >&2
  exit 1
}

ok() {
  printf '\033[32m  ✓ %s\033[0m\n' "$1"
}

# ---------------- safety belts ----------------

# Refuse to run if the workspace path escaped TMPDIR somehow.
case "$WORKSPACE" in
  "${TMPDIR:-/tmp}"/*) : ;;
  *) fail "workspace path is not under TMPDIR: $WORKSPACE" ;;
esac

# Refuse to write outside the workspace.
assert_in_workspace() {
  local path="$1"
  case "$path" in
    "$WORKSPACE"/*) : ;;
    *) fail "path is not inside the test workspace: $path" ;;
  esac
}

# ---------------- step 1: directories ----------------

step "Creating isolated installs in $WORKSPACE"

for install in "$SRC_ROOT" "$TARGET_ROOT"; do
  assert_in_workspace "$install"
  mkdir -p "$install/state"
  mkdir -p "$install/claude/agents" "$install/claude/skills"
  mkdir -p "$install/codex/agents" "$install/codex/skills"
  mkdir -p "$install/antigravity/skills"
  mkdir -p "$install/opencode/agents" "$install/opencode/skills"
done
ok "src and target install trees materialised"

# ---------------- step 2: configs ----------------

step "Writing per-install TOML configs"

write_config() {
  local toml_path="$1"
  local install_root="$2"
  assert_in_workspace "$toml_path"
  assert_in_workspace "$install_root"
  # Single-quoted TOML literal strings: no escape processing, so
  # backslashes in Windows paths survive intact if this script ever
  # gets ported to PowerShell.
  cat > "$toml_path" <<EOF
[agents-sync]
poll_interval_seconds = 1.0
state_path = '$install_root/state/state.json'
claude_agents_dir = '$install_root/claude/agents'
claude_skills_dir = '$install_root/claude/skills'
codex_agents_dir = '$install_root/codex/agents'
codex_skills_dir = '$install_root/codex/skills'
antigravity_skills_dir = '$install_root/antigravity/skills'
antigravity_enabled = true
opencode_agents_dir = '$install_root/opencode/agents'
opencode_skills_dir = '$install_root/opencode/skills'
opencode_enabled = true
import_collision_strategy = "mtime_wins"
EOF
}

write_config "$SRC_TOML" "$SRC_ROOT"
write_config "$TARGET_TOML" "$TARGET_ROOT"

# Verify the configs only reference workspace paths. If grep finds a
# reference to anything outside the workspace, abort before invoking
# the daemon.
for toml_path in "$SRC_TOML" "$TARGET_TOML"; do
  if grep -E "^[a-z_]+ *= *'" "$toml_path" \
     | grep -v "$WORKSPACE" \
     | grep -qE "= *'"; then
    fail "config $toml_path contains a path outside $WORKSPACE — refusing to run"
  fi
done
ok "configs are workspace-only"

# ---------------- step 3: seed the source install ----------------

step "Seeding one skill and one agent on the source install"

mkdir -p "$SRC_ROOT/claude/skills/formatter"
cat > "$SRC_ROOT/claude/skills/formatter/SKILL.md" <<'EOF'
---
name: formatter
description: A test skill for the integration run
---
Format my code please.
EOF
ok "seed skill: claude/skills/formatter"

cat > "$SRC_ROOT/claude/agents/reviewer.md" <<'EOF'
---
name: reviewer
description: A test agent for the integration run
---
Review my code.
EOF
ok "seed agent: claude/agents/reviewer"

# ---------------- step 4: run the daemon briefly to adopt ----------------

step "Running source daemon for one polling cycle to adopt and project"

uv run agents-sync --config "$SRC_TOML" --interval 0.5 &
DAEMON_PID=$!
sleep 3
kill "$DAEMON_PID" 2>/dev/null || true
wait "$DAEMON_PID" 2>/dev/null || true

canonical_count=$(find "$SRC_ROOT/state/canonical" -name "*.json" 2>/dev/null | wc -l)
[[ "$canonical_count" -eq 2 ]] \
  || fail "expected 2 canonicals on source, got $canonical_count"
ok "adoption created 2 canonicals"

src_projections=$(find "$SRC_ROOT" \
  \( -name "SKILL.md" -o -name "reviewer.md" -o -name "reviewer.toml" \) \
  | grep -v state | wc -l)
[[ "$src_projections" -eq 7 ]] \
  || fail "expected 7 projected files on source, got $src_projections"
ok "daemon projected 7 files (agents on 3 tools + skills on 4 tools)"

# ---------------- step 5: export ----------------

step "Exporting source library to $ZIP_PATH"

uv run agents-sync --config "$SRC_TOML" export "$ZIP_PATH" \
  || fail "export command failed"
[[ -f "$ZIP_PATH" ]] || fail "export produced no zip"

zip_entries=$(uv run python - <<EOF
import zipfile
for name in zipfile.ZipFile("$ZIP_PATH").namelist():
    print(name)
EOF
)
echo "$zip_entries" | grep -q "^manifest.json$" \
  || fail "zip missing manifest.json"
canonical_entries=$(echo "$zip_entries" | grep -c "^canonical/.*\.json$")
[[ "$canonical_entries" -eq 2 ]] \
  || fail "expected 2 canonical entries in zip, got $canonical_entries"
ok "zip carries manifest.json + 2 canonical/<uuid>.json entries"

# ---------------- step 6: import into a fresh target ----------------

step "Importing into the empty target install"

uv run agents-sync --config "$TARGET_TOML" import "$ZIP_PATH" \
  || fail "import command failed"

target_projections=$(find "$TARGET_ROOT" \
  \( -name "SKILL.md" -o -name "reviewer.md" -o -name "reviewer.toml" \) \
  | grep -v state | wc -l)
[[ "$target_projections" -eq 7 ]] \
  || fail "expected 7 projected files on target, got $target_projections"
ok "import projected all 7 files onto the target install"

target_archive_dir="$TARGET_ROOT/state/archive"
if [[ -d "$target_archive_dir" ]] \
   && [[ -n "$(find "$target_archive_dir" -type f 2>/dev/null)" ]]; then
  fail "import created archive entries — should have been zero on a fresh install"
fi
ok "no archive entries created (no displacement on fresh install)"

# ---------------- step 7: pair_id round-trip ----------------

step "Confirming pair_ids round-trip from source to target"

src_pair=$(grep -h "^pair_id:" "$SRC_ROOT/claude/skills/formatter/SKILL.md" | awk '{print $2}')
target_pair=$(grep -h "^pair_id:" "$TARGET_ROOT/claude/skills/formatter/SKILL.md" | awk '{print $2}')
[[ -n "$src_pair" ]] || fail "no pair_id injected on source skill"
[[ "$src_pair" == "$target_pair" ]] \
  || fail "pair_id mismatch: src=$src_pair target=$target_pair"
ok "pair_id $src_pair preserved across export/import"

# ---------------- step 8: NFR-05 idempotence ----------------

step "Verifying sync_once on the target is a no-op (NFR-05)"

idempotent_check=$(uv run python - <<EOF
import tomllib
from agents_sync.sync import Syncer
with open("$TARGET_TOML", "rb") as f:
    config = tomllib.load(f)["agents-sync"]
print(Syncer(config).sync_once())
EOF
)
[[ "$idempotent_check" == "0" ]] \
  || fail "sync_once changed $idempotent_check items after import — expected 0"
ok "sync_once changed 0 items (idempotent)"

# ---------------- step 9: collision strategies ----------------

step "Verifying collision strategies on a re-import into the source"

mtime_tie=$(uv run agents-sync --config "$SRC_TOML" import "$ZIP_PATH" 2>&1)
echo "$mtime_tie" | grep -q "accepted=0 skipped=2" \
  || fail "mtime_wins tie should skip both; got: $(echo "$mtime_tie" | tail -1)"
ok "mtime_wins ties favour local (default-deny on rewrite)"

skip_run=$(uv run agents-sync --config "$SRC_TOML" import "$ZIP_PATH" \
             --collision-strategy skip 2>&1)
echo "$skip_run" | grep -q "accepted=0 skipped=2" \
  || fail "skip strategy did not skip both: $(echo "$skip_run" | tail -1)"
ok "--collision-strategy skip leaves local untouched"

overwrite_run=$(uv run agents-sync --config "$SRC_TOML" import "$ZIP_PATH" \
                  --collision-strategy overwrite 2>&1)
echo "$overwrite_run" | grep -q "accepted=2" \
  || fail "overwrite strategy did not accept both: $(echo "$overwrite_run" | tail -1)"
src_archive_dir="$SRC_ROOT/state/archive"
[[ -d "$src_archive_dir" ]] \
  && [[ -n "$(find "$src_archive_dir" -type f 2>/dev/null)" ]] \
  || fail "overwrite did not produce archive entries (NFR-01 violation)"
ok "--collision-strategy overwrite displaces local + archives prior bytes"

# Trap will print the final success line and remove the workspace.
