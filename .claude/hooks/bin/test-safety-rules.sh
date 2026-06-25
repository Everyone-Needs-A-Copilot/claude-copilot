#!/usr/bin/env bash
# test-safety-rules.sh — Integration tests for the safety primitives in pretool-check.sh
#
# Tests: rule_destructive_command (/careful) and rule_path_scope (/freeze)
#
# Usage:
#   .claude/hooks/bin/test-safety-rules.sh
#
# Exit codes:
#   0 — all tests passed
#   1 — one or more tests failed

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"
HOOK="${SCRIPT_DIR}/../pretool-check.sh"
STATE_DIR="${SCRIPT_DIR}/../state"
FREEZE_FILE="${STATE_DIR}/.freeze"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

# invoke_hook <payload_json> → sets HOOK_EXIT and HOOK_STDOUT and HOOK_STDERR
invoke_hook() {
  local payload="$1"
  HOOK_STDOUT="$(printf '%s' "$payload" | COPILOT_FORCE_DELEGATE=off COPILOT_QA_GATE=off \
    bash "$HOOK" 2>/tmp/test-safety-stderr)"
  HOOK_EXIT=$?
  HOOK_STDERR="$(cat /tmp/test-safety-stderr 2>/dev/null || true)"
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

assert_stdout_contains() {
  local test_name="$1" needle="$2"
  if printf '%s' "$HOOK_STDOUT" | grep -q "$needle" 2>/dev/null; then
    echo "  PASS [stdout contains '${needle}']: ${test_name}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL [stdout='${HOOK_STDOUT}', want '${needle}']: ${test_name}"
    FAIL=$((FAIL + 1))
  fi
}

assert_stderr_contains() {
  local test_name="$1" needle="$2"
  if printf '%s' "$HOOK_STDERR" | grep -q "$needle" 2>/dev/null; then
    echo "  PASS [stderr contains '${needle}']: ${test_name}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL [stderr='${HOOK_STDERR}', want '${needle}']: ${test_name}"
    FAIL=$((FAIL + 1))
  fi
}

# Unique session ID for tests (avoids affecting real sessions)
TEST_SESSION="test-safety-rules-$$"

# Build a Bash tool payload
bash_payload() {
  local cmd="$1"
  printf '{"session_id":"%s","tool_name":"Bash","tool_input":{"command":"%s"}}' \
    "$TEST_SESSION" "$(printf '%s' "$cmd" | sed 's/"/\\"/g')"
}

# Build an Edit tool payload
edit_payload() {
  local file_path="$1"
  printf '{"session_id":"%s","tool_name":"Edit","tool_input":{"file_path":"%s","old_string":"a","new_string":"b"}}' \
    "$TEST_SESSION" "$file_path"
}

# Build a Write tool payload
write_payload() {
  local file_path="$1"
  printf '{"session_id":"%s","tool_name":"Write","tool_input":{"file_path":"%s","content":"test"}}' \
    "$TEST_SESSION" "$file_path"
}

# ---------------------------------------------------------------------------
# Teardown: clean freeze state + streak state after tests
# ---------------------------------------------------------------------------
cleanup() {
  rm -f "$FREEZE_FILE"
  rm -f "${STATE_DIR}/streak-${TEST_SESSION}.json"
  rm -f /tmp/test-safety-stderr
}
trap cleanup EXIT

# Remove any leftover freeze state from a previous aborted test run
rm -f "$FREEZE_FILE"

# ---------------------------------------------------------------------------
# SECTION 1: rule_destructive_command (/careful)
# ---------------------------------------------------------------------------
echo ""
echo "=== /careful (rule_destructive_command) ==="

# T1: Block — git push --force (block severity)
invoke_hook "$(bash_payload "git push origin main --force")"
assert_exit "git push --force is blocked" 2
assert_stdout_contains "git push --force stdout has deny reason" "permissionDecision"

# T2: Block — git push -f (common shorthand)
invoke_hook "$(bash_payload "git push -f")"
assert_exit "git push -f is blocked" 2

# T3: Block — git push origin -f (with remote arg)
invoke_hook "$(bash_payload "git push origin -f")"
assert_exit "git push origin -f is blocked" 2

# T4: Warn — rm -rf / (warn severity — destructive-command rule)
invoke_hook "$(bash_payload "rm -rf /")"
assert_exit "rm -rf / exits 0 (warn, not block)" 0
assert_stderr_contains "rm -rf / emits safety-warn to stderr" "safety-warn"

# T5: Warn — git reset --hard
invoke_hook "$(bash_payload "git reset --hard HEAD~1")"
assert_exit "git reset --hard exits 0 (warn)" 0
assert_stderr_contains "git reset --hard emits safety-warn" "safety-warn"

# T6: Warn — DROP TABLE
invoke_hook "$(bash_payload "psql -c 'DROP TABLE users;'")"
assert_exit "DROP TABLE exits 0 (warn)" 0
assert_stderr_contains "DROP TABLE emits safety-warn" "safety-warn"

# T7: Allow — normal command (ls)
invoke_hook "$(bash_payload "ls -la /tmp")"
assert_exit "ls -la is allowed (exit 0)" 0

# T8: Allow — git push without --force
invoke_hook "$(bash_payload "git push origin main")"
assert_exit "git push origin main is allowed" 0

# T9: Escape hatch — COPILOT_CAREFUL=off bypasses block
HOOK_STDOUT="$(printf '%s' "$(bash_payload "git push --force")" | \
  COPILOT_FORCE_DELEGATE=off COPILOT_QA_GATE=off COPILOT_CAREFUL=off \
  bash "$HOOK" 2>/tmp/test-safety-stderr)"
HOOK_EXIT=$?
if [[ "$HOOK_EXIT" -eq 0 ]]; then
  echo "  PASS [exit=0]: COPILOT_CAREFUL=off bypasses git push --force block"
  PASS=$((PASS + 1))
else
  echo "  FAIL [exit=${HOOK_EXIT}, want 0]: COPILOT_CAREFUL=off should bypass block"
  FAIL=$((FAIL + 1))
fi

# T10: Escape hatch — COPILOT_SAFETY=off bypasses block
HOOK_STDOUT="$(printf '%s' "$(bash_payload "git push --force")" | \
  COPILOT_FORCE_DELEGATE=off COPILOT_QA_GATE=off COPILOT_SAFETY=off \
  bash "$HOOK" 2>/tmp/test-safety-stderr)"
HOOK_EXIT=$?
if [[ "$HOOK_EXIT" -eq 0 ]]; then
  echo "  PASS [exit=0]: COPILOT_SAFETY=off bypasses git push --force block"
  PASS=$((PASS + 1))
else
  echo "  FAIL [exit=${HOOK_EXIT}, want 0]: COPILOT_SAFETY=off should bypass block"
  FAIL=$((FAIL + 1))
fi

# ---------------------------------------------------------------------------
# SECTION 2: rule_path_scope (/freeze)
# ---------------------------------------------------------------------------
echo ""
echo "=== /freeze (rule_path_scope) ==="

FREEZE_DIR="/tmp/test-freeze-$$"
mkdir -p "$FREEZE_DIR"
cleanup_freeze_dir() { rm -rf "$FREEZE_DIR"; }
trap "cleanup_freeze_dir; cleanup" EXIT

# Set up freeze state
printf '%s\n' "$FREEZE_DIR" > "$FREEZE_FILE"

# T11: Allow — Edit inside freeze dir
invoke_hook "$(edit_payload "${FREEZE_DIR}/foo.txt")"
assert_exit "Edit inside freeze dir is allowed" 0

# T12: Block — Edit outside freeze dir
invoke_hook "$(edit_payload "/tmp/outside-project/bar.txt")"
assert_exit "Edit outside freeze dir is blocked" 2
assert_stdout_contains "Edit outside freeze has deny reason" "permissionDecision"

# T13: Allow — Write inside freeze dir
invoke_hook "$(write_payload "${FREEZE_DIR}/subdir/file.txt")"
assert_exit "Write inside freeze dir is allowed" 0

# T14: Block — Write outside freeze dir
invoke_hook "$(write_payload "/etc/hosts")"
assert_exit "Write outside freeze dir (/etc/hosts) is blocked" 2

# T15: Allow — Bash without redirect (no path violation)
invoke_hook "$(bash_payload "ls -la ${FREEZE_DIR}")"
assert_exit "Bash ls inside freeze dir is allowed" 0

# T16: Block — Bash redirect to outside-freeze path
invoke_hook "$(bash_payload "echo hello > /tmp/outside.txt")"
assert_exit "Bash redirect outside freeze dir is blocked" 2

# T17: Allow — Bash redirect to inside-freeze path
invoke_hook "$(bash_payload "echo hello > ${FREEZE_DIR}/output.txt")"
assert_exit "Bash redirect inside freeze dir is allowed" 0

# T18: Escape hatch — COPILOT_FREEZE=off bypasses freeze block
HOOK_STDOUT="$(printf '%s' "$(edit_payload "/tmp/outside-project/bar.txt")" | \
  COPILOT_FORCE_DELEGATE=off COPILOT_QA_GATE=off COPILOT_FREEZE=off \
  bash "$HOOK" 2>/tmp/test-safety-stderr)"
HOOK_EXIT=$?
if [[ "$HOOK_EXIT" -eq 0 ]]; then
  echo "  PASS [exit=0]: COPILOT_FREEZE=off bypasses freeze block"
  PASS=$((PASS + 1))
else
  echo "  FAIL [exit=${HOOK_EXIT}, want 0]: COPILOT_FREEZE=off should bypass freeze"
  FAIL=$((FAIL + 1))
fi

# T19: Escape hatch — COPILOT_SAFETY=off bypasses freeze
HOOK_STDOUT="$(printf '%s' "$(write_payload "/etc/hosts")" | \
  COPILOT_FORCE_DELEGATE=off COPILOT_QA_GATE=off COPILOT_SAFETY=off \
  bash "$HOOK" 2>/tmp/test-safety-stderr)"
HOOK_EXIT=$?
if [[ "$HOOK_EXIT" -eq 0 ]]; then
  echo "  PASS [exit=0]: COPILOT_SAFETY=off bypasses freeze block"
  PASS=$((PASS + 1))
else
  echo "  FAIL [exit=${HOOK_EXIT}, want 0]: COPILOT_SAFETY=off should bypass freeze"
  FAIL=$((FAIL + 1))
fi

# T20: No freeze file — no restriction
rm -f "$FREEZE_FILE"
invoke_hook "$(edit_payload "/tmp/outside-project/bar.txt")"
assert_exit "No freeze file → no restriction on outside path" 0

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "==================================================================="
echo "Results: ${PASS} passed, ${FAIL} failed"
echo "==================================================================="

[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
