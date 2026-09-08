#!/usr/bin/env bash
# test-qa-gate-integration.sh — End-to-end integration test for QA gate state machine
#
# Proves the full flow:
#   1. SubagentStop(me) → pending_tasks gets TASK-N
#   2. PreToolUse(Bash) → deny
#   3. PreToolUse(Agent, subagent_type=qa) with an authoritative no-active
#      journey witness → allow
#   4. SubagentStop(qa, bare APPROVED claim, no stored evidence) →
#      pending_tasks stays armed and Bash stays denied (B3: a message claim
#      alone is never authoritative)
#   5. Store a real, task-bound QA evidence packet, then SubagentStop(qa)
#      again → tc task check-qa approves and pending_tasks clears
#   6. PreToolUse(Bash) → allow again, now backed by real evidence
#
# Also proves session-unblocked is strictly distinct from task-verified
# (Scenario 2: retry exhaustion unblocks the session but tc task check-qa
# still reports the task unapproved).
#
# Run: bash tests/hooks/test-qa-gate-integration.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
PRETOOL_HOOK="$PROJECT_ROOT/.claude/hooks/pretool-check.sh"
STOP_HOOK="$PROJECT_ROOT/.claude/hooks/subagent-stop.sh"
JQ="/usr/bin/jq"

TEST_SESSION="integ-test-$$"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/qa-gate-integration.XXXXXX")"
TEST_PROJECT="${TEST_ROOT}/project"
OTHER_PROJECT="${TEST_ROOT}/other-project"
STATE_DIR="${TEST_ROOT}/state"
GATE_FILE="${STATE_DIR}/qa-gate.json"
NO_ACTIVE_CC="${STATE_DIR}/test-no-active-cc"

# Hooks must resolve task authority and state entirely inside the fixture.
export CLAUDE_PROJECT_DIR="$TEST_PROJECT"
export COPILOT_HOOK_STATE_DIR="$STATE_DIR"

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

cleanup_state() {
  rm -f "$GATE_FILE" \
        "${STATE_DIR}/qa-gate.lock" \
        "${STATE_DIR}/qa-gate.log" \
        "${STATE_DIR}/streak-${TEST_SESSION}.json" \
        "${STATE_DIR}/streak-${TEST_SESSION}.lock" 2>/dev/null || true
}

cleanup_all() {
  case "$TEST_ROOT" in
    "${TMPDIR:-/tmp}"/qa-gate-integration.*) rm -rf -- "$TEST_ROOT" ;;
    *) echo "Refusing to remove unexpected fixture root: $TEST_ROOT" >&2 ;;
  esac
}

trap cleanup_all EXIT

mkdir -p "$TEST_PROJECT" "$OTHER_PROJECT" "$STATE_DIR"
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'printf '\''%s\n'\'' '\''{"schema_version":"2.1","state":"no_active"}'\''' \
  > "$NO_ACTIVE_CC"
chmod +x "$NO_ACTIVE_CC"
tc init --path "$TEST_PROJECT" --json >/dev/null
tc init --path "$OTHER_PROJECT" --json >/dev/null

create_task() {
  local project="$1"
  local title="$2"
  (cd "$project" && tc task create --title "$title" --json) | "$JQ" -r '.id'
}

PRIMARY_TASK_ID="$(create_task "$TEST_PROJECT" "QA gate approval fixture")"
RETRY_TASK_ID="$(create_task "$TEST_PROJECT" "QA gate retry fixture")"

# Create one more task in the other project than exists in the primary one.
# Its ID is valid there but cannot resolve against CLAUDE_PROJECT_DIR.
create_task "$OTHER_PROJECT" "Other project one" >/dev/null
create_task "$OTHER_PROJECT" "Other project two" >/dev/null
CROSS_PROJECT_TASK_ID="$(create_task "$OTHER_PROJECT" "Other project only")"
INVALID_TASK_ID=999999

PRIMARY_TASK="TASK-${PRIMARY_TASK_ID}"
RETRY_TASK="TASK-${RETRY_TASK_ID}"
CROSS_PROJECT_TASK="TASK-${CROSS_PROJECT_TASK_ID}"
INVALID_TASK="TASK-${INVALID_TASK_ID}"

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
  output="$(COPILOT_CC_BIN="$NO_ACTIVE_CC" bash "$PRETOOL_HOOK" <<< "$payload" 2>/dev/null)" || exit_code=$?
  printf '%d|%s' "$exit_code" "$output"
}

get_exit_code() { printf '%s' "$1" | cut -d'|' -f1; }
get_output()    { printf '%s' "$1" | cut -d'|' -f2-; }

# Store v2 task-bound evidence against an actual fixture source and check.
# Plain directories also require a registered contract and real source identity.
store_passing_evidence() {
  local task_num="$1"
  local content identity
  printf '%s\n' 'guarded fixture' > "$TEST_PROJECT/acceptance-input.txt"
  printf '%s\n' '{"schemaVersion":2,"criteria":[{"id":"C1","expected":"The guarded fixture input exists"}],"sources":["acceptance-input.txt"]}' > "$TEST_ROOT/contract.json"
  (cd "$TEST_PROJECT" && tc task contract "$task_num" --file "$TEST_ROOT/contract.json" --json) >/dev/null || return 1
  identity="$(cd "$TEST_PROJECT" && tc task evidence-identity "$task_num")" || return 1
  (cd "$TEST_PROJECT" && test -f acceptance-input.txt) || return 1
  content="CRITERION: C1
EXPECTED: The guarded fixture input exists
OBSERVED: test -f acceptance-input.txt returned exit 0 against the captured source
$identity
BASELINE: unavailable, fresh fixture database
ARTIFACT: test-run|test -f acceptance-input.txt exit=0
UNTESTED: none
VERDICT: APPROVED"
  (cd "$TEST_PROJECT" && tc wp store --task "$task_num" --type test --title "Fixture QA evidence" --content "$content" --json) >/dev/null 2>&1
}

check_qa() {
  (cd "$TEST_PROJECT" && tc task check-qa "$1" --json 2>/dev/null)
}

# ---------------------------------------------------------------------------
# Integration test: full state machine flow
# ---------------------------------------------------------------------------
echo "=== QA gate integration test ==="
echo ""
echo "Scenario: me completes ${PRIMARY_TASK} → gate blocks → qa approves → gate clears"
echo ""

cleanup_state

# --- Step 1: SubagentStop(me) with a real local task ---
echo "Step 1: SubagentStop(me, 'Task: ${PRIMARY_TASK} completed')"
send_stop "me" "Task: ${PRIMARY_TASK} | WP: WP-1\nSummary: implementation done."

PENDING="$("$JQ" -r --arg sid "$TEST_SESSION" \
  '.[$sid].pending_tasks // [] | @json' "$GATE_FILE" 2>/dev/null || echo "[]")"

if printf '%s' "$PENDING" | "$JQ" -e --arg task "$PRIMARY_TASK" 'contains([$task])' > /dev/null 2>&1; then
  ok "Step 1: pending_tasks includes ${PRIMARY_TASK} after me completion"
else
  fail "Step 1: ${PRIMARY_TASK} not in pending_tasks after me completion: $PENDING"
fi

# --- Step 2: PreToolUse(Bash, "ls") → should be denied ---
echo ""
echo "Step 2: PreToolUse(Bash, 'ls') → expect deny"
RESULT="$(send_pretool_bash "ls")"
EXIT="$(get_exit_code "$RESULT")"
OUTPUT="$(get_output "$RESULT")"

if [[ "$EXIT" -eq 2 ]]; then
  ok "Step 2: Bash 'ls' denied (exit 2) while ${PRIMARY_TASK} pending"
else
  fail "Step 2: expected exit 2 (deny), got exit $EXIT"
fi
if printf '%s' "$OUTPUT" | "$JQ" -e '.permissionDecision == "deny"' > /dev/null 2>&1; then
  ok "Step 2: deny response contains permissionDecision=deny"
else
  fail "Step 2: deny response malformed: $OUTPUT"
fi

# --- Step 3: PreToolUse(Agent, subagent_type=qa) with no active journey → allow ---
echo ""
echo "Step 3: PreToolUse(Agent, subagent_type=qa) → expect allow"
RESULT="$(send_pretool_agent "qa")"
EXIT="$(get_exit_code "$RESULT")"

if [[ "$EXIT" -eq 0 ]]; then
  ok "Step 3: Agent(qa) allowed (exit 0) while ${PRIMARY_TASK} pending"
else
  fail "Step 3: expected exit 0 (allow) for Agent(qa), got exit $EXIT"
fi

# --- Step 4: PreToolUse(Bash, "tc task get N") → safe prefix, should be allowed ---
echo ""
echo "Step 4: PreToolUse(Bash, 'tc task get ${PRIMARY_TASK_ID} --json') → expect allow (safe prefix)"
RESULT="$(send_pretool_bash "tc task get ${PRIMARY_TASK_ID} --json")"
EXIT="$(get_exit_code "$RESULT")"

if [[ "$EXIT" -eq 0 ]]; then
  ok "Step 4: 'tc task get ${PRIMARY_TASK_ID} --json' allowed while pending (safe prefix)"
else
  fail "Step 4: expected exit 0 for safe tc command, got exit $EXIT"
fi

# --- Step 5: SubagentStop(qa, bare APPROVED claim, no stored evidence) →
# B3: a message claim alone is never authoritative. tc task check-qa is the
# verdict source, and no work product has been stored for PRIMARY_TASK yet,
# so the gate must stay armed. ---
echo ""
echo "Step 5: SubagentStop(qa, '${PRIMARY_TASK} VERDICT: APPROVED', no stored evidence) → expect gate STAYS ARMED"
send_stop "qa" "Task: ${PRIMARY_TASK} | WP: WP-2\nAll tests pass.\nVERDICT: APPROVED\nARTIFACT: test-run|pytest tests/test_foo.py exit=0 5 passed"

PENDING="$("$JQ" -r --arg sid "$TEST_SESSION" \
  '.[$sid].pending_tasks // [] | @json' "$GATE_FILE" 2>/dev/null || echo "[]")"

if printf '%s' "$PENDING" | "$JQ" -e --arg task "$PRIMARY_TASK" 'contains([$task])' > /dev/null 2>&1; then
  ok "Step 5: pending_tasks still contains ${PRIMARY_TASK} — a bare APPROVED claim with no stored evidence does not clear the gate"
else
  fail "Step 5: ${PRIMARY_TASK} should still be pending after an unbacked APPROVED claim: $PENDING"
fi

# --- Step 5b: PreToolUse(Bash, "ls") → still denied, no evidence yet ---
echo ""
echo "Step 5b: PreToolUse(Bash, 'ls') → expect deny (gate still armed, claim unbacked)"
RESULT="$(send_pretool_bash "ls")"
EXIT="$(get_exit_code "$RESULT")"

if [[ "$EXIT" -eq 2 ]]; then
  ok "Step 5b: Bash 'ls' still denied (exit 2) — an unbacked verdict claim never unblocks the gate"
else
  fail "Step 5b: expected exit 2 (deny) with no stored evidence, got exit $EXIT"
fi

# --- Step 5c: store real task-bound evidence for PRIMARY_TASK, then qa
# reports completion again. This message carries no VERDICT line at all —
# the point is that tc task check-qa's own read of the stored evidence is
# what decides, not this hook re-scanning message text. ---
echo ""
echo "Step 5c: store task-bound evidence for ${PRIMARY_TASK}, then SubagentStop(qa) → expect gate clear"
store_passing_evidence "$PRIMARY_TASK_ID"

CHECK_QA="$(check_qa "$PRIMARY_TASK_ID")"
if printf '%s' "$CHECK_QA" | "$JQ" -e '.approved == true' > /dev/null 2>&1; then
  ok "Step 5c: tc task check-qa ${PRIMARY_TASK_ID} independently reports approved=true once evidence is stored"
else
  fail "Step 5c: tc task check-qa ${PRIMARY_TASK_ID} should report approved=true, got: $CHECK_QA"
fi

send_stop "qa" "Task: ${PRIMARY_TASK} | WP: WP-2b\nSee stored evidence."

PENDING="$("$JQ" -r --arg sid "$TEST_SESSION" \
  '.[$sid].pending_tasks // [] | @json' "$GATE_FILE" 2>/dev/null || echo "[]")"
PENDING_COUNT="$(printf '%s' "$PENDING" | "$JQ" 'length' 2>/dev/null || echo 1)"

if [[ "$PENDING_COUNT" -eq 0 ]]; then
  ok "Step 5c: pending_tasks is empty after tc task check-qa approves stored evidence"
else
  fail "Step 5c: pending_tasks should be empty after evidence-backed approval: $PENDING"
fi

# --- Step 6: PreToolUse(Bash, "ls") → should now be allowed ---
echo ""
echo "Step 6: PreToolUse(Bash, 'ls') → expect allow (gate cleared by real evidence)"
RESULT="$(send_pretool_bash "ls")"
EXIT="$(get_exit_code "$RESULT")"

if [[ "$EXIT" -eq 0 ]]; then
  ok "Step 6: Bash 'ls' allowed (exit 0) after gate cleared by evidence-backed approval"
else
  fail "Step 6: expected exit 0 (allow) after gate cleared, got exit $EXIT"
fi

echo ""
echo "Step 7: change the captured source → expect stored evidence rejected"
printf '%s\n' 'changed guarded fixture' > "$TEST_PROJECT/acceptance-input.txt"
QA_RESULT="$(check_qa "$PRIMARY_TASK_ID")"
if printf '%s' "$QA_RESULT" | "$JQ" -e '.approved == false and (.reason | contains("stale"))' >/dev/null; then
  ok "Step 7: changed source invalidates previously approved evidence"
else
  fail "Step 7: stale evidence should be rejected: $QA_RESULT"
fi

echo ""
echo "--- Scenario 2: 3 qa failures → auto-unblock ---"
cleanup_state

echo ""
echo "Step 1: me completes ${RETRY_TASK}"
send_stop "me" "Task: ${RETRY_TASK} | WP: WP-3\nSummary: implementation done."

echo "Step 2-4: qa fails 3 times"
LAST_OUTPUT=""
for i in 1 2 3; do
  OUTPUT="$(send_stop "qa" "Task: ${RETRY_TASK} | WP: WP-4\nVERDICT: REJECTED - failing tests" 2>/dev/null || true)"
  if [[ -n "$OUTPUT" ]]; then
    LAST_OUTPUT="$OUTPUT"
  fi
done

PENDING="$("$JQ" -r --arg sid "$TEST_SESSION" \
  '.[$sid].pending_tasks // [] | @json' "$GATE_FILE" 2>/dev/null || echo "[]")"
PENDING_COUNT="$(printf '%s' "$PENDING" | "$JQ" 'length' 2>/dev/null || echo 1)"

if [[ "$PENDING_COUNT" -eq 0 ]]; then
  ok "Scenario 2: ${RETRY_TASK} auto-unblocked after 3 qa failures"
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

# B3: session-unblocked is strictly distinct from task-verified. The SESSION
# recovered (Bash allowed above), but tc's own predicate must still report
# RETRY_TASK as unapproved — retry exhaustion never manufactures evidence.
echo "Step 6: tc task check-qa ${RETRY_TASK_ID} after auto-unblock → expect approved=false"
CHECK_QA="$(check_qa "$RETRY_TASK_ID")"
if printf '%s' "$CHECK_QA" | "$JQ" -e '.approved == false' > /dev/null 2>&1; then
  ok "Scenario 2: tc task check-qa ${RETRY_TASK_ID} still reports approved=false — session-unblocked never implies task-verified"
else
  fail "Scenario 2: tc task check-qa ${RETRY_TASK_ID} should report approved=false after advisory unblock, got: $CHECK_QA"
fi

echo ""
echo "--- Scenario 3: invalid and cross-project task IDs never arm ---"
cleanup_state

send_stop "me" "Task: ${INVALID_TASK} | WP: WP-5\nSummary: invalid fixture ID."
PENDING="$("$JQ" -r --arg sid "$TEST_SESSION" \
  '.[$sid].pending_tasks // [] | @json' "$GATE_FILE" 2>/dev/null || echo "[]")"
if [[ "$PENDING" == "[]" ]]; then
  ok "Scenario 3: nonexistent ${INVALID_TASK} does not arm the gate"
else
  fail "Scenario 3: nonexistent ${INVALID_TASK} armed the gate: $PENDING"
fi

send_stop "me" "Task: ${CROSS_PROJECT_TASK} | WP: WP-6\nSummary: task exists only in another project."
PENDING="$("$JQ" -r --arg sid "$TEST_SESSION" \
  '.[$sid].pending_tasks // [] | @json' "$GATE_FILE" 2>/dev/null || echo "[]")"
if [[ "$PENDING" == "[]" ]]; then
  ok "Scenario 3: ${CROSS_PROJECT_TASK} from another tc project does not arm the gate"
else
  fail "Scenario 3: cross-project ${CROSS_PROJECT_TASK} armed the gate: $PENDING"
fi

RESULT="$(send_pretool_bash "ls")"
EXIT="$(get_exit_code "$RESULT")"
if [[ "$EXIT" -eq 0 ]]; then
  ok "Scenario 3: Bash remains allowed after rejected task IDs"
else
  fail "Scenario 3: rejected task IDs left a gate behind (exit $EXIT)"
fi

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
cleanup_state

echo ""
echo "=== Integration test results: $PASS passed, $FAIL failed ==="
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
