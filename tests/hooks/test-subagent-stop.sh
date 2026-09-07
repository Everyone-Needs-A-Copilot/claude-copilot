#!/usr/bin/env bash
# test-subagent-stop.sh — Tests for .claude/hooks/subagent-stop.sh
#
# Run: bash tests/hooks/test-subagent-stop.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
HOOK="$PROJECT_ROOT/.claude/hooks/subagent-stop.sh"
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

# ---------------------------------------------------------------------------
# Store a real, task-bound QA evidence packet (post-B3: this is the ONLY
# thing that can make `tc task check-qa` — and therefore this hook — report
# a task as approved; see .claude/hooks/subagent-stop.sh's check_qa_verdict).
# TEST_PROJECT is a plain tmp directory, not a git repo, so
# tc.services.qa._current_identity() returns None and staleness comparison
# against IDENTITY is skipped — IDENTITY only needs to be present and
# non-empty here, matching tools/tc/tests/test_qa_completion.py's own
# fixture packet shape.
# ---------------------------------------------------------------------------
store_evidence() {
  local task_num="$1"
  local verdict="${2:-APPROVED}"
  local content
  content="CRITERION: implementation satisfies the guarded behavior
EXPECTED: completion is blocked until real evidence is stored
OBSERVED: evidence stored and tc task check-qa approves
IDENTITY: fixture rev=abc1234, clean
BASELINE: unavailable, fresh fixture database
ARTIFACT: test-run|pytest tests/test_fixture.py exit=0 5 passed
UNTESTED: none
VERDICT: ${verdict}"
  (cd "$TEST_PROJECT" && tc wp store --task "$task_num" --type test --title "Fixture QA evidence" --content "$content" --json) >/dev/null 2>&1
}

store_passing_evidence() {
  store_evidence "$1" "APPROVED"
}

# Direct read of the verdict authority itself (tc task check-qa), used to
# confirm a hook-observed outcome independently of the hook's own state file.
check_qa() {
  (cd "$TEST_PROJECT" && tc task check-qa "$1" --json 2>/dev/null)
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
# Test 3: qa completion with APPROVED verdict — B3: a bare message claim is
# no longer authoritative. `tc task check-qa` is (see
# .claude/hooks/subagent-stop.sh's check_qa_verdict). Part (a) proves an
# unbacked claim leaves the gate armed; part (b) proves a real, stored,
# task-bound evidence packet is what actually clears it; part (c) confirms
# the same verdict directly from the authority itself.
# ---------------------------------------------------------------------------
test_qa_approved_requires_stored_evidence() {
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

  # (a) qa "approves" with a bare message claim — no `tc wp store` evidence
  # exists for TASK-5 at all. Under the new contract this must NOT clear
  # the gate: it is treated as a failed check (retry accounting), exactly
  # like any other unverifiable claim.
  local payload_qa
  payload_qa="$(make_payload "qa" "Task: TASK-5 | WP: WP-20\nVERDICT: APPROVED\nARTIFACT: test-run|pytest tests/test_foo.py exit=0 5 passed")"
  local result
  result="$(invoke_hook "$payload_qa")"
  local exit_code
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "qa APPROVED (bare, no evidence): hook exits 0"
  else
    fail "qa APPROVED (bare, no evidence): expected exit 0, got $exit_code"
  fi

  pending="$(read_pending)"
  if printf '%s' "$pending" | "$JQ" -e 'contains(["TASK-5"])' > /dev/null 2>&1; then
    ok "qa APPROVED (bare, no evidence): TASK-5 remains pending — a message claim alone does not clear the gate"
  else
    fail "qa APPROVED (bare, no evidence): TASK-5 should still be pending: $pending"
  fi

  local last_event
  last_event="$(read_last_event)"
  if [[ "$last_event" == "qa_failed_retry_1" ]]; then
    ok "qa APPROVED (bare, no evidence): treated as a failed check (qa_failed_retry_1) — tc task check-qa is the verdict authority, not the message text"
  else
    fail "qa APPROVED (bare, no evidence): expected qa_failed_retry_1 event, got: $last_event"
  fi

  # (b) Store a real task-bound evidence packet, then a qa completion whose
  # own message text carries no VERDICT line at all — it should still be
  # approved, because check_qa_verdict never scans the message.
  store_passing_evidence 5

  local payload_qa_evidenced
  payload_qa_evidenced="$(make_payload "qa" "Task: TASK-5 | WP: WP-21\nReview complete, see stored evidence.")"
  result="$(invoke_hook "$payload_qa_evidenced")"
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "qa APPROVED (stored evidence): hook exits 0"
  else
    fail "qa APPROVED (stored evidence): expected exit 0, got $exit_code"
  fi

  pending="$(read_pending)"
  local pending_count
  pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
  if [[ "$pending_count" -eq 0 ]]; then
    ok "qa APPROVED (stored evidence): TASK-5 removed from pending_tasks once tc task check-qa approves"
  else
    fail "qa APPROVED (stored evidence): pending_tasks should be empty: $pending"
  fi

  last_event="$(read_last_event)"
  if [[ "$last_event" == "qa_passed" ]]; then
    ok "qa APPROVED (stored evidence): history event is qa_passed"
  else
    fail "qa APPROVED (stored evidence): expected qa_passed event, got: $last_event"
  fi

  # (c) Confirm the same verdict directly from the authority itself.
  local check
  check="$(check_qa 5)"
  if printf '%s' "$check" | "$JQ" -e '.approved == true' > /dev/null 2>&1; then
    ok "qa APPROVED (stored evidence): tc task check-qa 5 independently reports approved=true"
  else
    fail "qa APPROVED (stored evidence): tc task check-qa 5 should report approved=true, got: $check"
  fi
}

# ---------------------------------------------------------------------------
# Test 3b: the verdict authority is tc task check-qa, never a regex over the
# agent's returned message. Proven adversarially: the message text itself
# narrates a REJECTED-sounding sentence and never states "VERDICT: APPROVED"
# anywhere — under the OLD regex-over-message contract this text shape was
# exactly what could steer parsing the wrong way. Under the new contract the
# message is never scanned for a verdict at all.
# ---------------------------------------------------------------------------
test_qa_verdict_authority_is_tc_not_message_text() {
  clean_gate
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-9 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  store_passing_evidence 9

  local payload_qa
  payload_qa="$(make_payload "qa" "Task: TASK-9 | WP: WP-22\nAn earlier attempt was REJECTED for missing coverage, but the fix is now verified by stored evidence.")"
  invoke_hook "$payload_qa" > /dev/null 2>&1 || true

  local pending
  pending="$(read_pending)"
  local pending_count
  pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
  if [[ "$pending_count" -eq 0 ]]; then
    ok "verdict authority: message narrating 'REJECTED' does not block clearing when tc task check-qa approves stored evidence"
  else
    fail "verdict authority: expected TASK-9 cleared on tc-approved evidence despite REJECTED-sounding prose, got: $pending"
  fi
}

# ---------------------------------------------------------------------------
# Test 4: qa completion with APPROVED-WITH-MINOR-FIXES — same B3 split as
# Test 3: a bare claim must not clear the gate; only stored, task-bound
# evidence carrying this verdict does.
# ---------------------------------------------------------------------------
test_qa_approved_minor_fixes_requires_stored_evidence() {
  clean_gate
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-7 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  # (a) bare claim, no evidence stored → stays pending
  local payload_qa_bare result exit_code
  payload_qa_bare="$(make_payload "qa" "Task: TASK-7\nVERDICT: APPROVED-WITH-MINOR-FIXES\nARTIFACT: test-run|pytest tests/test_foo.py exit=0 5 passed")"
  result="$(invoke_hook "$payload_qa_bare")"
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "qa APPROVED-WITH-MINOR-FIXES (bare, no evidence): hook exits 0"
  else
    fail "qa APPROVED-WITH-MINOR-FIXES (bare, no evidence): expected exit 0, got $exit_code"
  fi

  local pending
  pending="$(read_pending)"
  if printf '%s' "$pending" | "$JQ" -e 'contains(["TASK-7"])' > /dev/null 2>&1; then
    ok "qa APPROVED-WITH-MINOR-FIXES (bare, no evidence): TASK-7 remains pending"
  else
    fail "qa APPROVED-WITH-MINOR-FIXES (bare, no evidence): TASK-7 should still be pending: $pending"
  fi

  # (b) stored evidence carrying the same verdict → clears
  store_evidence 7 "APPROVED-WITH-MINOR-FIXES"

  local payload_qa_evidenced
  payload_qa_evidenced="$(make_payload "qa" "Task: TASK-7\nMinor fixes noted, see stored evidence.")"
  result="$(invoke_hook "$payload_qa_evidenced")"
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "qa APPROVED-WITH-MINOR-FIXES (stored evidence): hook exits 0"
  else
    fail "qa APPROVED-WITH-MINOR-FIXES (stored evidence): expected exit 0, got $exit_code"
  fi

  pending="$(read_pending)"
  local pending_count
  pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
  if [[ "$pending_count" -eq 0 ]]; then
    ok "qa APPROVED-WITH-MINOR-FIXES (stored evidence): TASK-7 removed from pending_tasks"
  else
    fail "qa APPROVED-WITH-MINOR-FIXES (stored evidence): pending_tasks should be empty: $pending"
  fi
}

# ---------------------------------------------------------------------------
# Test 5: qa completion with REJECTED verdict → retries incremented
#
# Uses TASK-10 (not TASK-5): TASK-5 already carries a stored, tc-approved
# evidence packet from Test 3, and since evidence is stored in the same tc
# database for the whole suite run (only the gate JSON is reset by
# clean_gate between tests), a task ID reused after evidence has been
# stored for it would no longer exercise a REJECTED/failing check.
# ---------------------------------------------------------------------------
test_qa_rejected_increments_retries() {
  clean_gate
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-10 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  local payload_qa
  payload_qa="$(make_payload "qa" "Task: TASK-10\nVERDICT: REJECTED - tests fail")"
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
  retries="$(read_retries "TASK-10")"
  if [[ "$retries" -eq 1 ]]; then
    ok "qa REJECTED: retries for TASK-10 incremented to 1"
  else
    fail "qa REJECTED: expected retries=1, got $retries"
  fi

  # Task still in pending
  local pending
  pending="$(read_pending)"
  if printf '%s' "$pending" | "$JQ" -e 'contains(["TASK-10"])' > /dev/null 2>&1; then
    ok "qa REJECTED: TASK-10 still in pending_tasks (gate remains active)"
  else
    fail "qa REJECTED: TASK-10 should remain in pending_tasks: $pending"
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
#
# Uses TASK-11 (not TASK-5) for the same reason as Test 5 above.
# ---------------------------------------------------------------------------
test_qa_three_failures_auto_unblock() {
  clean_gate

  # Put TASK-11 in pending
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-11 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  local advisory_output=""

  # Fail 3 times
  local i
  for i in 1 2 3; do
    local payload_qa
    payload_qa="$(make_payload "qa" "Task: TASK-11\nVERDICT: REJECTED - tests still failing")"
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
    ok "qa 3-failures: TASK-11 auto-unblocked (removed from pending_tasks)"
  else
    fail "qa 3-failures: TASK-11 should be auto-unblocked: $pending"
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

  # B3: session-unblocked is strictly distinct from task-verified. The
  # session recovering (pending_tasks cleared, Bash unblocked) must never be
  # mistaken for tc's own predicate marking TASK-11 approved — only a real
  # stored evidence packet can do that, and none was stored here.
  local check
  check="$(check_qa 11)"
  if printf '%s' "$check" | "$JQ" -e '.approved == false' > /dev/null 2>&1; then
    ok "qa 3-failures: tc task check-qa 11 still reports approved=false — session-unblocked never implies task-verified"
  else
    fail "qa 3-failures: tc task check-qa 11 should report approved=false after advisory unblock, got: $check"
  fi
}

# ---------------------------------------------------------------------------
# Test 7: qa verdict parsing — the old "implicit pass" heuristic (a
# <promise>COMPLETE</promise> with no REJECTED token, no explicit VERDICT
# line) is REMOVED entirely under B3. A message shaped exactly like the old
# implicit-pass case, with no evidence stored, must stay pending; only real
# stored evidence clears it — and it clears even though this message still
# carries no VERDICT line, because the message is never scanned for one.
# ---------------------------------------------------------------------------
test_qa_message_without_verdict_requires_stored_evidence() {
  clean_gate
  local payload_me
  payload_me="$(make_payload "me" "Task: TASK-8 completed.")"
  bash "$HOOK" <<< "$payload_me" > /dev/null 2>&1 || true

  # (a) COMPLETE promise, no REJECTED, no VERDICT, no stored evidence
  local payload_qa_bare result exit_code
  payload_qa_bare="$(make_payload "qa" "Task: TASK-8 | WP: WP-22\nAll tests pass.\nARTIFACT: test-run|pytest tests/test_foo.py exit=0 5 passed\n<promise>COMPLETE</promise>")"
  result="$(invoke_hook "$payload_qa_bare")"
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "qa message without VERDICT (no evidence): hook exits 0"
  else
    fail "qa message without VERDICT (no evidence): expected exit 0, got $exit_code"
  fi

  local pending
  pending="$(read_pending)"
  if printf '%s' "$pending" | "$JQ" -e 'contains(["TASK-8"])' > /dev/null 2>&1; then
    ok "qa message without VERDICT (no evidence): TASK-8 remains pending — the removed implicit-pass heuristic no longer applies"
  else
    fail "qa message without VERDICT (no evidence): TASK-8 should still be pending: $pending"
  fi

  # (b) stored evidence → clears, even though this message still carries no
  # VERDICT line of its own
  store_passing_evidence 8

  local payload_qa_evidenced
  payload_qa_evidenced="$(make_payload "qa" "Task: TASK-8 | WP: WP-23\nDone, see stored evidence.\n<promise>COMPLETE</promise>")"
  result="$(invoke_hook "$payload_qa_evidenced")"
  exit_code="$(get_exit_code "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "qa message without VERDICT (stored evidence): hook exits 0"
  else
    fail "qa message without VERDICT (stored evidence): expected exit 0, got $exit_code"
  fi

  pending="$(read_pending)"
  local pending_count
  pending_count="$(printf '%s' "$pending" | "$JQ" 'length' 2>/dev/null || echo 1)"
  if [[ "$pending_count" -eq 0 ]]; then
    ok "qa message without VERDICT (stored evidence): TASK-8 cleared once tc task check-qa approves, independent of message wording"
  else
    fail "qa message without VERDICT (stored evidence): pending_tasks should be empty: $pending"
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
# Test 9: COPILOT_QA_GATE=off escape hatch → hook exits immediately. Uses a
# REAL local task (TASK-14) rather than a nonexistent one so the B3
# session-unblocked/task-verified distinction is actually checkable: the
# escape hatch may bypass gate bookkeeping for the SESSION, but it must
# never be mistaken for tc's own predicate marking the TASK verified.
# ---------------------------------------------------------------------------
test_escape_hatch() {
  clean_gate
  local payload
  payload="$(make_payload "me" "Task: TASK-14 completed.")"

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

  local check
  check="$(check_qa 14)"
  if printf '%s' "$check" | "$JQ" -e '.approved == false' > /dev/null 2>&1; then
    ok "escape hatch: tc task check-qa 14 still reports approved=false — COPILOT_QA_GATE=off unblocks the session, never the task"
  else
    fail "escape hatch: tc task check-qa 14 should report approved=false, got: $check"
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
# Test 11: me completes multiple tasks in same session — B3: clearing is
# bound to the matching task ID only. Only TASK-3 gets a stored evidence
# packet; TASK-3's approval must leave TASK-4 untouched, which is now a
# meaningful check (previously a bare message claim could have cleared
# TASK-3 regardless of evidence, masking whether the binding was real).
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

  # Store real evidence for TASK-3 ONLY — TASK-4 has none.
  store_passing_evidence 3

  # qa approves TASK-3 only (structured header names TASK-3 alone)
  local p3
  p3="$(make_payload "qa" "Task: TASK-3\nSee stored evidence.")"
  bash "$HOOK" <<< "$p3" > /dev/null 2>&1 || true

  pending="$(read_pending)"
  if ! printf '%s' "$pending" | "$JQ" -e 'contains(["TASK-3"])' > /dev/null 2>&1 \
     && printf '%s' "$pending" | "$JQ" -e 'contains(["TASK-4"])' > /dev/null 2>&1; then
    ok "multiple me tasks: after TASK-3's evidence is approved, only TASK-4 remains pending — clearing is bound to the matching task ID only"
  else
    fail "multiple me tasks: expected TASK-4 only in pending, got: $pending"
  fi

  # Confirm this genuinely reflects the binding, not coincidental ordering:
  # TASK-4 has no evidence of its own and tc independently agrees.
  local check4
  check4="$(check_qa 4)"
  if printf '%s' "$check4" | "$JQ" -e '.approved == false' > /dev/null 2>&1; then
    ok "multiple me tasks: tc task check-qa 4 independently confirms TASK-4 is not approved"
  else
    fail "multiple me tasks: tc task check-qa 4 should report approved=false, got: $check4"
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
echo "--- Test 3: qa APPROVED requires stored, task-bound evidence (bare claim vs. real evidence)"
test_qa_approved_requires_stored_evidence
echo "--- Test 3b: verdict authority is tc task check-qa, not message text"
test_qa_verdict_authority_is_tc_not_message_text
echo "--- Test 4: qa APPROVED-WITH-MINOR-FIXES requires stored evidence"
test_qa_approved_minor_fixes_requires_stored_evidence
echo "--- Test 5: qa REJECTED → retries incremented, task stays pending"
test_qa_rejected_increments_retries
echo "--- Test 6: 3 consecutive qa failures → auto-unblock + advisory (session-unblocked, never task-verified)"
test_qa_three_failures_auto_unblock
echo "--- Test 7: qa message without VERDICT requires stored evidence (old implicit-pass heuristic removed)"
test_qa_message_without_verdict_requires_stored_evidence
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
