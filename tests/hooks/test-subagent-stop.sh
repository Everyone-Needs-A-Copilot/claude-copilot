#!/usr/bin/env bash
# test-subagent-stop.sh — Tests for .claude/hooks/subagent-stop.sh
#
# Run: bash tests/hooks/test-subagent-stop.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
HOOK="$PROJECT_ROOT/.claude/hooks/subagent-stop.sh"
STATE_DIR="$PROJECT_ROOT/.claude/hooks/state"
GATE_FILE="${STATE_DIR}/qa-gate.json"
JQ="/usr/bin/jq"

TEST_SESSION="test-subagent-$$"

PASS=0
FAIL=0

ok() {
  echo "  PASS: $1"
  PASS=$((PASS + 1))
}

fail() {
  echo "  FAIL: $1"
  FAIL=$((FAIL + 1))
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
clean_gate() {
  rm -f "$GATE_FILE" "${STATE_DIR}/qa-gate.lock" "${STATE_DIR}/qa-gate.log" 2>/dev/null || true
}

# Send payload to hook; capture exit code and stdout
invoke_hook() {
  local payload="$1"
  local extra_env="${2:-}"
  local exit_code=0
  local output
  if [[ -n "$extra_env" ]]; then
    output="$(eval "env $extra_env bash '$HOOK'" <<< "$payload" 2>/dev/null)" || exit_code=$?
  else
    output="$(bash "$HOOK" <<< "$payload" 2>/dev/null)" || exit_code=$?
  fi
  printf '%d|%s' "$exit_code" "$output"
}

get_exit_code() { printf '%s' "$1" | cut -d'|' -f1; }
get_output()    { printf '%s' "$1" | cut -d'|' -f2-; }

# Build a SubagentStop payload
make_payload() {
  local agent_type="$1"
  local last_msg="$2"
  # Escape double quotes in last_msg for JSON
  local escaped_msg
  escaped_msg="$(printf '%s' "$last_msg" | sed 's/"/\\"/g')"
  printf '{"session_id":"%s","agent_type":"%s","last_assistant_message":"%s"}\n' \
    "$TEST_SESSION" "$agent_type" "$escaped_msg"
}

# Read pending_tasks for TEST_SESSION from gate file
read_pending() {
  if [[ ! -f "$GATE_FILE" ]]; then
    echo "[]"
    return
  fi
  "$JQ" -r --arg sid "$TEST_SESSION" '.[$sid].pending_tasks // [] | @json' "$GATE_FILE" 2>/dev/null || echo "[]"
}

# Read retries for a task
read_retries() {
  local task_id="$1"
  if [[ ! -f "$GATE_FILE" ]]; then
    echo "0"
    return
  fi
  "$JQ" -r --arg sid "$TEST_SESSION" --arg tid "$task_id" \
    '.[$sid].retries[$tid] // 0' "$GATE_FILE" 2>/dev/null || echo "0"
}

# Read last history event
read_last_event() {
  if [[ ! -f "$GATE_FILE" ]]; then
    echo ""
    return
  fi
  "$JQ" -r --arg sid "$TEST_SESSION" \
    '.[$sid].history // [] | if length > 0 then .[-1].event else "" end' "$GATE_FILE" 2>/dev/null || echo ""
}

# ---------------------------------------------------------------------------
# Test 1: me completion with TASK-5 → pending_tasks includes TASK-5
# ---------------------------------------------------------------------------
test_me_completion_adds_task() {
  clean_gate
  local payload
  payload="$(make_payload "me" "Task: TASK-5 | WP: WP-10\nSummary: implementation complete.")"

  local result exit_code
  result="$(invoke_hook "$payload")"
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "me completion: hook exits 0 (non-blocking)"
  else
    fail "me completion: expected exit 0, got $exit_code"
  fi

  local pending
  pending="$(read_pending)"
  if printf '%s' "$pending" | "$JQ" -e 'contains(["TASK-5"])' > /dev/null 2>&1; then
    ok "me completion: TASK-5 added to pending_tasks"
  else
    fail "me completion: TASK-5 not in pending_tasks: $pending"
  fi

  local last_event
  last_event="$(read_last_event)"
  if [[ "$last_event" == "me_completed" ]]; then
    ok "me completion: history event is me_completed"
  else
    fail "me completion: expected me_completed event, got: $last_event"
  fi
}

# ---------------------------------------------------------------------------
# Test 2: me completion without TASK-N → state unchanged, warning logged
# ---------------------------------------------------------------------------
test_me_completion_no_task_id() {
  clean_gate
  local payload
  payload="$(make_payload "me" "Implementation done. See attached work product.")"

  local result exit_code
  result="$(invoke_hook "$payload")"
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "me completion no task-id: hook exits 0"
  else
    fail "me completion no task-id: expected exit 0, got $exit_code"
  fi

  local pending
  pending="$(read_pending)"
  local pending_count
  pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 0)"
  if [[ "$pending_count" -eq 0 ]]; then
    ok "me completion no task-id: pending_tasks unchanged (empty)"
  else
    fail "me completion no task-id: pending_tasks should be empty: $pending"
  fi

  # Warning should be logged
  if [[ -f "${STATE_DIR}/qa-gate.log" ]] && grep -q "no TASK-N found" "${STATE_DIR}/qa-gate.log" 2>/dev/null; then
    ok "me completion no task-id: warning logged to qa-gate.log"
  else
    fail "me completion no task-id: expected warning in qa-gate.log"
  fi
}

# ---------------------------------------------------------------------------
# Test 3: qa completion with APPROVED verdict → pending_tasks cleared
# ---------------------------------------------------------------------------
test_qa_approved_clears_pending() {
  clean_gate
  # First put TASK-5 in pending via me completion
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-5 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  # Verify it was added
  local pending
  pending="$(read_pending)"
  if ! printf '%s' "$pending" | "$JQ" -e 'contains(["TASK-5"])' > /dev/null 2>&1; then
    fail "qa approved test: pre-condition failed, TASK-5 not in pending after me completion"
    return
  fi

  # Now qa approves
  local payload_qa
  payload_qa="$(make_payload "qa" "Task: TASK-5 | WP: WP-20\nVERDICT: APPROVED")"
  local result
  result="$(invoke_hook "$payload_qa")"
  local exit_code
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "qa APPROVED: hook exits 0"
  else
    fail "qa APPROVED: expected exit 0, got $exit_code"
  fi

  pending="$(read_pending)"
  local pending_count
  pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
  if [[ "$pending_count" -eq 0 ]]; then
    ok "qa APPROVED: TASK-5 removed from pending_tasks"
  else
    fail "qa APPROVED: pending_tasks should be empty: $pending"
  fi

  local last_event
  last_event="$(read_last_event)"
  if [[ "$last_event" == "qa_passed" ]]; then
    ok "qa APPROVED: history event is qa_passed"
  else
    fail "qa APPROVED: expected qa_passed event, got: $last_event"
  fi
}

# ---------------------------------------------------------------------------
# Test 4: qa completion with APPROVED-WITH-MINOR-FIXES → also clears pending
# ---------------------------------------------------------------------------
test_qa_approved_minor_fixes_clears_pending() {
  clean_gate
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-7 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  local payload_qa
  payload_qa="$(make_payload "qa" "Task: TASK-7\nVERDICT: APPROVED-WITH-MINOR-FIXES")"
  invoke_hook "$payload_qa" > /dev/null 2>&1 || true

  local pending
  pending="$(read_pending)"
  local pending_count
  pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
  if [[ "$pending_count" -eq 0 ]]; then
    ok "qa APPROVED-WITH-MINOR-FIXES: TASK-7 removed from pending_tasks"
  else
    fail "qa APPROVED-WITH-MINOR-FIXES: pending_tasks should be empty: $pending"
  fi
}

# ---------------------------------------------------------------------------
# Test 5: qa completion with REJECTED verdict → retries incremented
# ---------------------------------------------------------------------------
test_qa_rejected_increments_retries() {
  clean_gate
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-5 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  local payload_qa
  payload_qa="$(make_payload "qa" "Task: TASK-5\nVERDICT: REJECTED - tests fail")"
  local result
  result="$(invoke_hook "$payload_qa")"
  local exit_code
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "qa REJECTED: hook exits 0"
  else
    fail "qa REJECTED: expected exit 0, got $exit_code"
  fi

  local retries
  retries="$(read_retries "TASK-5")"
  if [[ "$retries" -eq 1 ]]; then
    ok "qa REJECTED: retries for TASK-5 incremented to 1"
  else
    fail "qa REJECTED: expected retries=1, got $retries"
  fi

  # Task still in pending
  local pending
  pending="$(read_pending)"
  if printf '%s' "$pending" | "$JQ" -e 'contains(["TASK-5"])' > /dev/null 2>&1; then
    ok "qa REJECTED: TASK-5 still in pending_tasks (gate remains active)"
  else
    fail "qa REJECTED: TASK-5 should remain in pending_tasks: $pending"
  fi

  local last_event
  last_event="$(read_last_event)"
  if [[ "$last_event" == "qa_failed_retry_1" ]]; then
    ok "qa REJECTED: history event is qa_failed_retry_1"
  else
    fail "qa REJECTED: expected qa_failed_retry_1 event, got: $last_event"
  fi
}

# ---------------------------------------------------------------------------
# Test 6: 3 consecutive qa failures → task auto-unblocked, advisory emitted
# ---------------------------------------------------------------------------
test_qa_three_failures_auto_unblock() {
  clean_gate

  # Put TASK-5 in pending
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-5 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  local advisory_output=""

  # Fail 3 times
  local i
  for i in 1 2 3; do
    local payload_qa
    payload_qa="$(make_payload "qa" "Task: TASK-5\nVERDICT: REJECTED - tests still failing")"
    local result
    result="$(invoke_hook "$payload_qa")"
    local exit_code output
    exit_code="$(get_exit_code "$result")"
    output="$(get_output "$result")"
    if [[ "$exit_code" -ne 0 ]]; then
      fail "qa 3-failure test: failure $i expected exit 0, got $exit_code"
    fi
    if [[ -n "$output" ]]; then
      advisory_output="$output"
    fi
  done

  # After 3 failures: task should be removed from pending (auto-unblock)
  local pending
  pending="$(read_pending)"
  local pending_count
  pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
  if [[ "$pending_count" -eq 0 ]]; then
    ok "qa 3-failures: TASK-5 auto-unblocked (removed from pending_tasks)"
  else
    fail "qa 3-failures: TASK-5 should be auto-unblocked: $pending"
  fi

  # Advisory should have been emitted (on the 3rd failure invocation)
  if [[ -n "$advisory_output" ]] && printf '%s' "$advisory_output" | "$JQ" -e '.systemMessage | length > 0' > /dev/null 2>&1; then
    ok "qa 3-failures: advisory systemMessage emitted"
  else
    fail "qa 3-failures: expected advisory systemMessage, got: $advisory_output"
  fi

  # Advisory should mention human review
  if printf '%s' "$advisory_output" | "$JQ" -r '.systemMessage' | grep -qi "human review"; then
    ok "qa 3-failures: advisory mentions human review"
  else
    fail "qa 3-failures: advisory should mention human review: $advisory_output"
  fi

  # History should record advisory_unblock event
  local last_event
  last_event="$(read_last_event)"
  if [[ "$last_event" == "qa_failed_advisory_unblock" ]]; then
    ok "qa 3-failures: history event is qa_failed_advisory_unblock"
  else
    fail "qa 3-failures: expected qa_failed_advisory_unblock event, got: $last_event"
  fi
}

# ---------------------------------------------------------------------------
# Test 7: qa verdict parsing — implicit pass (COMPLETE promise, no REJECTED)
# ---------------------------------------------------------------------------
test_qa_implicit_pass() {
  clean_gate
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-8 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  # qa message uses COMPLETE promise but no explicit VERDICT token
  local payload_qa
  payload_qa="$(make_payload "qa" "Task: TASK-8 | WP: WP-22\nAll tests pass.\n<promise>COMPLETE</promise>")"
  invoke_hook "$payload_qa" > /dev/null 2>&1 || true

  local pending
  pending="$(read_pending)"
  local pending_count
  pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
  if [[ "$pending_count" -eq 0 ]]; then
    ok "qa implicit pass: COMPLETE promise without REJECTED → treated as pass, TASK-8 cleared"
  else
    fail "qa implicit pass: expected pending cleared, got: $pending"
  fi
}

# ---------------------------------------------------------------------------
# Test 8: Unrelated agent type (ta) → no state change
# ---------------------------------------------------------------------------
test_unrelated_agent_no_change() {
  clean_gate
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-20 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  # ta agent stop fires
  local payload_ta
  payload_ta="$(make_payload "ta" "Task: TASK-20 architecture review done.")"
  local result exit_code
  result="$(invoke_hook "$payload_ta")"
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "unrelated agent (ta): hook exits 0"
  else
    fail "unrelated agent (ta): expected exit 0, got $exit_code"
  fi

  # TASK-20 should still be in pending (ta did not affect it)
  local pending
  pending="$(read_pending)"
  if printf '%s' "$pending" | "$JQ" -e 'contains(["TASK-20"])' > /dev/null 2>&1; then
    ok "unrelated agent (ta): TASK-20 still in pending (ta stop had no effect)"
  else
    fail "unrelated agent (ta): TASK-20 should still be in pending: $pending"
  fi
}

# ---------------------------------------------------------------------------
# Test 9: COPILOT_QA_GATE=off escape hatch → hook exits immediately
# ---------------------------------------------------------------------------
test_escape_hatch() {
  clean_gate
  local payload
  payload="$(make_payload "me" "Task: TASK-99 completed.")"

  invoke_hook "$payload" "COPILOT_QA_GATE=off" > /dev/null 2>&1 || true

  # No gate file should have been created
  if [[ ! -f "$GATE_FILE" ]]; then
    ok "escape hatch: COPILOT_QA_GATE=off → no gate file created"
  else
    # Gate file existed before, check it's empty/unchanged
    local pending
    pending="$(read_pending)"
    local pending_count
    pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 0)"
    if [[ "$pending_count" -eq 0 ]]; then
      ok "escape hatch: COPILOT_QA_GATE=off → no tasks added to pending"
    else
      fail "escape hatch: COPILOT_QA_GATE=off should not add tasks, got: $pending"
    fi
  fi
}

# ---------------------------------------------------------------------------
# Test 10: Empty payload → exits cleanly
# ---------------------------------------------------------------------------
test_empty_payload() {
  local exit_code=0
  bash "$HOOK" <<< "" 2>/dev/null || exit_code=$?
  if [[ "$exit_code" -eq 0 ]]; then
    ok "empty payload: hook exits 0 (safe allow)"
  else
    fail "empty payload: expected exit 0, got $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 11: me completes multiple tasks in same session
# ---------------------------------------------------------------------------
test_me_multiple_tasks_same_session() {
  clean_gate

  # me completes TASK-3
  local p1
  p1="$(make_payload "me" "Task: TASK-3 | WP: WP-5\nSummary: done.")"
  bash "$HOOK" <<< "$p1" > /dev/null 2>&1 || true

  # me completes TASK-4 (different task in same session)
  local p2
  p2="$(make_payload "me" "Task: TASK-4 | WP: WP-6\nSummary: done.")"
  bash "$HOOK" <<< "$p2" > /dev/null 2>&1 || true

  local pending
  pending="$(read_pending)"
  if printf '%s' "$pending" | "$JQ" -e 'contains(["TASK-3","TASK-4"])' > /dev/null 2>&1; then
    ok "multiple me tasks: TASK-3 and TASK-4 both in pending_tasks"
  else
    fail "multiple me tasks: expected both TASK-3 and TASK-4, got: $pending"
  fi

  # qa approves TASK-3 only
  local p3
  p3="$(make_payload "qa" "Task: TASK-3\nVERDICT: APPROVED")"
  bash "$HOOK" <<< "$p3" > /dev/null 2>&1 || true

  pending="$(read_pending)"
  if ! printf '%s' "$pending" | "$JQ" -e 'contains(["TASK-3"])' > /dev/null 2>&1 \
     && printf '%s' "$pending" | "$JQ" -e 'contains(["TASK-4"])' > /dev/null 2>&1; then
    ok "multiple me tasks: after TASK-3 approved, only TASK-4 remains in pending"
  else
    fail "multiple me tasks: expected TASK-4 only in pending, got: $pending"
  fi
}

# ---------------------------------------------------------------------------
# Test 12: me completion is idempotent (same task twice → not duplicated)
# ---------------------------------------------------------------------------
test_me_idempotent() {
  clean_gate
  local payload
  payload="$(make_payload "me" "Task: TASK-6 completed.")"

  bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true
  bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true

  local pending
  pending="$(read_pending)"
  local task_count
  task_count="$(printf '%s' "$pending" | "$JQ" '[.[] | select(. == "TASK-6")] | length' 2>/dev/null || echo 0)"
  if [[ "$task_count" -eq 1 ]]; then
    ok "me idempotent: TASK-6 appears exactly once in pending_tasks despite two calls"
  else
    fail "me idempotent: TASK-6 should appear once, got count=$task_count in: $pending"
  fi
}

# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------
echo "=== subagent-stop.sh tests ==="
echo ""
echo "--- Test 1: me completion with TASK-5 adds to pending_tasks"
test_me_completion_adds_task
echo "--- Test 2: me completion without TASK-N → state unchanged, warning logged"
test_me_completion_no_task_id
echo "--- Test 3: qa APPROVED → pending_tasks cleared"
test_qa_approved_clears_pending
echo "--- Test 4: qa APPROVED-WITH-MINOR-FIXES → pending_tasks cleared"
test_qa_approved_minor_fixes_clears_pending
echo "--- Test 5: qa REJECTED → retries incremented, task stays pending"
test_qa_rejected_increments_retries
echo "--- Test 6: 3 consecutive qa failures → auto-unblock + advisory"
test_qa_three_failures_auto_unblock
echo "--- Test 7: qa implicit pass (COMPLETE promise, no REJECTED)"
test_qa_implicit_pass
echo "--- Test 8: Unrelated agent type (ta) → no state change"
test_unrelated_agent_no_change
echo "--- Test 9: COPILOT_QA_GATE=off escape hatch"
test_escape_hatch
echo "--- Test 10: Empty payload → exits cleanly"
test_empty_payload
echo "--- Test 11: Multiple tasks same session"
test_me_multiple_tasks_same_session
echo "--- Test 12: me completion idempotent (no duplicate pending entries)"
test_me_idempotent

# Clean up
clean_gate

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
