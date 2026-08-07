#!/usr/bin/env bash
# test-subagent-stop.sh — Integration tests for subagent-stop.sh QA gate logic
#
# Tests:
#   - Normal me completion activates QA gate (pending_tasks populated)
#   - BLOCKED me completion does NOT activate QA gate
#   - CONFUSED me completion does NOT activate QA gate
#   - CONFUSED is a recognized terminal promise (gate stays clear)
#   - QA pass clears pending_tasks
#
# Usage:
#   .claude/hooks/bin/test-subagent-stop.sh
#
# Exit codes:
#   0 — all tests passed
#   1 — one or more tests failed

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"
HOOK="${SCRIPT_DIR}/../subagent-stop.sh"
STATE_DIR="${SCRIPT_DIR}/../state"
GATE_FILE="${STATE_DIR}/qa-gate.json"
LOG_FILE="${STATE_DIR}/qa-gate.log"
JQ="/usr/bin/jq"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

# Unique session ID per test run to avoid cross-contamination
TEST_SESSION="test-subagent-stop-$$"

# invoke_hook <payload_json> → sets HOOK_EXIT and HOOK_STDOUT
invoke_hook() {
  local payload="$1"
  HOOK_STDOUT="$(printf '%s' "$payload" | bash "$HOOK" 2>/dev/null)"
  HOOK_EXIT=$?
}

assert_exit() {
  local test_name="$1" expected="$2"
  if [[ "$HOOK_EXIT" -eq "$expected" ]]; then
    echo "  PASS [exit=${expected}]: ${test_name}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL [exit=${HOOK_EXIT}, want ${expected}]: ${test_name}"
    FAIL=$((FAIL + 1))
  fi
}

# Assert that a TASK-N is in pending_tasks for TEST_SESSION
assert_in_pending() {
  local test_name="$1" task_id="$2"
  if [[ ! -f "$GATE_FILE" ]]; then
    echo "  FAIL [gate file missing]: ${test_name}"
    FAIL=$((FAIL + 1))
    return
  fi
  local found
  found="$("$JQ" -r --arg sid "$TEST_SESSION" --arg tid "$task_id" \
    '.[$sid].pending_tasks // [] | map(. == $tid) | any' "$GATE_FILE" 2>/dev/null || echo "false")"
  if [[ "$found" == "true" ]]; then
    echo "  PASS [${task_id} in pending_tasks]: ${test_name}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL [${task_id} NOT in pending_tasks, want it there]: ${test_name}"
    FAIL=$((FAIL + 1))
  fi
}

# Assert that a TASK-N is NOT in pending_tasks for TEST_SESSION
assert_not_in_pending() {
  local test_name="$1" task_id="$2"
  if [[ ! -f "$GATE_FILE" ]]; then
    # No gate file means nothing was added — that's a pass
    echo "  PASS [gate file absent → ${task_id} not pending]: ${test_name}"
    PASS=$((PASS + 1))
    return
  fi
  local found
  found="$("$JQ" -r --arg sid "$TEST_SESSION" --arg tid "$task_id" \
    '.[$sid].pending_tasks // [] | map(. == $tid) | any' "$GATE_FILE" 2>/dev/null || echo "false")"
  if [[ "$found" == "false" ]]; then
    echo "  PASS [${task_id} not in pending_tasks]: ${test_name}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL [${task_id} IS in pending_tasks, should NOT be]: ${test_name}"
    FAIL=$((FAIL + 1))
  fi
}

# Build a SubagentStop payload for agent-me
me_payload() {
  local msg="$1"
  printf '{"session_id":"%s","agent_type":"me","last_assistant_message":"%s"}' \
    "$TEST_SESSION" "$(printf '%s' "$msg" | sed 's/"/\\"/g')"
}

# Build a SubagentStop payload for agent-qa
qa_payload() {
  local msg="$1"
  printf '{"session_id":"%s","agent_type":"qa","last_assistant_message":"%s"}' \
    "$TEST_SESSION" "$(printf '%s' "$msg" | sed 's/"/\\"/g')"
}

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
cleanup() {
  # Remove only the test session from the gate file (leave other sessions intact)
  if [[ -f "$GATE_FILE" ]]; then
    local cleaned
    cleaned="$("$JQ" --arg sid "$TEST_SESSION" 'del(.[$sid])' "$GATE_FILE" 2>/dev/null || cat "$GATE_FILE")"
    printf '%s\n' "$cleaned" > "${GATE_FILE}.tmp.$$"
    mv "${GATE_FILE}.tmp.$$" "$GATE_FILE" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# SECTION 1: Normal completion — should activate QA gate
# ---------------------------------------------------------------------------
echo ""
echo "=== Normal me completion (should activate QA gate) ==="

MSG_NORMAL="Task: TASK-42 | WP: WP-10\nFiles Modified:\n- src/auth.py: Added login\nSummary: Implemented login flow.\n<promise>COMPLETE</promise>"

invoke_hook "$(me_payload "$MSG_NORMAL")"
assert_exit "Normal completion exits 0" 0
assert_in_pending "Normal completion adds TASK-42 to pending_tasks" "TASK-42"

# ---------------------------------------------------------------------------
# SECTION 2: BLOCKED me completion — must NOT activate QA gate
# ---------------------------------------------------------------------------
echo ""
echo "=== BLOCKED me completion (must NOT activate QA gate) ==="

MSG_BLOCKED="Working on TASK-99. The planned approach requires X but X is unavailable.\nQUESTION: Should we use approach Y instead?\n<promise>BLOCKED</promise>"

invoke_hook "$(me_payload "$MSG_BLOCKED")"
assert_exit "BLOCKED completion exits 0" 0
assert_not_in_pending "BLOCKED completion does NOT add TASK-99 to pending_tasks" "TASK-99"

# ---------------------------------------------------------------------------
# SECTION 3: CONFUSED me completion — must NOT activate QA gate
# ---------------------------------------------------------------------------
echo ""
echo "=== CONFUSED me completion (must NOT activate QA gate) ==="

MSG_CONFUSED="Working on TASK-77. Hit a genuine decision fork mid-implementation.\n<promise>CONFUSED</promise>\nQUESTION: Should the cache key include the user tenant or not?\nOPTIONS:\n- A: Include tenant in cache key (safe, lower hit rate)\n- B: Shared cache key (higher hit rate, may leak cross-tenant data)\nCONTEXT: Affects both correctness and performance."

invoke_hook "$(me_payload "$MSG_CONFUSED")"
assert_exit "CONFUSED completion exits 0" 0
assert_not_in_pending "CONFUSED completion does NOT add TASK-77 to pending_tasks" "TASK-77"

# ---------------------------------------------------------------------------
# SECTION 4: Verify CONFUSED is a terminal promise distinct from COMPLETE
# ---------------------------------------------------------------------------
echo ""
echo "=== CONFUSED terminal promise — gate stays clear after CONFUSED ==="

# A fresh task that gets CONFUSED (not previously queued)
MSG_CONFUSED_FRESH="Implementing TASK-55. Need user decision before proceeding.\n<promise>CONFUSED</promise>\nQUESTION: Use REST or GraphQL for this endpoint?\nOPTIONS:\n- A: REST\n- B: GraphQL\nCONTEXT: Determines client contract."

invoke_hook "$(me_payload "$MSG_CONFUSED_FRESH")"
assert_exit "CONFUSED fresh task exits 0" 0
assert_not_in_pending "CONFUSED fresh TASK-55 not added to pending_tasks" "TASK-55"

# After CONFUSED, if user answers and me is re-invoked normally, gate should work
MSG_AFTER_CONFUSED="Task: TASK-55 | WP: WP-55\nImplemented REST endpoint per user decision.\n<promise>COMPLETE</promise>"

invoke_hook "$(me_payload "$MSG_AFTER_CONFUSED")"
assert_exit "Post-CONFUSED normal completion exits 0" 0
assert_in_pending "Post-CONFUSED normal TASK-55 IS added to pending_tasks" "TASK-55"

# ---------------------------------------------------------------------------
# SECTION 5: Escape hatch — COPILOT_QA_GATE=off bypasses everything
# ---------------------------------------------------------------------------
echo ""
echo "=== Escape hatch: COPILOT_QA_GATE=off ==="

# Reset the test session state to verify escape hatch independently
cleanup

MSG_ESCAPE="Task: TASK-88 complete. <promise>COMPLETE</promise>"
HOOK_STDOUT="$(printf '%s' "$(me_payload "$MSG_ESCAPE")" | COPILOT_QA_GATE=off bash "$HOOK" 2>/dev/null)"
HOOK_EXIT=$?
if [[ "$HOOK_EXIT" -eq 0 ]]; then
  echo "  PASS [exit=0]: COPILOT_QA_GATE=off exits 0"
  PASS=$((PASS + 1))
else
  echo "  FAIL [exit=${HOOK_EXIT}, want 0]: COPILOT_QA_GATE=off should exit 0"
  FAIL=$((FAIL + 1))
fi
assert_not_in_pending "COPILOT_QA_GATE=off: TASK-88 not added (hook disabled)" "TASK-88"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "==================================================================="
echo "Results: ${PASS} passed, ${FAIL} failed"
echo "==================================================================="

[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
