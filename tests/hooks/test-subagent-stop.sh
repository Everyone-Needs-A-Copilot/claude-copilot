#!/usr/bin/env bash
# test-subagent-stop.sh — Tests for .claude/hooks/subagent-stop.sh
#
# Run: bash tests/hooks/test-subagent-stop.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
HOOK="$PROJECT_ROOT/.claude/hooks/subagent-stop.sh"
# Guardrail D/E (TASK-129-followup) live in pretool-check.sh's rule_qa_gate()
# deny path, not in subagent-stop.sh — these tests invoke it directly,
# scoped to the same isolated COPILOT_HOOK_STATE_DIR set up below, so no
# real .claude/hooks/state/ file is ever touched.
PRETOOL_HOOK="$PROJECT_ROOT/.claude/hooks/pretool-check.sh"
JQ="/usr/bin/jq"

TEST_SESSION="test-subagent-$$"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/subagent-stop.XXXXXX")"
TEST_PROJECT="${TEST_ROOT}/project"
STATE_DIR="${TEST_ROOT}/state"
GATE_FILE="${STATE_DIR}/qa-gate.json"

export CLAUDE_PROJECT_DIR="$TEST_PROJECT"
export COPILOT_HOOK_STATE_DIR="$STATE_DIR"

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
  # Also reset pretool-check.sh's force-delegate streak state for
  # TEST_SESSION. The guardrail D/E tests below invoke pretool-check.sh
  # (not just subagent-stop.sh) multiple times using the SAME shared
  # TEST_SESSION as every other test in this file — without this, a Bash
  # tool_input streak built up across earlier tests would trip
  # rule_force_delegate's own 5-consecutive-same-tool deny and mask the
  # qa-gate result the D/E tests are actually asserting on.
  rm -f "${STATE_DIR}/streak-${TEST_SESSION}.json" "${STATE_DIR}/streak-${TEST_SESSION}.lock" 2>/dev/null || true
}

cleanup_all() {
  case "$TEST_ROOT" in
    "${TMPDIR:-/tmp}"/subagent-stop.*) rm -rf -- "$TEST_ROOT" ;;
    *) echo "Refusing to remove unexpected fixture root: $TEST_ROOT" >&2 ;;
  esac
}

trap cleanup_all EXIT

mkdir -p "$TEST_PROJECT" "$STATE_DIR"
tc init --path "$TEST_PROJECT" --json >/dev/null
for task_number in $(seq 1 20); do
  (cd "$TEST_PROJECT" && tc task create --title "Subagent stop fixture ${task_number}" --json) >/dev/null
done

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

# Read armed_at[task_id] for TEST_SESSION
read_armed_at() {
  local task_id="$1"
  if [[ ! -f "$GATE_FILE" ]]; then
    echo ""
    return
  fi
  "$JQ" -r --arg sid "$TEST_SESSION" --arg tid "$task_id" \
    '.[$sid].armed_at[$tid] // ""' "$GATE_FILE" 2>/dev/null || echo ""
}

# Read last_parse[task_id] for TEST_SESSION
read_last_parse() {
  local task_id="$1"
  if [[ ! -f "$GATE_FILE" ]]; then
    echo ""
    return
  fi
  "$JQ" -r --arg sid "$TEST_SESSION" --arg tid "$task_id" \
    '.[$sid].last_parse[$tid] // ""' "$GATE_FILE" 2>/dev/null || echo ""
}

# Directly stamp a session's pending_tasks/armed_at in GATE_FILE, bypassing
# the hook. Used by the guardrail-D tests below to seed an "already old"
# arming timestamp without waiting real hours.
seed_pending_with_armed_at() {
  local task_id="$1"
  local armed_at_iso="$2"
  local prior='{}'
  [[ -s "$GATE_FILE" ]] && prior="$(cat "$GATE_FILE")"
  "$JQ" -n --arg sid "$TEST_SESSION" --arg tid "$task_id" --arg ts "$armed_at_iso" --argjson prior "$prior" '
    $prior
    | .[$sid] = ((.[$sid] // {"pending_tasks":[],"retries":{},"armed_at":{},"last_parse":{},"history":[],"lastSeen":""})
        | .pending_tasks = ((.pending_tasks // []) + [$tid] | unique)
        | .armed_at = ((.armed_at // {}) + {($tid): $ts})
        | .lastSeen = $ts)
  ' > "${GATE_FILE}.tmp" && mv "${GATE_FILE}.tmp" "$GATE_FILE"
}

# ISO timestamp N hours in the past, portable (macOS BSD date / GNU date).
hours_ago_iso() {
  local hours="$1"
  if [[ "$(uname)" == "Darwin" ]]; then
    date -u -v-"${hours}"H +%Y-%m-%dT%H:%M:%SZ
  else
    date -u -d "${hours} hours ago" +%Y-%m-%dT%H:%M:%SZ
  fi
}

# Invoke pretool-check.sh (guardrails D/E live in its rule_qa_gate deny
# path). Scoped to the same COPILOT_HOOK_STATE_DIR exported above.
invoke_pretool_hook() {
  local payload="$1"
  local extra_env="${2:-}"
  local exit_code=0
  local output
  if [[ -n "$extra_env" ]]; then
    output="$(eval "env $extra_env bash '$PRETOOL_HOOK'" <<< "$payload" 2>/dev/null)" || exit_code=$?
  else
    output="$(bash "$PRETOOL_HOOK" <<< "$payload" 2>/dev/null)" || exit_code=$?
  fi
  printf '%d|%s' "$exit_code" "$output"
}

# A Bash tool_input payload for pretool-check.sh, using a command that is
# NOT on the QA-gate safe-prefix allowlist (so a fresh/blocking gate denies
# it, and an advisory/stale gate allows it through).
make_bash_tool_payload() {
  local cmd="$1"
  printf '{"session_id":"%s","tool_name":"Bash","tool_input":{"command":"%s"}}\n' "$TEST_SESSION" "$cmd"
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
  payload_qa="$(make_payload "qa" "Task: TASK-5 | WP: WP-20\nVERDICT: APPROVED\nARTIFACT: test-run|pytest tests/test_foo.py exit=0 5 passed")"
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
  payload_qa="$(make_payload "qa" "Task: TASK-7\nVERDICT: APPROVED-WITH-MINOR-FIXES\nARTIFACT: test-run|pytest tests/test_foo.py exit=0 5 passed")"
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
  payload_qa="$(make_payload "qa" "Task: TASK-8 | WP: WP-22\nAll tests pass.\nARTIFACT: test-run|pytest tests/test_foo.py exit=0 5 passed\n<promise>COMPLETE</promise>")"
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
  p3="$(make_payload "qa" "Task: TASK-3\nVERDICT: APPROVED\nARTIFACT: test-run|pytest tests/test_foo.py exit=0 5 passed")"
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
# Test 13: extract_task_id tolerates markdown decoration around the
# structured "Task:" header (bold label, list marker, ATX heading, table
# row) — the over-strict extraction defect.
# ---------------------------------------------------------------------------
test_extract_task_id_markdown_variants() {
  local variants=(
    "TASK-8|**Task:** TASK-8\nSummary: implementation complete."
    "TASK-9|- Task: TASK-9\nSummary: implementation complete."
    "TASK-10|### Task: TASK-10\nSummary: implementation complete."
    "TASK-11|| Task: TASK-11 | WP: WP-1 |"
  )

  local variant task_id msg
  for variant in "${variants[@]}"; do
    task_id="${variant%%|*}"
    msg="${variant#*|}"
    clean_gate
    local payload
    payload="$(make_payload "me" "$msg")"
    bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true

    local pending
    pending="$(read_pending)"
    if printf '%s' "$pending" | "$JQ" -e --arg t "$task_id" 'contains([$t])' > /dev/null 2>&1; then
      ok "extract_task_id decorated: ${task_id} extracted from markdown-decorated header"
    else
      fail "extract_task_id decorated: expected ${task_id} in pending after decorated header, got: $pending"
    fi
  done
}

# ---------------------------------------------------------------------------
# Test 14: a bare prose mention of TASK-N (no "Task:" label) must NOT arm
# the gate — decoration tolerance must not regress into a bare-ID scan.
# ---------------------------------------------------------------------------
test_extract_task_id_bare_prose_no_match() {
  clean_gate
  local payload
  payload="$(make_payload "me" "This work covers TASK-12 and related fixes; testing performed inline.")"
  bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true

  local pending
  pending="$(read_pending)"
  local pending_count
  pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
  if [[ "$pending_count" -eq 0 ]]; then
    ok "extract_task_id bare prose: TASK-12 mentioned in prose does NOT arm gate"
  else
    fail "extract_task_id bare prose: gate should not arm on prose mention, got pending: $pending"
  fi
}

# ---------------------------------------------------------------------------
# Test 15: qa failure with an unparseable Task: header, exactly one pending
# task → failure is attributed to that task, retries accrue normally, and
# the 3-strikes auto-unblock still fires (the gate-wedge defect).
# ---------------------------------------------------------------------------
test_qa_unparseable_failure_single_pending_attributes_and_unblocks() {
  clean_gate

  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-13 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  # QA fails without a structured "Task:" header at all — simulates the
  # real-world case that previously wedged the gate permanently.
  local i advisory_output=""
  for i in 1 2 3; do
    local payload_qa
    payload_qa="$(make_payload "qa" "QA review complete.\nVERDICT: REJECTED - artifact missing")"
    local result output
    result="$(invoke_hook "$payload_qa")"
    output="$(get_output "$result")"
    if [[ -n "$output" ]]; then
      advisory_output="$output"
    fi
  done

  local retries
  retries="$(read_retries "TASK-13")"
  if [[ "$retries" -eq 3 ]]; then
    ok "qa unparseable failure, single pending: retries attributed to sole pending TASK-13, reached 3"
  else
    fail "qa unparseable failure, single pending: expected retries=3 for TASK-13, got $retries"
  fi

  local pending
  pending="$(read_pending)"
  local pending_count
  pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
  if [[ "$pending_count" -eq 0 ]]; then
    ok "qa unparseable failure, single pending: gate auto-unblocked on 3rd unattributed failure"
  else
    fail "qa unparseable failure, single pending: expected auto-unblock, pending: $pending"
  fi

  if [[ -n "$advisory_output" ]] && printf '%s' "$advisory_output" | "$JQ" -e '.systemMessage | length > 0' > /dev/null 2>&1; then
    ok "qa unparseable failure, single pending: advisory systemMessage emitted on 3rd failure"
  else
    fail "qa unparseable failure, single pending: expected advisory systemMessage, got: $advisory_output"
  fi

  if [[ -f "${STATE_DIR}/qa-gate.log" ]] && grep -q "attributed to sole pending task TASK-13" "${STATE_DIR}/qa-gate.log" 2>/dev/null; then
    ok "qa unparseable failure, single pending: WARN log names the attributed task"
  else
    fail "qa unparseable failure, single pending: expected attribution WARN naming TASK-13 in qa-gate.log"
  fi
}

# ---------------------------------------------------------------------------
# Test 16: qa failure with an unparseable Task: header, 2+ pending tasks →
# attribution would be a guess, so it stays a no-op (still logged).
# ---------------------------------------------------------------------------
test_qa_unparseable_failure_multiple_pending_noop() {
  clean_gate

  local payload_me_a payload_me_b
  payload_me_a="$(make_payload "me" "Task: TASK-14 completed.")"
  bash "$HOOK" <<< "$payload_me_a" > /dev/null 2>&1 || true
  payload_me_b="$(make_payload "me" "Task: TASK-15 completed.")"
  bash "$HOOK" <<< "$payload_me_b" > /dev/null 2>&1 || true

  local pending_before
  pending_before="$(read_pending)"

  local payload_qa
  payload_qa="$(make_payload "qa" "QA review complete.\nVERDICT: REJECTED - artifact missing")"
  local result exit_code
  result="$(invoke_hook "$payload_qa")"
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "qa unparseable failure, multiple pending: hook exits 0"
  else
    fail "qa unparseable failure, multiple pending: expected exit 0, got $exit_code"
  fi

  local pending_after
  pending_after="$(read_pending)"
  if [[ "$pending_after" == "$pending_before" ]]; then
    ok "qa unparseable failure, multiple pending: pending_tasks unchanged (no guess)"
  else
    fail "qa unparseable failure, multiple pending: expected no change, before=$pending_before after=$pending_after"
  fi

  local retries14 retries15
  retries14="$(read_retries "TASK-14")"
  retries15="$(read_retries "TASK-15")"
  if [[ "$retries14" -eq 0 && "$retries15" -eq 0 ]]; then
    ok "qa unparseable failure, multiple pending: no retry counter incremented for either task"
  else
    fail "qa unparseable failure, multiple pending: expected zero retries, got TASK-14=$retries14 TASK-15=$retries15"
  fi

  if [[ -f "${STATE_DIR}/qa-gate.log" ]] && grep -q "cannot attribute unambiguously" "${STATE_DIR}/qa-gate.log" 2>/dev/null; then
    ok "qa unparseable failure, multiple pending: WARN log records ambiguous-attribution no-op"
  else
    fail "qa unparseable failure, multiple pending: expected ambiguous-attribution WARN in qa-gate.log"
  fi
}

# ---------------------------------------------------------------------------
# TASK-129-followup guardrail tests (A-E)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Test 17 (guardrail A): a "Task:" line that is quoted (blockquote), fenced
# (code block), or indented as a code block is NOT extracted — it must not
# arm the gate, even though it carries a real, otherwise-well-formed header.
# ---------------------------------------------------------------------------
test_extract_task_id_quoted_variants_no_match() {
  local variants=(
    "blockquote|> Task: TASK-30\nSummary: done."
    "fenced|\`\`\`\nTask: TASK-31\n\`\`\`\nSummary: done."
    "4-space-indented|    Task: TASK-32\nSummary: done."
  )

  local variant label msg
  for variant in "${variants[@]}"; do
    label="${variant%%|*}"
    msg="${variant#*|}"
    clean_gate
    local payload
    payload="$(make_payload "me" "$msg")"
    bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true

    local pending
    pending="$(read_pending)"
    local pending_count
    pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
    if [[ "$pending_count" -eq 0 ]]; then
      ok "guardrail A (${label}): quoted/coded Task: line does NOT arm the gate"
    else
      fail "guardrail A (${label}): should not arm gate, got pending: $pending"
    fi
  done
}

# ---------------------------------------------------------------------------
# Test 18 (guardrail C, arm path): 2+ distinct header-shaped "Task:" lines
# in an @agent-me completion must NOT arm the gate for either — ambiguity
# fails closed on the arm path too, not just the qa path.
# ---------------------------------------------------------------------------
test_me_ambiguous_headers_not_armed() {
  clean_gate
  local payload
  payload="$(make_payload "me" "* Task: TASK-2\n* Task: TASK-3\nSummary: done.")"
  bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true

  local pending
  pending="$(read_pending)"
  local pending_count
  pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
  if [[ "$pending_count" -eq 0 ]]; then
    ok "guardrail C (me): 2+ distinct headers do NOT arm the gate"
  else
    fail "guardrail C (me): expected no arm, got pending: $pending"
  fi
}

# ---------------------------------------------------------------------------
# Test 19 (guardrail B): QA's header parses cleanly to a REAL task id, but
# that id is not pending for this session. The cross-check must refuse to
# mutate TASK-999's retries and fall back to the sole pending task instead.
# ---------------------------------------------------------------------------
test_qa_cross_check_not_pending_refuses_and_falls_back() {
  clean_gate
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-16 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  local payload_qa
  payload_qa="$(make_payload "qa" "Task: TASK-999\nVERDICT: REJECTED - wrong task referenced")"
  bash "$HOOK" <<< "$payload_qa" > /dev/null 2>&1 || true

  local retries_999 retries_16
  retries_999="$(read_retries "TASK-999")"
  retries_16="$(read_retries "TASK-16")"

  if [[ "$retries_999" -eq 0 ]]; then
    ok "guardrail B: non-pending extracted id TASK-999 NOT mutated (retries stayed 0)"
  else
    fail "guardrail B: TASK-999 retries should stay 0, got $retries_999"
  fi

  if [[ "$retries_16" -eq 1 ]]; then
    ok "guardrail B: refused id falls back to sole pending task TASK-16 (retries=1)"
  else
    fail "guardrail B: expected TASK-16 retries=1 via single-pending fallback, got $retries_16"
  fi

  if [[ -f "${STATE_DIR}/qa-gate.log" ]] && grep -q "is NOT in pending_tasks for this session" "${STATE_DIR}/qa-gate.log" 2>/dev/null; then
    ok "guardrail B: WARN logged naming the extracted id and pending set"
  else
    fail "guardrail B: expected cross-check WARN in qa-gate.log"
  fi
}

# ---------------------------------------------------------------------------
# Test 20 (guardrail C, qa path): 2+ distinct header-shaped ids in a QA
# completion → no action (no clear, no retry mutation for either), WARN
# logged listing all ids found.
# ---------------------------------------------------------------------------
test_qa_ambiguous_headers_no_op() {
  clean_gate
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-17 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  local pending_before
  pending_before="$(read_pending)"

  local payload_qa
  payload_qa="$(make_payload "qa" "- Task: TASK-17\n- Task: TASK-18\nVERDICT: REJECTED")"
  local result exit_code
  result="$(invoke_hook "$payload_qa")"
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "guardrail C (qa): ambiguous headers — hook exits 0"
  else
    fail "guardrail C (qa): ambiguous headers — expected exit 0, got $exit_code"
  fi

  local pending_after
  pending_after="$(read_pending)"
  if [[ "$pending_after" == "$pending_before" ]]; then
    ok "guardrail C (qa): ambiguous headers — pending_tasks unchanged (no guess)"
  else
    fail "guardrail C (qa): expected no change, before=$pending_before after=$pending_after"
  fi

  local retries17 retries18
  retries17="$(read_retries "TASK-17")"
  retries18="$(read_retries "TASK-18")"
  if [[ "$retries17" -eq 0 && "$retries18" -eq 0 ]]; then
    ok "guardrail C (qa): ambiguous headers — neither task's retries mutated"
  else
    fail "guardrail C (qa): expected zero retries, got TASK-17=$retries17 TASK-18=$retries18"
  fi

  if [[ -f "${STATE_DIR}/qa-gate.log" ]] && grep -q "2+ distinct Task: header-shaped lines" "${STATE_DIR}/qa-gate.log" 2>/dev/null; then
    ok "guardrail C (qa): WARN logged listing all ids found"
  else
    fail "guardrail C (qa): expected ambiguity WARN in qa-gate.log"
  fi
}

# ---------------------------------------------------------------------------
# Test 21 (guardrail D): a fresh pending task (armed 1h ago) still denies;
# a pending task older than the default 24h threshold drops to advisory
# and no longer denies (read-side release — pretool-check.sh's rule_qa_gate).
# ---------------------------------------------------------------------------
test_staleness_fresh_denies() {
  clean_gate
  seed_pending_with_armed_at "TASK-40" "$(hours_ago_iso 1)"

  local payload result exit_code
  payload="$(make_bash_tool_payload "echo hi")"
  result="$(invoke_pretool_hook "$payload")"
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 2 ]]; then
    ok "guardrail D: fresh pending task (1h old) still denies"
  else
    fail "guardrail D: expected deny (exit 2) for fresh task, got $exit_code"
  fi
}

test_staleness_old_goes_advisory() {
  clean_gate
  seed_pending_with_armed_at "TASK-41" "$(hours_ago_iso 30)"

  local payload result exit_code
  payload="$(make_bash_tool_payload "echo hi")"
  result="$(invoke_pretool_hook "$payload")"
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "guardrail D: pending task older than default 24h threshold goes advisory (allows)"
  else
    fail "guardrail D: expected allow (exit 0) for stale task, got $exit_code"
  fi

  if [[ -f "${STATE_DIR}/qa-gate.log" ]] && grep -q "qa-gate advisory (age)" "${STATE_DIR}/qa-gate.log" 2>/dev/null; then
    ok "guardrail D: advisory transition logged"
  else
    fail "guardrail D: expected advisory WARN in qa-gate.log"
  fi
}

# ---------------------------------------------------------------------------
# Test 22 (guardrail D): COPILOT_QA_GATE_MAX_AGE_HOURS override is respected
# in both directions on the same 2h-old task.
# ---------------------------------------------------------------------------
test_staleness_override_env_respected() {
  clean_gate
  seed_pending_with_armed_at "TASK-42" "$(hours_ago_iso 2)"

  local payload
  payload="$(make_bash_tool_payload "echo hi")"

  local result exit_code
  result="$(invoke_pretool_hook "$payload")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "guardrail D override: 2h-old task denies under default 24h threshold"
  else
    fail "guardrail D override: expected deny under default threshold, got $exit_code"
  fi

  result="$(invoke_pretool_hook "$payload" "COPILOT_QA_GATE_MAX_AGE_HOURS=1")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "guardrail D override: COPILOT_QA_GATE_MAX_AGE_HOURS=1 makes the 2h-old task advisory"
  else
    fail "guardrail D override: expected allow with 1h override, got $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 23 (guardrail D): an old-shape qa-gate.json (bare pending_tasks
# strings, no armed_at map at all) must fall back to lastSeen and must not
# crash the hook.
# ---------------------------------------------------------------------------
test_staleness_old_shape_no_crash() {
  clean_gate
  "$JQ" -n --arg sid "$TEST_SESSION" --arg ts "$(hours_ago_iso 30)" \
    '{ ($sid): { pending_tasks: ["TASK-43"], retries: {}, history: [], lastSeen: $ts } }' \
    > "$GATE_FILE"

  local payload result exit_code
  payload="$(make_bash_tool_payload "echo hi")"
  result="$(invoke_pretool_hook "$payload")"
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "guardrail D: old-shape state (no armed_at) falls back to lastSeen, goes advisory, no crash"
  else
    fail "guardrail D: old-shape state should go advisory via lastSeen fallback, got $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 24 (guardrail E): the deny message includes the retry count and the
# last-parse reason recorded for the blocking task.
# ---------------------------------------------------------------------------
test_diagnostic_deny_message_has_retries_and_last_parse() {
  clean_gate
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-19 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  local payload_qa
  payload_qa="$(make_payload "qa" "QA review complete.\nVERDICT: REJECTED - artifact missing")"
  bash "$HOOK" <<< "$payload_qa" > /dev/null 2>&1 || true

  local retries
  retries="$(read_retries "TASK-19")"
  if [[ "$retries" -eq 1 ]]; then
    ok "guardrail E precondition: TASK-19 retries=1 after one QA failure"
  else
    fail "guardrail E precondition: expected retries=1, got $retries"
  fi

  local payload result reason
  payload="$(make_bash_tool_payload "echo hi")"
  result="$(invoke_pretool_hook "$payload")"
  reason="$(get_output "$result" | "$JQ" -r '.reason // ""' 2>/dev/null)"

  if printf '%s' "$reason" | grep -q "retries 1/3"; then
    ok "guardrail E: deny message contains the retry count (retries 1/3)"
  else
    fail "guardrail E: expected 'retries 1/3' in deny reason, got: $reason"
  fi

  if printf '%s' "$reason" | grep -q "no Task: header found"; then
    ok "guardrail E: deny message contains the last-parse reason"
  else
    fail "guardrail E: expected last-parse reason in deny reason, got: $reason"
  fi
}

# ---------------------------------------------------------------------------
# Test 25 (TASK-129-followup defect 1): fence tracking must key off the
# delimiter CHARACTER (and run length), not just "a fence delimiter
# occurred" — a backtick fence must not be closed by a tilde run and vice
# versa, and an unclosed fence at EOF must swallow everything after it.
# Every "Task:" line below is a real, existing fixture task (TASK-1); if
# the fence tracker mis-closes and lets extraction see it, the gate WILL
# arm (task_id_valid_in_project succeeds), so these are live regression
# checks, not just "no crash" checks.
# ---------------------------------------------------------------------------
test_fence_delimiter_type_tracking_no_match() {
  local variants=(
    "mismatched backtick-open/tilde-close (QA live repro)|\`\`\`\nsome code\n~~~\nTask: TASK-1\n\`\`\`"
    "tilde-opened fence containing a backtick run|~~~\nsome code\n\`\`\`\nTask: TASK-1\n~~~"
    "backtick fence opened with a language tag|\`\`\`bash\necho hi\nTask: TASK-1\n\`\`\`"
    "unclosed fence at EOF swallows the rest of the message|\`\`\`\nTask: TASK-1\nTask: TASK-2\nSummary: done."
  )

  local variant label msg
  for variant in "${variants[@]}"; do
    label="${variant%%|*}"
    msg="${variant#*|}"
    clean_gate
    local payload
    payload="$(make_payload "me" "$msg")"
    bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true

    local pending
    pending="$(read_pending)"
    local pending_count
    pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
    if [[ "$pending_count" -eq 0 ]]; then
      ok "fence tracking (${label}): does NOT arm the gate"
    else
      fail "fence tracking (${label}): should not arm gate, got pending: $pending"
    fi
  done
}

# ---------------------------------------------------------------------------
# Test 26 (TASK-129-followup defect 1, must-not-regress): a closing run at
# least as long as the opening run DOES close a same-character fence, and a
# "Task:" line after a properly closed fence still extracts and arms.
# ---------------------------------------------------------------------------
test_fence_delimiter_type_tracking_closes_and_extracts() {
  clean_gate
  local payload
  # Opened with 3 backticks, closed with 4 ("longer closing run"). The
  # in-fence "Task: TASK-1" must stay swallowed; the real header after the
  # close must still extract and arm.
  payload="$(make_payload "me" "\`\`\`\nTask: TASK-1\n\`\`\`\`\nTask: TASK-2\nSummary: done.")"
  bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true

  local pending
  pending="$(read_pending)"
  if printf '%s' "$pending" | "$JQ" -e '. == ["TASK-2"]' > /dev/null 2>&1; then
    ok "fence tracking (longer closing run): closes fence, in-fence TASK-1 swallowed, TASK-2 after it extracted"
  else
    fail "fence tracking (longer closing run): expected pending == [\"TASK-2\"], got: $pending"
  fi

  clean_gate
  # Regression guard: a matching-length closing fence still closes, and a
  # Task: line AFTER it (outside any fence) still extracts normally.
  payload="$(make_payload "me" "\`\`\`\ncode here\n\`\`\`\nTask: TASK-2\nSummary: done.")"
  bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true

  pending="$(read_pending)"
  if printf '%s' "$pending" | "$JQ" -e '. == ["TASK-2"]' > /dev/null 2>&1; then
    ok "fence tracking (regression): Task: line after a properly closed fence still extracts"
  else
    fail "fence tracking (regression): expected pending == [\"TASK-2\"], got: $pending"
  fi
}

# ---------------------------------------------------------------------------
# Test 27 (TASK-129-followup defect 2): an unbounded COPILOT_QA_GATE_MAX_AGE_HOURS
# override must not overflow 64-bit arithmetic into a negative threshold —
# a negative threshold would make `age -ge threshold` true for every task,
# silently releasing the ENTIRE QA gate machine-wide. Each variant seeds a
# task armed 0 seconds ago (as fresh as it gets) and asserts the gate STILL
# DENIES under the given override — a clamp that failed would instead make
# even a brand-new task advisory (exit 0), exactly the failure QA reproduced.
# ---------------------------------------------------------------------------
test_max_age_hours_overflow_clamps_stays_denied() {
  local variants=(
    "20-digit overflow (QA live repro)|99999999999999999999"
    "int64 max (19 digits)|9223372036854775807"
    "just above the 8760h ceiling|8761"
  )

  local variant label value
  for variant in "${variants[@]}"; do
    label="${variant%%|*}"
    value="${variant#*|}"
    clean_gate
    seed_pending_with_armed_at "TASK-50" "$(hours_ago_iso 0)"

    local payload result exit_code
    payload="$(make_bash_tool_payload "echo hi")"
    result="$(invoke_pretool_hook "$payload" "COPILOT_QA_GATE_MAX_AGE_HOURS=${value}")"
    exit_code="$(get_exit_code "$result")"

    if [[ "$exit_code" -eq 2 ]]; then
      ok "max-age overflow (${label}): clamps, freshly-armed task still DENIED"
    else
      fail "max-age overflow (${label}): expected deny (exit 2) for fresh task, got $exit_code — gate may have been disabled machine-wide"
    fi

    if [[ -f "${STATE_DIR}/qa-gate.log" ]] && grep -q "clamped to 8760h ceiling" "${STATE_DIR}/qa-gate.log" 2>/dev/null; then
      ok "max-age overflow (${label}): WARN log names the supplied value and the clamped ceiling"
    else
      fail "max-age overflow (${label}): expected clamp WARN naming ceiling 8760h in qa-gate.log"
    fi
  done
}

# ---------------------------------------------------------------------------
# Test 28 (TASK-129-followup defect 2): legitimate override values (well
# under the ceiling) still compute correctly and are not accidentally
# clamped or broken by the overflow guard.
# ---------------------------------------------------------------------------
test_max_age_hours_legitimate_values_still_work() {
  clean_gate
  # 30h-old task: older than the default 24h threshold, but younger than a
  # legitimate 48h override — must still DENY under the larger override.
  seed_pending_with_armed_at "TASK-51" "$(hours_ago_iso 30)"

  local payload result exit_code
  payload="$(make_bash_tool_payload "echo hi")"
  result="$(invoke_pretool_hook "$payload" "COPILOT_QA_GATE_MAX_AGE_HOURS=48")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "max-age legitimate value: 48h override on a 30h-old task still DENIES (48 > 30)"
  else
    fail "max-age legitimate value: expected deny (exit 2) with 48h override on 30h-old task, got $exit_code"
  fi

  if [[ -f "${STATE_DIR}/qa-gate.log" ]] && grep -q "clamped" "${STATE_DIR}/qa-gate.log" 2>/dev/null; then
    fail "max-age legitimate value: 48h should NOT trigger a clamp WARN"
  else
    ok "max-age legitimate value: 48h override does not trigger a clamp WARN"
  fi
}

# ---------------------------------------------------------------------------
# Test 29 (TASK-129-followup defect 2): unset / empty / 0 / negative /
# non-numeric overrides must all still degrade to the 24h default — the
# overflow guard must not change this pre-existing behavior.
# ---------------------------------------------------------------------------
test_max_age_hours_invalid_inputs_degrade_to_default() {
  local variants=(
    "empty string|"
    "zero|0"
    "negative|-5"
    "non-numeric|abc"
  )

  local variant label value extra_env
  for variant in "${variants[@]}"; do
    label="${variant%%|*}"
    value="${variant#*|}"
    clean_gate
    # 30h-old task: older than the 24h default → must go advisory (allow).
    seed_pending_with_armed_at "TASK-52" "$(hours_ago_iso 30)"

    local payload result exit_code
    payload="$(make_bash_tool_payload "echo hi")"
    extra_env="COPILOT_QA_GATE_MAX_AGE_HOURS=${value}"
    result="$(invoke_pretool_hook "$payload" "$extra_env")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -eq 0 ]]; then
      ok "max-age invalid input (${label}): degrades to 24h default, 30h-old task goes advisory"
    else
      fail "max-age invalid input (${label}): expected allow (exit 0, default 24h applies), got $exit_code"
    fi
  done

  # Also confirm the true-unset case (no env var at all) behaves the same.
  clean_gate
  seed_pending_with_armed_at "TASK-52" "$(hours_ago_iso 30)"
  local payload result exit_code
  payload="$(make_bash_tool_payload "echo hi")"
  result="$(invoke_pretool_hook "$payload")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "max-age invalid input (unset): degrades to 24h default, 30h-old task goes advisory"
  else
    fail "max-age invalid input (unset): expected allow (exit 0, default 24h applies), got $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 30 (TASK-129-followup CHANGE 1 — fourth review round): CommonMark
# fence-close indent rule. A same-char, same-length closing run indented 4+
# spaces is literal in-fence content, not a real close, and must NOT expose
# a nested "Task:" line to extraction. QA's exact live repro (4-space
# nested close arming the gate on TASK-1) must not arm; 8 spaces likewise;
# tilde fences behave the same; a 3-space nested close is spec-valid and
# must still close (no regression); and a real Task: header AFTER a
# genuinely closed fence must still extract normally.
# ---------------------------------------------------------------------------
test_fence_close_indent_rule() {
  local variants=(
    "4-space nested close (QA exact repro)|\`\`\`\n    \`\`\`\nTask: TASK-1\n\`\`\`"
    "8-space nested close|\`\`\`\n        \`\`\`\nTask: TASK-1\n\`\`\`"
    "4-space nested close, tilde fence|~~~\n    ~~~\nTask: TASK-1\n~~~"
    "leading-tab nested close|\`\`\`\n\t\`\`\`\nTask: TASK-1\n\`\`\`"
  )

  local variant label msg
  for variant in "${variants[@]}"; do
    label="${variant%%|*}"
    msg="${variant#*|}"
    clean_gate
    local payload
    payload="$(make_payload "me" "$msg")"
    bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true

    local pending pending_count
    pending="$(read_pending)"
    pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
    if [[ "$pending_count" -eq 0 ]]; then
      ok "fence-close indent (${label}): over-indented close does NOT arm the gate"
    else
      fail "fence-close indent (${label}): should not arm gate, got pending: $pending"
    fi
  done

  # Must-not-regress: a 3-space nested close is spec-valid and still closes
  # the fence — QA confirmed this works today; only 4+ is excluded.
  clean_gate
  local payload3
  payload3="$(make_payload "me" "\`\`\`\n   \`\`\`\nTask: TASK-1\nSummary: done.")"
  bash "$HOOK" <<< "$payload3" > /dev/null 2>&1 || true
  local pending3
  pending3="$(read_pending)"
  if printf '%s' "$pending3" | "$JQ" -e '. == ["TASK-1"]' > /dev/null 2>&1; then
    ok "fence-close indent (regression): 3-space nested close still closes fence, real header after it extracts"
  else
    fail "fence-close indent (regression): expected pending == [\"TASK-1\"] after a 3-space nested close, got: $pending3"
  fi

  # A real Task: header after a genuinely (non-indented) closed fence must
  # still extract — the indent rule must not break the ordinary close path.
  clean_gate
  local payload4
  payload4="$(make_payload "me" "\`\`\`\ncode here\n\`\`\`\nTask: TASK-2\nSummary: done.")"
  bash "$HOOK" <<< "$payload4" > /dev/null 2>&1 || true
  local pending4
  pending4="$(read_pending)"
  if printf '%s' "$pending4" | "$JQ" -e '. == ["TASK-2"]' > /dev/null 2>&1; then
    ok "fence-close indent (regression): Task: header after a genuinely closed fence still extracts"
  else
    fail "fence-close indent (regression): expected pending == [\"TASK-2\"] after a genuinely closed fence, got: $pending4"
  fi
}

# ---------------------------------------------------------------------------
# Test 31 (TASK-129-followup CHANGE 2 — structural cross-check on the arm
# path): an extracted id whose tc status is terminal (completed/cancelled)
# must NOT arm the gate and must log a WARN naming why; a legitimate
# completion citing a live (pending/in_progress) task DOES still arm.
# ---------------------------------------------------------------------------
create_task_with_status() {
  local title="$1" status="$2"
  local created id
  created="$(cd "$TEST_PROJECT" && tc task create --title "$title" --json)" || return 1
  id="$(printf '%s' "$created" | "$JQ" -r '.id')" || return 1
  if [[ "$status" != "pending" ]]; then
    (cd "$TEST_PROJECT" && tc task update "$id" --status "$status" --json) >/dev/null || return 1
  fi
  echo "TASK-${id}"
}

test_status_cross_check_terminal_does_not_arm() {
  local variants=("completed" "cancelled")
  local status task_id
  for status in "${variants[@]}"; do
    clean_gate
    task_id="$(create_task_with_status "arm-eligibility fixture (${status})" "$status")"
    if [[ -z "$task_id" ]]; then
      fail "status cross-check (${status}): fixture task creation failed, cannot run test"
      continue
    fi

    local payload
    payload="$(make_payload "me" "Task: ${task_id}\nSummary: done.")"
    bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true

    local pending pending_count
    pending="$(read_pending)"
    pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
    if [[ "$pending_count" -eq 0 ]]; then
      ok "status cross-check (${status}): terminal-status task does NOT arm the gate"
    else
      fail "status cross-check (${status}): should not arm gate, got pending: $pending"
    fi

    if [[ -f "${STATE_DIR}/qa-gate.log" ]] && grep -q "terminal (completed/cancelled)" "${STATE_DIR}/qa-gate.log" 2>/dev/null; then
      ok "status cross-check (${status}): WARN logged explaining the refusal"
    else
      fail "status cross-check (${status}): expected a WARN naming the terminal-status refusal in qa-gate.log"
    fi
  done
}

test_status_cross_check_live_task_arms() {
  clean_gate
  local task_id
  task_id="$(create_task_with_status "arm-eligibility fixture (pending)" "pending")"
  if [[ -z "$task_id" ]]; then
    fail "status cross-check (pending): fixture task creation failed, cannot run test"
    return
  fi

  local payload
  payload="$(make_payload "me" "Task: ${task_id}\nSummary: done.")"
  bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true

  local pending
  pending="$(read_pending)"
  if printf '%s' "$pending" | "$JQ" -e --arg tid "$task_id" '. == [$tid]' > /dev/null 2>&1; then
    ok "status cross-check (pending): a legitimate completion on a live (non-terminal) task DOES arm the gate"
  else
    fail "status cross-check (pending): expected pending == [\"${task_id}\"], got: $pending"
  fi

  clean_gate
  local in_progress_id
  in_progress_id="$(create_task_with_status "arm-eligibility fixture (in_progress)" "in_progress")"
  payload="$(make_payload "me" "Task: ${in_progress_id}\nSummary: done.")"
  bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true
  pending="$(read_pending)"
  if printf '%s' "$pending" | "$JQ" -e --arg tid "$in_progress_id" '. == [$tid]' > /dev/null 2>&1; then
    ok "status cross-check (in_progress): a legitimate completion on an in_progress task DOES arm the gate"
  else
    fail "status cross-check (in_progress): expected pending == [\"${in_progress_id}\"], got: $pending"
  fi
}

test_status_cross_check_ambiguity_fails_closed() {
  # Belt-and-suspenders: guardrail C (ambiguity) still fails closed even
  # when every candidate id individually would have been status-eligible —
  # ambiguity is decided before task_status_arm_eligible is ever reached.
  clean_gate
  local id_a id_b
  id_a="$(create_task_with_status "ambiguity fixture A" "pending")"
  id_b="$(create_task_with_status "ambiguity fixture B" "pending")"
  local payload
  payload="$(make_payload "me" "Task: ${id_a}\nTask: ${id_b}\nSummary: done.")"
  bash "$HOOK" <<< "$payload" > /dev/null 2>&1 || true

  local pending pending_count
  pending="$(read_pending)"
  pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
  if [[ "$pending_count" -eq 0 ]]; then
    ok "status cross-check + ambiguity: two distinct status-eligible ids still fail closed (does not arm)"
  else
    fail "status cross-check + ambiguity: should not arm gate, got pending: $pending"
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
echo "--- Test 13: extract_task_id tolerates markdown-decorated Task: headers"
test_extract_task_id_markdown_variants
echo "--- Test 14: bare prose TASK-N mention does NOT arm the gate"
test_extract_task_id_bare_prose_no_match
echo "--- Test 15: unparseable qa failure, single pending task → attributed, 3-strike unblock works"
test_qa_unparseable_failure_single_pending_attributes_and_unblocks
echo "--- Test 16: unparseable qa failure, multiple pending tasks → no-op, no guess"
test_qa_unparseable_failure_multiple_pending_noop
echo "--- Test 17: guardrail A — quoted/fenced/indented Task: lines do NOT extract"
test_extract_task_id_quoted_variants_no_match
echo "--- Test 18: guardrail C (arm path) — ambiguous headers do not arm the gate"
test_me_ambiguous_headers_not_armed
echo "--- Test 19: guardrail B — extracted id not pending is refused, falls back"
test_qa_cross_check_not_pending_refuses_and_falls_back
echo "--- Test 20: guardrail C (qa path) — ambiguous headers are a no-op"
test_qa_ambiguous_headers_no_op
echo "--- Test 21: guardrail D — fresh pending task denies, stale goes advisory"
test_staleness_fresh_denies
test_staleness_old_goes_advisory
echo "--- Test 22: guardrail D — COPILOT_QA_GATE_MAX_AGE_HOURS override respected"
test_staleness_override_env_respected
echo "--- Test 23: guardrail D — old-shape state (no armed_at) does not crash"
test_staleness_old_shape_no_crash
echo "--- Test 24: guardrail E — deny message includes retries and last-parse reason"
test_diagnostic_deny_message_has_retries_and_last_parse
echo "--- Test 25: fence tracking keys off delimiter type — mismatched/unclosed fences do not extract"
test_fence_delimiter_type_tracking_no_match
echo "--- Test 26: fence tracking — matching/longer closing runs close correctly, post-fence header still extracts"
test_fence_delimiter_type_tracking_closes_and_extracts
echo "--- Test 27: max-age override overflow clamps to ceiling, gate stays DENIED"
test_max_age_hours_overflow_clamps_stays_denied
echo "--- Test 28: max-age override legitimate values still work"
test_max_age_hours_legitimate_values_still_work
echo "--- Test 29: max-age override invalid inputs degrade to 24h default"
test_max_age_hours_invalid_inputs_degrade_to_default
echo "--- Test 30: CHANGE 1 — CommonMark fence-close indent rule (4+ space nested close does not arm)"
test_fence_close_indent_rule
echo "--- Test 31a: CHANGE 2 — terminal-status task (completed/cancelled) does not arm"
test_status_cross_check_terminal_does_not_arm
echo "--- Test 31b: CHANGE 2 — live (pending/in_progress) task still arms"
test_status_cross_check_live_task_arms
echo "--- Test 31c: CHANGE 2 — ambiguity still fails closed even with status-eligible candidates"
test_status_cross_check_ambiguity_fails_closed

# Clean up
clean_gate

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
