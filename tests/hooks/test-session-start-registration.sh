#!/usr/bin/env bash
# Registration check in session-start.sh counts user, project and local settings.
# Run: bash tests/hooks/test-session-start-registration.sh
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
HOOK="$PROJECT_ROOT/.claude/hooks/session-start.sh"
PASS=0; FAIL=0
ok()   { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# settings JSON registering copilot-hook for the given events
settings() {
  python3 - "$@" <<'PY'
import json, sys
print(json.dumps({"hooks": {e: [{"hooks": [{"type": "command", "command": f'bash "$HOME/.copilot/current/claude-copilot/.claude/hooks/copilot-hook.sh" {e}'}]}] for e in sys.argv[1:]}}))
PY
}

# run <name> <user-events> <project-events> <local-events>; echoes hook output
run() {
  local d="$TMP/$1"; mkdir -p "$d/fakehome/.claude" "$d/proj/.claude"
  settings $2 > "$d/fakehome/.claude/settings.json"
  settings $3 > "$d/proj/.claude/settings.json"
  settings $4 > "$d/proj/.claude/settings.local.json"
  printf '{"session_id":"s","source":"startup"}' | HOME="$d/fakehome" CLAUDE_PROJECT_DIR="$d/proj" \
    COPILOT_HOOK_STATE_DIR="$d/state" bash "$HOOK" 2>/dev/null
}
ALL="SessionStart PreToolUse SubagentStop UserPromptSubmit"

echo "=== test-session-start-registration.sh ==="
out="$(run user_only "$ALL" "" "")"
[[ "$out" != *"partly registered"* ]] && ok "user-level shim alone satisfies enforcement" || fail "false warning with user-level shim only"

out="$(run split "SessionStart PreToolUse" "SubagentStop" "UserPromptSubmit")"
[[ "$out" != *"partly registered"* ]] && ok "user + project + local events combine" || fail "split registration falsely warned"

out="$(run missing "SessionStart PreToolUse" "SubagentStop" "")"
if [[ "$out" == *"partly registered"* && "$out" == *"Registered: 3/4"* && "$out" == *"UserPromptSubmit"* ]]; then
  ok "event registered nowhere still warns"
else fail "genuine missing registration not reported: $out"; fi

echo ""; echo "Passed: $PASS Failed: $FAIL"; [[ $FAIL -eq 0 ]]
