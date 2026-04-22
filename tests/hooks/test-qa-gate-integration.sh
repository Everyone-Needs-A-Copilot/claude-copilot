#!/usr/bin/env bash
# test-qa-gate-integration.sh — End-to-end integration test for QA gate state machine
#
# Proves the full flow:
#   1. SubagentStop(me) → pending_tasks gets TASK-N
#   2. PreToolUse(Bash) → deny
#   3. PreToolUse(Agent, subagent_type=qa) → allow
#   4. SubagentStop(qa, APPROVED) → pending_tasks cleared
#   5. PreToolUse(Bash) → allow again
#
# Run: bash tests/hooks/test-qa-gate-integration.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
PRETOOL_HOOK="$PROJECT_ROOT/.claude/hooks/pretool-check.sh"
STOP_HOOK="$PROJECT_ROOT/.claude/hooks/subagent-stop.sh"
STATE_DIR="$PROJECT_ROOT/.claude/hooks/state"
GATE_FILE="${STATE_DIR}/qa-gate.json"
JQ="/usr/bin/jq"

TEST_SESSION="integ-test-$$"

PASS=0
FAIL=0

ok() {
  echo "  [PASS] $1"
  PASS=$((PASS + 1))
}

fail() {
  echo "  [FAIL] $1"
  FAIL=$((FAIL + 1))
}

cleanup() {
  rm -f "$GATE_FILE" \
        "${STATE_DIR}/qa-gate.lock" \
        "${STATE_DIR}/qa-gate.log" \
        "${STATE_DIR}/streak-${TEST_SESSION}.json" \
        "${STATE_DIR}/streak-${TEST_SESSION}.lock" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
send_stop() {
  local agent_type="$1"
  local message="$2"
  local escaped
  escaped="$(printf '%s' "$message" | sed 's/"/\\"/g')"
  local payload
  payload="$(printf '{"session_id":"%s","agent_type":"%s","last_assistant_message":"%s"}' \
    "$TEST_SESSION" "$agent_type" "$escaped")"
  bash "$STOP_HOOK" <<< "$payload" 2>/dev/null
}

send_pretool_bash() {
  local cmd="$1"
  local payload
  payload="$(printf '{"session_id":"%s","tool_name":"Bash","tool_input":{"command":"%s"}}' \
    "$TEST_SESSION" "$(printf '%s' "$cmd" | sed 's/"/\\"/g')")"
  local exit_code=0
  local output
  output="$(bash "$PRETOOL_HOOK" <<< "$payload" 2>/dev/null)" || exit_code=$?
  printf '%d|%s' "$exit_code" "$output"
}

send_pretool_agent() {
  local subagent_type="$1"
  local payload
  payload="$(printf '{"session_id":"%s","tool_name":"Agent","tool_input":{"subagent_type":"%s"}}' \
    "$TEST_SESSION" "$subagent_type")"
  local exit_code=0
  local output
  output="$(bash "$PRETOOL_HOOK" <<< "$payload" 2>/dev/null)" || exit_code=$?
  printf '%d|%s' "$exit_code" "$output"
}

get_exit_code() { printf '%s' "$1" | cut -d'|' -f1; }
get_output()    { printf '%s' "$1" | cut -d'|' -f2-; }

# ---------------------------------------------------------------------------
# Integration test: full state machine flow
# ---------------------------------------------------------------------------
echo "=== QA gate integration test ==="
echo ""
echo "Scenario: me completes TASK-99 → gate blocks → qa approves → gate clears"
echo ""

cleanup

# --- Step 1: SubagentStop(me) with TASK-99 ---
echo "Step 1: SubagentStop(me, 'Task: TASK-99 completed')"
send_stop "me" "Task: TASK-99 | WP: WP-50\nSummary: implementation done."

PENDING="$("$JQ" -r --arg sid "$TEST_SESSION" \
  '.[$sid].pending_tasks // [] | @json' "$GATE_FILE" 2>/dev/null || echo "[]")"

if printf '%s' "$PENDING" | "$JQ" -e 'contains(["TASK-99"])' > /dev/null 2>&1; then
  ok "Step 1: pending_tasks includes TASK-99 after me completion"
else
  fail "Step 1: TASK-99 not in pending_tasks after me completion: $PENDING"
fi

# --- Step 2: PreToolUse(Bash, "ls") → should be denied ---
echo ""
echo "Step 2: PreToolUse(Bash, 'ls') → expect deny"
RESULT="$(send_pretool_bash "ls")"
EXIT="$(get_exit_code "$RESULT")"
OUTPUT="$(get_output "$RESULT")"

if [[ "$EXIT" -eq 2 ]]; then
  ok "Step 2: Bash 'ls' denied (exit 2) while TASK-99 pending"
else
  fail "Step 2: expected exit 2 (deny), got exit $EXIT"
fi
if printf '%s' "$OUTPUT" | "$JQ" -e '.permissionDecision == "deny"' > /dev/null 2>&1; then
  ok "Step 2: deny response contains permissionDecision=deny"
else
  fail "Step 2: deny response malformed: $OUTPUT"
fi

# --- Step 3: PreToolUse(Agent, subagent_type=qa) → should be allowed ---
echo ""
echo "Step 3: PreToolUse(Agent, subagent_type=qa) → expect allow"
RESULT="$(send_pretool_agent "qa")"
EXIT="$(get_exit_code "$RESULT")"

if [[ "$EXIT" -eq 0 ]]; then
  ok "Step 3: Agent(qa) allowed (exit 0) while TASK-99 pending"
else
  fail "Step 3: expected exit 0 (allow) for Agent(qa), got exit $EXIT"
fi

# --- Step 4: PreToolUse(Bash, "tc task get 99") → safe prefix, should be allowed ---
echo ""
echo "Step 4: PreToolUse(Bash, 'tc task get 99 --json') → expect allow (safe prefix)"
RESULT="$(send_pretool_bash "tc task get 99 --json")"
EXIT="$(get_exit_code "$RESULT")"

if [[ "$EXIT" -eq 0 ]]; then
  ok "Step 4: 'tc task get 99 --json' allowed while pending (safe prefix)"
else
  fail "Step 4: expected exit 0 for safe tc command, got exit $EXIT"
fi

# --- Step 5: SubagentStop(qa, APPROVED) → gate should clear ---
echo ""
echo "Step 5: SubagentStop(qa, 'TASK-99 VERDICT: APPROVED') → expect gate clear"
send_stop "qa" "Task: TASK-99 | WP: WP-51\nAll tests pass.\nVERDICT: APPROVED"

PENDING="$("$JQ" -r --arg sid "$TEST_SESSION" \
  '.[$sid].pending_tasks // [] | @json' "$GATE_FILE" 2>/dev/null || echo "[]")"
PENDING_COUNT="$(printf '%s' "$PENDING" | "$JQ" 'length' 2>/dev/null || echo 1)"

if [[ "$PENDING_COUNT" -eq 0 ]]; then
  ok "Step 5: pending_tasks is empty after qa APPROVED"
else
  fail "Step 5: pending_tasks should be empty after qa APPROVED: $PENDING"
fi

# --- Step 6: PreToolUse(Bash, "ls") → should now be allowed ---
echo ""
echo "Step 6: PreToolUse(Bash, 'ls') → expect allow (gate cleared)"
RESULT="$(send_pretool_bash "ls")"
EXIT="$(get_exit_code "$RESULT")"

if [[ "$EXIT" -eq 0 ]]; then
  ok "Step 6: Bash 'ls' allowed (exit 0) after gate cleared"
else
  fail "Step 6: expected exit 0 (allow) after gate cleared, got exit $EXIT"
fi

echo ""
echo "--- Scenario 2: 3 qa failures → auto-unblock ---"
cleanup

echo ""
echo "Step 1: me completes TASK-88"
send_stop "me" "Task: TASK-88 completed."

echo "Step 2-4: qa fails 3 times"
LAST_OUTPUT=""
for i in 1 2 3; do
  OUTPUT="$(send_stop "qa" "Task: TASK-88\nVERDICT: REJECTED - failing tests" 2>/dev/null || true)"
  if [[ -n "$OUTPUT" ]]; then
    LAST_OUTPUT="$OUTPUT"
  fi
done

PENDING="$("$JQ" -r --arg sid "$TEST_SESSION" \
  '.[$sid].pending_tasks // [] | @json' "$GATE_FILE" 2>/dev/null || echo "[]")"
PENDING_COUNT="$(printf '%s' "$PENDING" | "$JQ" 'length' 2>/dev/null || echo 1)"

if [[ "$PENDING_COUNT" -eq 0 ]]; then
  ok "Scenario 2: TASK-88 auto-unblocked after 3 qa failures"
else
  fail "Scenario 2: expected auto-unblock after 3 failures, got: $PENDING"
fi

if [[ -n "$LAST_OUTPUT" ]] && printf '%s' "$LAST_OUTPUT" | "$JQ" -e '.systemMessage | length > 0' > /dev/null 2>&1; then
  ok "Scenario 2: advisory systemMessage emitted on 3rd failure"
else
  fail "Scenario 2: expected advisory on 3rd failure, got: $LAST_OUTPUT"
fi

echo "Step 5: PreToolUse(Bash) after auto-unblock → expect allow"
RESULT="$(send_pretool_bash "ls")"
EXIT="$(get_exit_code "$RESULT")"

if [[ "$EXIT" -eq 0 ]]; then
  ok "Scenario 2: Bash allowed after auto-unblock"
else
  fail "Scenario 2: expected allow after auto-unblock, got exit $EXIT"
fi

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
cleanup

echo ""
echo "=== Integration test results: $PASS passed, $FAIL failed ==="
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
