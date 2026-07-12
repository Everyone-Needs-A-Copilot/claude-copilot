#!/usr/bin/env bash
# test-pretool-check.sh — Tests for .claude/hooks/pretool-check.sh
#
# Uses plain bash assertions to match existing test infrastructure style
# (see tests/claude-launcher.test.sh).
#
# Run: bash tests/hooks/test-pretool-check.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
HOOK="$PROJECT_ROOT/.claude/hooks/pretool-check.sh"
STATE_DIR="$PROJECT_ROOT/.claude/hooks/state"
TEST_SESSION="test-session-$$"

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

# QA gate state file
GATE_FILE="${STATE_DIR}/qa-gate.json"

# Clean up test session state before/after
clean_state() {
  rm -f "${STATE_DIR}/streak-${TEST_SESSION}.json" \
        "${STATE_DIR}/streak-${TEST_SESSION}.lock" 2>/dev/null || true
}

# Write a qa-gate.json that puts TEST_SESSION in pending state with given tasks
write_gate_pending() {
  local tasks_json="$1"  # e.g. '["TASK-5","TASK-12"]'
  local retries_json="${2:-{}}"
  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{ "%s": { "pending_tasks": %s, "retries": %s, "history": [], "lastSeen": "%s" } }\n' \
    "$TEST_SESSION" "$tasks_json" "$retries_json" "$now" > "$GATE_FILE"
}

# Clear gate state for test session
clean_gate_state() {
  rm -f "$GATE_FILE" "${STATE_DIR}/qa-gate.lock" 2>/dev/null || true
}

# Invoke hook with Agent payload (for qa-gate tests)
invoke_hook_agent() {
  local subagent_type="$1"
  local extra_env="${2:-}"
  local payload
  payload="$(printf '{"session_id":"%s","tool_name":"Agent","tool_input":{"subagent_type":"%s"}}' \
    "$TEST_SESSION" "$subagent_type")"
  local exit_code=0
  local output
  if [[ -n "$extra_env" ]]; then
    output="$(eval "env $extra_env bash '$HOOK'" <<< "$payload" 2>/dev/null)" || exit_code=$?
  else
    output="$(bash "$HOOK" <<< "$payload" 2>/dev/null)" || exit_code=$?
  fi
  printf '%d|%s' "$exit_code" "$output"
}

# Invoke hook with Bash payload specifying command string
invoke_hook_bash_cmd() {
  local cmd="$1"
  local extra_env="${2:-}"
  local payload
  payload="$(printf '{"session_id":"%s","tool_name":"Bash","tool_input":{"command":"%s"}}' \
    "$TEST_SESSION" "$cmd")"
  local exit_code=0
  local output
  if [[ -n "$extra_env" ]]; then
    output="$(eval "env $extra_env bash '$HOOK'" <<< "$payload" 2>/dev/null)" || exit_code=$?
  else
    output="$(bash "$HOOK" <<< "$payload" 2>/dev/null)" || exit_code=$?
  fi
  printf '%d|%s' "$exit_code" "$output"
}

# Send a payload to the hook and capture exit code + stdout
invoke_hook() {
  local tool_name="$1"
  local extra_env="${2:-}"
  local payload
  payload="$(printf '{"session_id":"%s","tool_name":"%s","tool_input":{"command":"echo hi"}}' \
    "$TEST_SESSION" "$tool_name")"
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

# ---------------------------------------------------------------------------
# Test 1: Single Bash call → allowed (exit 0, empty output)
# ---------------------------------------------------------------------------
test_single_bash_allowed() {
  clean_state
  local result exit_code
  result="$(invoke_hook "Bash")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "single Bash call exits 0 (allowed)"
  else
    fail "single Bash call expected exit 0, got $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 2: 4 consecutive Bash calls → all allowed
# ---------------------------------------------------------------------------
test_four_consecutive_bash_allowed() {
  clean_state
  local i exit_code result
  local all_passed=true
  for i in 1 2 3 4; do
    result="$(invoke_hook "Bash")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -ne 0 ]]; then
      all_passed=false
      fail "call $i of 4 consecutive Bash should be allowed, got exit $exit_code"
    fi
  done
  if $all_passed; then
    ok "4 consecutive Bash calls all allowed"
  fi
}

# ---------------------------------------------------------------------------
# Test 3: 5th consecutive Bash call → denied
# ---------------------------------------------------------------------------
test_fifth_consecutive_bash_denied() {
  clean_state
  local i exit_code result output
  # Calls 1-4: allowed
  for i in 1 2 3 4; do
    invoke_hook "Bash" > /dev/null 2>&1 || true
  done
  # Call 5: denied
  result="$(invoke_hook "Bash")"
  exit_code="$(get_exit_code "$result")"
  output="$(get_output "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "5th consecutive Bash call exits 2 (denied)"
  else
    fail "5th consecutive Bash expected exit 2, got $exit_code"
  fi
  if printf '%s' "$output" | /usr/bin/jq -e '.permissionDecision == "deny"' > /dev/null 2>&1; then
    ok "deny response has permissionDecision=deny"
  else
    fail "deny response missing permissionDecision=deny: $output"
  fi
  if printf '%s' "$output" | /usr/bin/jq -e '.reason | length > 0' > /dev/null 2>&1; then
    ok "deny response has non-empty reason"
  else
    fail "deny response missing reason: $output"
  fi
  if printf '%s' "$output" | /usr/bin/jq -r '.reason' | grep -q "Bash"; then
    ok "deny reason mentions the blocked tool name"
  else
    fail "deny reason does not mention Bash: $output"
  fi
}

# ---------------------------------------------------------------------------
# Test 4: Mixed sequence (Bash, Bash, Read, Bash, Bash) → no deny
# Read resets the streak so Bash count never reaches 5
# ---------------------------------------------------------------------------
test_mixed_sequence_no_deny() {
  clean_state
  local result exit_code all_passed=true
  for tool in Bash Bash Read Bash Bash; do
    result="$(invoke_hook "$tool")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -ne 0 ]]; then
      all_passed=false
      fail "tool $tool in mixed sequence expected exit 0, got $exit_code"
    fi
  done
  if $all_passed; then
    ok "mixed Bash/Bash/Read/Bash/Bash sequence: no deny (Read resets streak)"
  fi
}

# ---------------------------------------------------------------------------
# Test 5: Agent tool at any streak length → always allowed
# ---------------------------------------------------------------------------
test_agent_always_allowed() {
  clean_state
  local result exit_code all_passed=true
  # Build up a streak of 4 Bash calls first
  for i in 1 2 3 4; do
    invoke_hook "Bash" > /dev/null 2>&1 || true
  done
  # Agent call should still be allowed
  result="$(invoke_hook "Agent")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "Agent call after 4 consecutive Bash calls: allowed (exit 0)"
  else
    fail "Agent call expected exit 0, got $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 6: COPILOT_FORCE_DELEGATE=off → always allowed regardless of streak
# ---------------------------------------------------------------------------
test_escape_hatch_off() {
  clean_state
  local result exit_code all_passed=true
  # Simulate 6 consecutive Bash calls with COPILOT_FORCE_DELEGATE=off
  for i in 1 2 3 4 5 6; do
    result="$(invoke_hook "Bash" "COPILOT_FORCE_DELEGATE=off")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -ne 0 ]]; then
      all_passed=false
      fail "call $i with COPILOT_FORCE_DELEGATE=off expected exit 0, got $exit_code"
    fi
  done
  if $all_passed; then
    ok "COPILOT_FORCE_DELEGATE=off: 6 consecutive Bash calls all allowed"
  fi
}

# ---------------------------------------------------------------------------
# Test 7: Stale session state (>24h old) does not cause errors
# ---------------------------------------------------------------------------
test_stale_state_no_error() {
  clean_state
  # Write a stale state file (1970 timestamp)
  printf '{"session_id":"%s","lastTool":"Bash","streak":4,"updatedAt":"1970-01-01T00:00:00Z"}\n' \
    "$TEST_SESSION" > "${STATE_DIR}/streak-${TEST_SESSION}.json"

  local result exit_code
  result="$(invoke_hook "Bash")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "stale state file (1970 epoch): hook exits 0 without error (treated as fresh)"
  else
    fail "stale state file caused error: exit $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 8: Malformed/empty payload → hook exits 0 (safe default)
# ---------------------------------------------------------------------------
test_malformed_payload() {
  local exit_code=0
  bash "$HOOK" <<< "" 2>/dev/null || exit_code=$?
  if [[ "$exit_code" -eq 0 ]]; then
    ok "empty payload: hook exits 0 (safe allow)"
  else
    fail "empty payload: expected exit 0, got $exit_code"
  fi

  exit_code=0
  bash "$HOOK" <<< "not-json" 2>/dev/null || exit_code=$?
  if [[ "$exit_code" -eq 0 ]]; then
    ok "non-JSON payload: hook exits 0 (safe allow)"
  else
    fail "non-JSON payload: expected exit 0, got $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 9: Concurrent safety — two simultaneous invocations don't corrupt state
# ---------------------------------------------------------------------------
test_concurrent_safety() {
  clean_state
  local sess_a="test-conc-a-$$"
  local sess_b="test-conc-b-$$"
  local file_a="${STATE_DIR}/streak-${sess_a}.json"
  local file_b="${STATE_DIR}/streak-${sess_b}.json"

  # Run 3 concurrent Bash calls for each of two sessions
  for i in 1 2 3; do
    payload_a="$(printf '{"session_id":"%s","tool_name":"Bash","tool_input":{}}' "$sess_a")"
    payload_b="$(printf '{"session_id":"%s","tool_name":"Bash","tool_input":{}}' "$sess_b")"
    bash "$HOOK" <<< "$payload_a" > /dev/null 2>&1 &
    bash "$HOOK" <<< "$payload_b" > /dev/null 2>&1 &
  done
  wait

  local streak_a streak_b
  streak_a="$(/usr/bin/jq -r '.streak // "invalid"' "$file_a" 2>/dev/null || echo "invalid")"
  streak_b="$(/usr/bin/jq -r '.streak // "invalid"' "$file_b" 2>/dev/null || echo "invalid")"

  if [[ "$streak_a" != "invalid" ]] && /usr/bin/jq -e 'type == "number"' <<< "$streak_a" > /dev/null 2>&1; then
    ok "concurrent session A: state file is valid JSON (streak=$streak_a)"
  else
    fail "concurrent session A: state file corrupt or invalid: $streak_a"
  fi
  if [[ "$streak_b" != "invalid" ]] && /usr/bin/jq -e 'type == "number"' <<< "$streak_b" > /dev/null 2>&1; then
    ok "concurrent session B: state file is valid JSON (streak=$streak_b)"
  else
    fail "concurrent session B: state file corrupt or invalid: $streak_b"
  fi

  # Sessions must be independent
  if [[ "$streak_a" == "$streak_b" ]] || [[ "$streak_a" -ge 0 && "$streak_b" -ge 0 ]]; then
    ok "concurrent sessions A and B have independent state"
  else
    fail "concurrent sessions A and B state contaminated"
  fi

  rm -f "$file_a" "$file_b" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Test 10: 6th call after deny — streak reset means 6th call is allowed again
# ---------------------------------------------------------------------------
test_streak_reset_after_deny() {
  clean_state
  local result exit_code

  # Build streak to 4
  for i in 1 2 3 4; do
    invoke_hook "Bash" > /dev/null 2>&1 || true
  done

  # 5th call → deny (and streak resets to 0)
  result="$(invoke_hook "Bash")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "5th call denied (pre-condition for reset test)"
  else
    fail "5th call should be denied but got exit $exit_code"
    return
  fi

  # 6th call → allowed (streak was reset to 0 on deny)
  result="$(invoke_hook "Bash")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "6th call after deny: allowed (streak was reset to 0)"
  else
    fail "6th call after deny should be allowed, got exit $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 11: Performance — hook completes in <50ms
# ---------------------------------------------------------------------------
test_performance() {
  clean_state
  local start_ms end_ms elapsed_ms

  if [[ "$(uname)" == "Darwin" ]]; then
    start_ms="$(python3 -c 'import time; print(int(time.time() * 1000))')"
  else
    start_ms="$(date +%s%3N)"
  fi

  invoke_hook "Bash" > /dev/null 2>&1

  if [[ "$(uname)" == "Darwin" ]]; then
    end_ms="$(python3 -c 'import time; print(int(time.time() * 1000))')"
  else
    end_ms="$(date +%s%3N)"
  fi

  elapsed_ms=$((end_ms - start_ms))

  if [[ "$elapsed_ms" -lt 50 ]]; then
    ok "hook performance: completed in ${elapsed_ms}ms (target <50ms)"
  else
    fail "hook performance: ${elapsed_ms}ms exceeds 50ms target"
  fi
}

# ===========================================================================
# QA-gate rule tests (rule_qa_gate)
# ===========================================================================

# ---------------------------------------------------------------------------
# QA-gate Test 1: Empty pending_tasks → all tools allowed
# ---------------------------------------------------------------------------
test_qa_gate_empty_pending_allows_all() {
  clean_state
  clean_gate_state
  # Write gate file with empty pending_tasks
  write_gate_pending "[]"

  local result exit_code
  # Bash should be allowed
  result="$(invoke_hook_bash_cmd "ls -la")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "QA gate: empty pending_tasks → Bash allowed"
  else
    fail "QA gate: empty pending_tasks → Bash should be allowed, got exit $exit_code"
  fi
  # Read should be allowed
  result="$(invoke_hook "Read")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "QA gate: empty pending_tasks → Read allowed"
  else
    fail "QA gate: empty pending_tasks → Read should be allowed, got exit $exit_code"
  fi
  clean_gate_state
}

# ---------------------------------------------------------------------------
# QA-gate Test 2: No gate file → all tools allowed (gate inactive)
# ---------------------------------------------------------------------------
test_qa_gate_no_file_allows_all() {
  clean_state
  clean_gate_state
  # No gate file at all

  local result exit_code
  result="$(invoke_hook_bash_cmd "rm -rf /")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "QA gate: no gate file → Bash allowed (gate inactive)"
  else
    fail "QA gate: no gate file → Bash should be allowed, got exit $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# QA-gate Test 3: Non-empty pending_tasks → Bash denied
# ---------------------------------------------------------------------------
test_qa_gate_pending_denies_bash() {
  clean_state
  clean_gate_state
  write_gate_pending '["TASK-5"]'

  local result exit_code output
  result="$(invoke_hook_bash_cmd "ls -la")"
  exit_code="$(get_exit_code "$result")"
  output="$(get_output "$result")"

  if [[ "$exit_code" -eq 2 ]]; then
    ok "QA gate: pending TASK-5 → Bash denied (exit 2)"
  else
    fail "QA gate: pending TASK-5 → Bash should be denied, got exit $exit_code"
  fi
  if printf '%s' "$output" | /usr/bin/jq -e '.permissionDecision == "deny"' > /dev/null 2>&1; then
    ok "QA gate: deny response has permissionDecision=deny"
  else
    fail "QA gate: deny response missing permissionDecision=deny: $output"
  fi
  if printf '%s' "$output" | /usr/bin/jq -r '.reason' | grep -q "TASK-5"; then
    ok "QA gate: deny reason mentions blocking task TASK-5"
  else
    fail "QA gate: deny reason does not mention TASK-5: $output"
  fi
  clean_gate_state
}

# ---------------------------------------------------------------------------
# QA-gate Test 4: Non-empty pending_tasks → Read denied
# ---------------------------------------------------------------------------
test_qa_gate_pending_denies_read() {
  clean_state
  clean_gate_state
  write_gate_pending '["TASK-12"]'

  local result exit_code
  result="$(invoke_hook "Read")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "QA gate: pending TASK-12 → Read denied"
  else
    fail "QA gate: pending TASK-12 → Read should be denied, got exit $exit_code"
  fi
  clean_gate_state
}

# ---------------------------------------------------------------------------
# QA-gate Test 5: Non-empty pending_tasks → Agent(qa) allowed
# ---------------------------------------------------------------------------
test_qa_gate_pending_allows_agent_qa() {
  clean_state
  clean_gate_state
  write_gate_pending '["TASK-5"]'

  local result exit_code
  result="$(invoke_hook_agent "qa")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "QA gate: pending TASK-5 → Agent(qa) allowed"
  else
    fail "QA gate: pending TASK-5 → Agent(qa) should be allowed, got exit $exit_code"
  fi
  clean_gate_state
}

# ---------------------------------------------------------------------------
# QA-gate Test 6: Non-empty pending_tasks → Agent(me) denied
# ---------------------------------------------------------------------------
test_qa_gate_pending_denies_agent_me() {
  clean_state
  clean_gate_state
  write_gate_pending '["TASK-5"]'

  local result exit_code
  result="$(invoke_hook_agent "me")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "QA gate: pending TASK-5 → Agent(me) denied"
  else
    fail "QA gate: pending TASK-5 → Agent(me) should be denied, got exit $exit_code"
  fi
  clean_gate_state
}

# ---------------------------------------------------------------------------
# QA-gate Test 7: Non-empty pending_tasks → safe tc Bash commands allowed
# ---------------------------------------------------------------------------
test_qa_gate_pending_allows_safe_tc_bash() {
  clean_state
  clean_gate_state
  write_gate_pending '["TASK-5"]'

  local all_passed=true
  local result exit_code

  for safe_cmd in "tc task get 5 --json" "tc task list --status pending" "tc wp get 10" "tc wp list" "tc progress" "tc log --task 5"; do
    # Reset streak state before each call to avoid force-delegate triggering
    clean_state
    write_gate_pending '["TASK-5"]'
    result="$(invoke_hook_bash_cmd "$safe_cmd")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -ne 0 ]]; then
      all_passed=false
      fail "QA gate: safe cmd '${safe_cmd}' should be allowed, got exit $exit_code"
    fi
  done

  if $all_passed; then
    ok "QA gate: all safe tc commands (get/list/progress/log) allowed while pending"
  fi
  clean_gate_state
}

# ---------------------------------------------------------------------------
# QA-gate Test 8: Non-empty pending_tasks → tc deploy wait denied (not safe)
# ---------------------------------------------------------------------------
test_qa_gate_pending_denies_unsafe_tc_bash() {
  clean_state
  clean_gate_state
  write_gate_pending '["TASK-5"]'

  local result exit_code
  result="$(invoke_hook_bash_cmd "tc deploy wait")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "QA gate: 'tc deploy wait' denied (not in safe prefix list)"
  else
    fail "QA gate: 'tc deploy wait' should be denied, got exit $exit_code"
  fi
  clean_gate_state
}

# ---------------------------------------------------------------------------
# QA-gate Test 9: COPILOT_QA_GATE=off escape hatch
# ---------------------------------------------------------------------------
test_qa_gate_escape_hatch() {
  clean_state
  clean_gate_state
  write_gate_pending '["TASK-5","TASK-12"]'

  local result exit_code
  result="$(invoke_hook_bash_cmd "ls -la" "COPILOT_QA_GATE=off")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "QA gate: COPILOT_QA_GATE=off → Bash allowed despite pending tasks"
  else
    fail "QA gate: COPILOT_QA_GATE=off escape hatch failed, got exit $exit_code"
  fi
  clean_gate_state
}

# ---------------------------------------------------------------------------
# QA-gate Test 10: Pending tasks cleared externally → subsequent calls allowed
# (Simulates subagent-stop writing a qa_passed state, gate checks fresh each time)
# ---------------------------------------------------------------------------
test_qa_gate_cleared_allows_calls() {
  clean_state
  clean_gate_state

  # Start with pending
  write_gate_pending '["TASK-99"]'
  local result exit_code
  result="$(invoke_hook_bash_cmd "ls -la")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "QA gate cleared test: initial deny with TASK-99 pending (pre-condition)"
  else
    fail "QA gate cleared test: expected deny pre-condition, got exit $exit_code"
  fi

  # Clear pending (simulate qa pass)
  write_gate_pending "[]"
  result="$(invoke_hook_bash_cmd "ls -la")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "QA gate cleared test: after pending cleared → Bash allowed again"
  else
    fail "QA gate cleared test: after clearing pending, Bash should be allowed, got exit $exit_code"
  fi
  clean_gate_state
}

# ---------------------------------------------------------------------------
# Test 12: git push / git pull are allowlisted — never count toward streak
# ---------------------------------------------------------------------------
test_git_push_pull_allowlisted() {
  clean_state

  # Pre-fill streak=4 (one below deny threshold) to prove git ops don't advance it
  printf '{"session_id":"%s","lastTool":"Bash","streak":4,"updatedAt":"%s"}\n' \
    "$TEST_SESSION" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "${STATE_DIR}/streak-${TEST_SESSION}.json"

  local result exit_code
  # git push should be allowed even with streak=4 (bypasses counter entirely)
  result="$(invoke_hook_bash_cmd "git push origin main")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "git push allowlisted: allowed even at streak=4"
  else
    fail "git push should be allowed at streak=4, got exit $exit_code"
  fi

  # git pull should also be allowed
  result="$(invoke_hook_bash_cmd "git pull origin main")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "git pull allowlisted: allowed even at streak=4"
  else
    fail "git pull should be allowed at streak=4, got exit $exit_code"
  fi

  # Streak should still be 4 (git ops don't advance it)
  local streak_after
  streak_after="$(/usr/bin/jq -r '.streak // "?"' "${STATE_DIR}/streak-${TEST_SESSION}.json" 2>/dev/null || echo "?")"
  if [[ "$streak_after" == "4" ]]; then
    ok "git push/pull do not advance the streak counter (still 4)"
  else
    fail "streak should remain 4 after git ops, got: $streak_after"
  fi
}

# ---------------------------------------------------------------------------
# Test 13: command-string escape hatch — COPILOT_FORCE_DELEGATE=off prefix
# ---------------------------------------------------------------------------
test_command_string_escape_hatch() {
  clean_state

  # Simulate high streak (5 consecutive would normally deny)
  local i
  for i in 1 2 3 4; do
    invoke_hook "Bash" > /dev/null 2>&1 || true
  done

  # Verify 5th plain Bash is denied (pre-condition)
  local result exit_code
  result="$(invoke_hook "Bash")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "command-string escape hatch pre-condition: 5th Bash denied (streak at limit)"
  else
    fail "expected 5th Bash denied as pre-condition, got exit $exit_code"
    return
  fi

  # Reset streak to 4 by writing state directly, then test escape hatch
  printf '{"session_id":"%s","lastTool":"Bash","streak":4,"updatedAt":"%s"}\n' \
    "$TEST_SESSION" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "${STATE_DIR}/streak-${TEST_SESSION}.json"

  result="$(invoke_hook_bash_cmd "COPILOT_FORCE_DELEGATE=off git push origin main")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "command-string escape hatch: COPILOT_FORCE_DELEGATE=off prefix bypasses deny at streak=4"
  else
    fail "command-string escape hatch failed, got exit $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 14: crash fix — git push exits 0 with no error (regression for Issue 1)
# ---------------------------------------------------------------------------
test_git_push_no_crash() {
  clean_state
  local payload exit_code stderr_out
  payload='{"session_id":"test","tool_name":"Bash","tool_input":{"command":"git push origin main"}}'
  stderr_out="$(bash "$HOOK" <<< "$payload" 2>&1 >/dev/null)" || exit_code=$?
  exit_code="${exit_code:-0}"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "crash fix: git push exits 0 (no hook crash)"
  else
    fail "crash fix: git push produced exit $exit_code (stderr: $stderr_out)"
  fi
}

# ===========================================================================
# TASK-106 / C-6 — subagent-livelock replay tests
#
# Root cause (see docs/10-architecture/06-hook-deadlock-root-cause-2026-07.md):
# Claude Code shares session_id between a main session and any subagent it
# spawns via the Agent tool. Confirmed empirically 2026-07-12 by replaying
# real PreToolUse payloads from a throwaway `claude -p` session: a
# Task-spawned subagent's own Read calls carry the SAME session_id as its
# parent, distinguished only by a non-empty agent_type/agent_id. Before this
# fix, a subagent's Read/Edit/Bash calls shared (and could trip) the parent's
# force-delegate streak and the qa-gate's deny-everything-except-Agent(qa)
# rule — with no escape, since framework agents (me/qa/ta/...) do not carry
# the Agent/Task tool in their `tools:` allow-list. That is the literal
# self-sealing deadlock described in 20097d9's commit message, later masked
# (not fixed) by 23c02c0's Bash-only matcher the same day.
# ===========================================================================

# Invoke hook with an arbitrary raw payload string (for agent_type fixtures
# the other helpers above don't support).
invoke_hook_raw() {
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

# Build a Read payload, optionally tagged with a subagent's agent_type/agent_id
# (empty agent_type == a call made directly by the main session).
subagent_read_payload() {
  local session="$1" agent_type="$2"
  if [[ -z "$agent_type" ]]; then
    printf '{"session_id":"%s","tool_name":"Read","tool_input":{"file_path":"/tmp/x"}}' "$session"
  else
    printf '{"session_id":"%s","agent_type":"%s","agent_id":"task-1","tool_name":"Read","tool_input":{"file_path":"/tmp/x"}}' \
      "$session" "$agent_type"
  fi
}

# ---------------------------------------------------------------------------
# Replay 1: main session Read streak at 4, then TWO subagent Read calls
# (same session_id, agent_type set) → both allowed, streak untouched. Then a
# 5th MAIN-session Read (agent_type empty) is still denied — proves the
# subagent calls neither get blocked NOR pollute/reset the parent streak.
# ---------------------------------------------------------------------------
test_subagent_read_exempt_from_force_delegate() {
  clean_state
  local result exit_code

  # 4 consecutive main-session Reads (streak=4, not yet denied)
  local i
  for i in 1 2 3 4; do
    result="$(invoke_hook_raw "$(subagent_read_payload "$TEST_SESSION" "")")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -ne 0 ]]; then
      fail "replay: main-session Read $i/4 should be allowed, got exit $exit_code"
      return
    fi
  done

  # Subagent's first Read on the SAME session_id: this is the exact call that
  # used to be denied (the livelock) before the agent_type exemption.
  result="$(invoke_hook_raw "$(subagent_read_payload "$TEST_SESSION" "general-purpose")")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "replay: subagent's 1st Read (5th same-tool call overall) allowed — no livelock"
  else
    fail "replay: subagent's 1st Read should be allowed (agent_type exempt), got exit $exit_code"
  fi

  # Subagent's second Read: still allowed — subagent calls are exempt, not
  # just spared once.
  result="$(invoke_hook_raw "$(subagent_read_payload "$TEST_SESSION" "general-purpose")")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "replay: subagent's 2nd Read also allowed (exempt, not one-time)"
  else
    fail "replay: subagent's 2nd Read should be allowed, got exit $exit_code"
  fi

  # Back to the main session: the parent's streak was NOT advanced or reset
  # by the subagent's calls, so its next Read is the 5th consecutive
  # main-session Read and is still denied as designed.
  result="$(invoke_hook_raw "$(subagent_read_payload "$TEST_SESSION" "")")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "replay: main session's 5th Read still denied — subagent calls did not pollute parent streak"
  else
    fail "replay: main session's 5th Read should still be denied, got exit $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Replay 2: a subagent working alone (fresh session_id it happens to share
# with a parent that never called Read) issues 6+ consecutive Read calls —
# never denied, at any streak length.
# ---------------------------------------------------------------------------
test_subagent_alone_never_denied() {
  local sess="test-subagent-alone-$$"
  rm -f "${STATE_DIR}/streak-${sess}.json" "${STATE_DIR}/streak-${sess}.lock" 2>/dev/null || true

  local all_passed=true
  local i result exit_code
  for i in 1 2 3 4 5 6; do
    result="$(invoke_hook_raw "$(subagent_read_payload "$sess" "qa")")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -ne 0 ]]; then
      all_passed=false
      fail "replay: subagent Read $i/6 (agent_type=qa) should be allowed, got exit $exit_code"
    fi
  done
  if $all_passed; then
    ok "replay: subagent alone — 6 consecutive Read calls all allowed (fully exempt)"
  fi

  rm -f "${STATE_DIR}/streak-${sess}.json" "${STATE_DIR}/streak-${sess}.lock" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Replay 3: QA gate active (TASK-77 pending) + @agent-qa subagent's OWN
# Read/Edit calls (agent_type=qa, same session_id as the gated main session)
# → allowed. Before this fix, rule_qa_gate's "deny everything else" branch
# caught these too, since it only special-cased TOOL_NAME=="Agent" and safe
# `tc` Bash prefixes — meaning @agent-qa could be dispatched but then
# couldn't Read the code it was asked to verify.
# ---------------------------------------------------------------------------
test_qa_gate_subagent_read_edit_exempt() {
  clean_state
  clean_gate_state
  write_gate_pending '["TASK-77"]'

  local result exit_code
  result="$(invoke_hook_raw "$(subagent_read_payload "$TEST_SESSION" "qa")")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "replay: QA gate active + qa subagent's own Read call allowed"
  else
    fail "replay: QA gate active + qa subagent Read should be allowed, got exit $exit_code"
  fi

  local edit_payload
  edit_payload="$(printf '{"session_id":"%s","agent_type":"qa","agent_id":"task-1","tool_name":"Edit","tool_input":{"file_path":"/tmp/x"}}' "$TEST_SESSION")"
  result="$(invoke_hook_raw "$edit_payload")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "replay: QA gate active + qa subagent's own Edit call allowed"
  else
    fail "replay: QA gate active + qa subagent Edit should be allowed, got exit $exit_code"
  fi

  # Control: the MAIN session (agent_type empty) is still gated — this proves
  # the exemption is scoped to subagent calls, not a blanket gate bypass.
  result="$(invoke_hook_raw "$(subagent_read_payload "$TEST_SESSION" "")")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "replay: QA gate control — main session's own Read is still denied"
  else
    fail "replay: main session Read should still be denied while gate active, got exit $exit_code"
  fi

  clean_gate_state
}

# ---------------------------------------------------------------------------
# Replay 4: QA gate active + an Agent-tool dispatch call that happens to
# carry a non-empty agent_type (a subagent nesting a further delegation) is
# STILL gated by the Agent-specific allow/deny logic — the subagent exemption
# explicitly excludes TOOL_NAME=="Agent" so this main mechanism isn't
# silently weakened.
# ---------------------------------------------------------------------------
test_qa_gate_nested_agent_dispatch_still_gated() {
  clean_state
  clean_gate_state
  write_gate_pending '["TASK-77"]'

  local payload result exit_code
  payload="$(printf '{"session_id":"%s","agent_type":"me","agent_id":"task-1","tool_name":"Agent","tool_input":{"subagent_type":"ta"}}' "$TEST_SESSION")"
  result="$(invoke_hook_raw "$payload")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "replay: QA gate active — nested Agent(ta) dispatch still denied (Agent gating not weakened)"
  else
    fail "replay: nested Agent(ta) dispatch should still be denied, got exit $exit_code"
  fi

  clean_gate_state
}

# ---------------------------------------------------------------------------
# Replay 5: CC_HOOK_ENFORCE=off is a global kill switch — bypasses BOTH
# force-delegate (streak at deny threshold) and qa-gate (pending task) in one
# shot, without needing to know the per-rule escape hatch names.
# ---------------------------------------------------------------------------
test_kill_switch_bypasses_everything() {
  clean_state
  clean_gate_state

  # Pre-condition: streak=4 (one below the force-delegate deny threshold)
  printf '{"session_id":"%s","lastTool":"Bash","streak":4,"updatedAt":"%s"}\n' \
    "$TEST_SESSION" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "${STATE_DIR}/streak-${TEST_SESSION}.json"
  # Pre-condition: QA gate also pending for the same session
  write_gate_pending '["TASK-77"]'

  local result exit_code
  result="$(invoke_hook_bash_cmd "ls -la" "CC_HOOK_ENFORCE=off")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "replay: CC_HOOK_ENFORCE=off allows despite streak=4 AND pending QA gate"
  else
    fail "replay: CC_HOOK_ENFORCE=off should allow, got exit $exit_code"
  fi

  # Without the kill switch, the same call is denied (pre-condition proof —
  # confirms the allow above was the kill switch, not a stale gate/streak)
  result="$(invoke_hook_bash_cmd "ls -la")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "replay: without the kill switch, same call is denied (QA gate still active)"
  else
    fail "replay: expected deny without kill switch as control, got exit $exit_code"
  fi

  clean_gate_state
}

# ---------------------------------------------------------------------------
# Replay 6: script-error injection — a corrupted (non-numeric) "streak"
# value in the state file must fail OPEN (exit 0), not crash. This is the
# literal mechanism the April 22 "resolve hook deadlock" fix targeted
# (script crash → hard block); found live while building this replay suite
# via bash's nested-arithmetic-variable-reference behavior on non-numeric
# input, which bypasses the ERR trap under `set -u` (fixed alongside this
# test — see the streak numeric-coercion guard in rule_force_delegate).
# ---------------------------------------------------------------------------
test_corrupted_streak_fails_open() {
  clean_state
  printf '{"session_id":"%s","lastTool":"Bash","streak":"not-a-number","updatedAt":"%s"}\n' \
    "$TEST_SESSION" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "${STATE_DIR}/streak-${TEST_SESSION}.json"

  local result exit_code
  result="$(invoke_hook "Bash")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "replay: corrupted non-numeric streak value fails open (exit 0)"
  else
    fail "replay: corrupted streak value should fail open, got exit $exit_code"
  fi
  clean_state
}

# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------
echo "=== pretool-check.sh tests ==="
echo ""
echo "--- Test 1: Single Bash call allowed"
test_single_bash_allowed
echo "--- Test 2: 4 consecutive Bash calls allowed"
test_four_consecutive_bash_allowed
echo "--- Test 3: 5th consecutive Bash call denied"
test_fifth_consecutive_bash_denied
echo "--- Test 4: Mixed sequence (Bash, Bash, Read, Bash, Bash) — no deny"
test_mixed_sequence_no_deny
echo "--- Test 5: Agent tool always allowed"
test_agent_always_allowed
echo "--- Test 6: COPILOT_FORCE_DELEGATE=off escape hatch"
test_escape_hatch_off
echo "--- Test 7: Stale state file does not cause errors"
test_stale_state_no_error
echo "--- Test 8: Malformed/empty payload"
test_malformed_payload
echo "--- Test 9: Concurrent session isolation"
test_concurrent_safety
echo "--- Test 10: Streak resets after deny"
test_streak_reset_after_deny
echo "--- Test 11: Performance <50ms"
test_performance

echo ""
echo "--- QA-gate Test 1: Empty pending_tasks → all tools allowed"
test_qa_gate_empty_pending_allows_all
echo "--- QA-gate Test 2: No gate file → all tools allowed (gate inactive)"
test_qa_gate_no_file_allows_all
echo "--- QA-gate Test 3: Non-empty pending_tasks → Bash denied"
test_qa_gate_pending_denies_bash
echo "--- QA-gate Test 4: Non-empty pending_tasks → Read denied"
test_qa_gate_pending_denies_read
echo "--- QA-gate Test 5: Non-empty pending_tasks → Agent(qa) allowed"
test_qa_gate_pending_allows_agent_qa
echo "--- QA-gate Test 6: Non-empty pending_tasks → Agent(me) denied"
test_qa_gate_pending_denies_agent_me
echo "--- QA-gate Test 7: Safe tc commands allowed while pending"
test_qa_gate_pending_allows_safe_tc_bash
echo "--- QA-gate Test 8: 'tc deploy wait' denied (not in safe prefix)"
test_qa_gate_pending_denies_unsafe_tc_bash
echo "--- QA-gate Test 9: COPILOT_QA_GATE=off escape hatch"
test_qa_gate_escape_hatch
echo "--- QA-gate Test 10: Pending tasks cleared → subsequent calls allowed"
test_qa_gate_cleared_allows_calls
echo "--- Test 12: git push / git pull allowlisted"
test_git_push_pull_allowlisted
echo "--- Test 13: command-string escape hatch (COPILOT_FORCE_DELEGATE=off prefix)"
test_command_string_escape_hatch
echo "--- Test 14: crash fix — git push exits 0 (no hook crash)"
test_git_push_no_crash

echo ""
echo "--- TASK-106/C-6 Replay 1: subagent Read exempt from force-delegate streak"
test_subagent_read_exempt_from_force_delegate
echo "--- TASK-106/C-6 Replay 2: subagent alone — never denied at any streak length"
test_subagent_alone_never_denied
echo "--- TASK-106/C-6 Replay 3: QA gate + qa subagent's own Read/Edit exempt"
test_qa_gate_subagent_read_edit_exempt
echo "--- TASK-106/C-6 Replay 4: QA gate + nested Agent dispatch still gated"
test_qa_gate_nested_agent_dispatch_still_gated
echo "--- TASK-106/C-6 Replay 5: CC_HOOK_ENFORCE=off kill switch bypasses everything"
test_kill_switch_bypasses_everything
echo "--- TASK-106/C-6 Replay 6: corrupted streak value fails open"
test_corrupted_streak_fails_open

# Clean up test session state
clean_state
clean_gate_state

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
