#!/usr/bin/env bash
# test-adversarial-pass.sh — Tests for adversarial-pass.sh + subagent-stop.sh parser
#
# Sections:
#   1. ABSENT path — no CLI configured/on PATH → no-op, exit 0, no output
#   2. PRESENT path — stub model → emits ARTIFACT: adversarial-run line
#   3. Timeout path — slow stub → degrades to no-op, exit 0
#   4. Error path — failing stub → degrades to no-op, exit 0
#   5. Empty diff path → no-op, exit 0
#   6. Escape hatch — COPILOT_ADVERSARIAL=off → no-op
#   7. Parser regression — existing artifact types (test-run, file-check, diff-check)
#   8. Parser: adversarial-run recognized as valid type
#   9. Parser: bare VERDICT: APPROVED (no artifact) still fails
#  10. QA gate still unblocks on test-run alone (no adversarial artifact required)
#
# Usage:
#   .claude/hooks/bin/test-adversarial-pass.sh
#
# Exit codes:
#   0 — all tests passed
#   1 — one or more tests failed

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"
ADVERSARIAL_SCRIPT="${SCRIPT_DIR}/adversarial-pass.sh"
SUBAGENT_STOP="${SCRIPT_DIR}/../subagent-stop.sh"
STATE_DIR="${SCRIPT_DIR}/../state"
GATE_FILE="${STATE_DIR}/qa-gate.json"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------
pass() {
  echo "  PASS: $1"
  PASS=$((PASS + 1))
}

fail() {
  echo "  FAIL: $1"
  FAIL=$((FAIL + 1))
}

assert_exit() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" -eq "$expected" ]]; then
    pass "[exit=${expected}] ${label}"
  else
    fail "[exit=${actual}, want ${expected}] ${label}"
  fi
}

assert_empty() {
  local label="$1" value="$2"
  if [[ -z "$value" ]]; then
    pass "[empty output] ${label}"
  else
    fail "[unexpected output: '${value}'] ${label}"
  fi
}

assert_contains() {
  local label="$1" needle="$2" haystack="$3"
  if printf '%s' "$haystack" | grep -q "$needle" 2>/dev/null; then
    pass "[contains '${needle}'] ${label}"
  else
    fail "[missing '${needle}' in: '${haystack}'] ${label}"
  fi
}

assert_not_contains() {
  local label="$1" needle="$2" haystack="$3"
  if ! printf '%s' "$haystack" | grep -q "$needle" 2>/dev/null; then
    pass "[does not contain '${needle}'] ${label}"
  else
    fail "[unexpectedly contains '${needle}' in: '${haystack}'] ${label}"
  fi
}

# ---------------------------------------------------------------------------
# Stub model factory
# ---------------------------------------------------------------------------
TMP_DIR="$(mktemp -d 2>/dev/null)"

cleanup() {
  rm -rf "$TMP_DIR"
  # Remove any test sessions from the gate file
  if [[ -f "$GATE_FILE" ]]; then
    local tmp="${GATE_FILE}.test-cleanup.tmp"
    /usr/bin/jq 'with_entries(select(.key | startswith("test-adversarial-") | not))' \
      "$GATE_FILE" > "$tmp" 2>/dev/null && mv "$tmp" "$GATE_FILE" || true
  fi
}
trap cleanup EXIT

# Stub: success — outputs a FINDINGS line
STUB_OK="${TMP_DIR}/fake-model-ok"
cat > "$STUB_OK" << 'STUBEOF'
#!/usr/bin/env bash
# Reads combined prompt+diff from stdin, outputs a FINDINGS line
input="$(cat)"
echo "FINDINGS: no critical issues found (adversarial-stub)"
exit 0
STUBEOF
chmod +x "$STUB_OK"

# Stub: timeout — sleeps much longer than any test timeout
STUB_SLOW="${TMP_DIR}/fake-model-slow"
cat > "$STUB_SLOW" << 'STUBEOF'
#!/usr/bin/env bash
sleep 120
echo "FINDINGS: too late"
exit 0
STUBEOF
chmod +x "$STUB_SLOW"

# Stub: error — exits non-zero
STUB_FAIL="${TMP_DIR}/fake-model-fail"
cat > "$STUB_FAIL" << 'STUBEOF'
#!/usr/bin/env bash
echo "error: API key not configured" >&2
exit 1
STUBEOF
chmod +x "$STUB_FAIL"

# Stub: outputs findings without the FINDINGS: prefix
STUB_NOFIND="${TMP_DIR}/fake-model-nofind"
cat > "$STUB_NOFIND" << 'STUBEOF'
#!/usr/bin/env bash
echo "The diff looks clean, no issues."
exit 0
STUBEOF
chmod +x "$STUB_NOFIND"

# Sample diff for use in tests
SAMPLE_DIFF="--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def greet(name):
-    return 'Hello ' + name
+    msg = 'Hello ' + name
+    return msg
"

# ---------------------------------------------------------------------------
# Helper: run has_artifact_marker pattern (mirrors subagent-stop.sh exactly)
# ---------------------------------------------------------------------------
has_artifact_marker() {
  local msg="$1"
  printf '%s' "$msg" | grep -qiE \
    '^[[:space:]]*ARTIFACT:[[:space:]]+(test-run|file-check|diff-check|adversarial-run)\|.+$'
}

# ---------------------------------------------------------------------------
# Helper: invoke subagent-stop.sh with a fake QA payload
# Returns exit code; sets GATE_VERDICT to "pass"|"fail"|"unknown"
# ---------------------------------------------------------------------------
invoke_subagent_stop_qa() {
  local session_id="$1" last_msg="$2"
  local payload
  payload="$(printf '{"session_id":"%s","agent_type":"qa","last_assistant_message":%s}' \
    "$session_id" "$(printf '%s' "$last_msg" | /usr/bin/python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"
  printf '%s' "$payload" | COPILOT_QA_GATE=on bash "$SUBAGENT_STOP" 2>/dev/null
  return $?
}

# ---------------------------------------------------------------------------
# Helper: invoke subagent-stop.sh with a fake @agent-me payload
# ---------------------------------------------------------------------------
invoke_subagent_stop_me() {
  local session_id="$1" last_msg="$2"
  local payload
  payload="$(printf '{"session_id":"%s","agent_type":"me","last_assistant_message":%s}' \
    "$session_id" "$(printf '%s' "$last_msg" | /usr/bin/python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"
  printf '%s' "$payload" | COPILOT_QA_GATE=on bash "$SUBAGENT_STOP" 2>/dev/null
  return $?
}

# ---------------------------------------------------------------------------
# Get pending tasks for a session from gate file
# ---------------------------------------------------------------------------
get_pending_tasks() {
  local session_id="$1"
  if [[ ! -f "$GATE_FILE" ]]; then
    echo "[]"
    return
  fi
  /usr/bin/jq -r --arg sid "$session_id" '.[$sid].pending_tasks // [] | length' "$GATE_FILE" 2>/dev/null || echo "0"
}

get_last_event() {
  local session_id="$1"
  if [[ ! -f "$GATE_FILE" ]]; then
    echo "none"
    return
  fi
  /usr/bin/jq -r --arg sid "$session_id" \
    '.[$sid].history // [] | if length > 0 then .[-1].event else "none" end' \
    "$GATE_FILE" 2>/dev/null || echo "none"
}

# ---------------------------------------------------------------------------
# SECTION 1: ABSENT PATH (primary — this machine has no second model CLI)
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 1: ABSENT path (no CLI configured, none on PATH) ==="

# T1: No COPILOT_ADVERSARIAL_CMD, no candidates on PATH → exit 0, no output
output="$(printf '%s' "$SAMPLE_DIFF" | \
  env COPILOT_ADVERSARIAL_CMD="" PATH="/usr/bin:/bin" \
  bash "$ADVERSARIAL_SCRIPT" 2>/dev/null)"
exit_code=$?
assert_exit "absent-path: exits 0" 0 $exit_code
assert_empty "absent-path: no output on stdout" "$output"

# T2: No env var and PATH does not contain codex/llm/mods → same no-op
output="$(printf '%s' "$SAMPLE_DIFF" | \
  env -i HOME="$HOME" PATH="/usr/bin:/bin" \
  bash "$ADVERSARIAL_SCRIPT" 2>/dev/null)"
exit_code=$?
assert_exit "absent-path (clean env): exits 0" 0 $exit_code
assert_empty "absent-path (clean env): no output" "$output"

# T3: COPILOT_ADVERSARIAL_CMD set to a command not on PATH → no-op
output="$(printf '%s' "$SAMPLE_DIFF" | \
  env COPILOT_ADVERSARIAL_CMD="nonexistent-model-xyz-42" \
  bash "$ADVERSARIAL_SCRIPT" 2>/dev/null)"
exit_code=$?
assert_exit "absent-path (cmd not on PATH): exits 0" 0 $exit_code
assert_empty "absent-path (cmd not on PATH): no output" "$output"

# T4: Absent path must NOT emit any ARTIFACT line
assert_not_contains "absent-path: no ARTIFACT line emitted" "ARTIFACT" "${output}"

# ---------------------------------------------------------------------------
# SECTION 2: PRESENT PATH (stub model configured)
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 2: PRESENT path (stub model via COPILOT_ADVERSARIAL_CMD) ==="

# T5: Stub model configured → exits 0 and emits ARTIFACT line
output="$(printf '%s' "$SAMPLE_DIFF" | \
  env COPILOT_ADVERSARIAL_CMD="$STUB_OK" \
  bash "$ADVERSARIAL_SCRIPT" 2>/dev/null)"
exit_code=$?
assert_exit "present-path (stub): exits 0" 0 $exit_code
assert_contains "present-path: ARTIFACT line emitted" "ARTIFACT:" "$output"
assert_contains "present-path: type is adversarial-run" "adversarial-run" "$output"
assert_contains "present-path: exit=0 in artifact detail" "exit=0" "$output"

# T6: FINDINGS: line from stub is captured in artifact
assert_contains "present-path: FINDINGS content in artifact" "FINDINGS" "$output"

# T7: No trailing newlines / clean single line
line_count="$(printf '%s' "$output" | grep -c 'ARTIFACT:' || true)"
if [[ "$line_count" -eq 1 ]]; then
  pass "present-path: exactly one ARTIFACT line"
else
  fail "present-path: expected 1 ARTIFACT line, got ${line_count}"
fi

# T8: Stub with no FINDINGS: prefix → falls back to first non-empty line
output_nofind="$(printf '%s' "$SAMPLE_DIFF" | \
  env COPILOT_ADVERSARIAL_CMD="$STUB_NOFIND" \
  bash "$ADVERSARIAL_SCRIPT" 2>/dev/null)"
exit_nofind=$?
assert_exit "present-path (no-FINDINGS prefix): exits 0" 0 $exit_nofind
assert_contains "present-path (no-FINDINGS prefix): still emits ARTIFACT" "ARTIFACT:" "$output_nofind"

# ---------------------------------------------------------------------------
# SECTION 3: TIMEOUT PATH
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 3: Timeout path (slow stub, 1-second timeout) ==="

# T9: Slow stub with short timeout → no-op (exits 0, no output)
output_slow="$(printf '%s' "$SAMPLE_DIFF" | \
  env COPILOT_ADVERSARIAL_CMD="$STUB_SLOW" \
  COPILOT_ADVERSARIAL_TIMEOUT="1" \
  bash "$ADVERSARIAL_SCRIPT" 2>/dev/null)"
exit_slow=$?
assert_exit "timeout-path: exits 0 (degraded to no-op)" 0 $exit_slow
assert_empty "timeout-path: no output on stdout" "$output_slow"

# ---------------------------------------------------------------------------
# SECTION 4: ERROR PATH
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 4: Error path (stub exits non-zero) ==="

# T10: Failing stub → no-op (exits 0, no output)
output_fail="$(printf '%s' "$SAMPLE_DIFF" | \
  env COPILOT_ADVERSARIAL_CMD="$STUB_FAIL" \
  bash "$ADVERSARIAL_SCRIPT" 2>/dev/null)"
exit_fail=$?
assert_exit "error-path: exits 0 (degraded to no-op)" 0 $exit_fail
assert_empty "error-path: no output on stdout" "$output_fail"

# ---------------------------------------------------------------------------
# SECTION 5: EMPTY DIFF
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 5: Empty diff → no-op ==="

# T11: Empty diff with working stub → no-op (nothing to review)
output_empty="$(printf '' | \
  env COPILOT_ADVERSARIAL_CMD="$STUB_OK" \
  bash "$ADVERSARIAL_SCRIPT" 2>/dev/null)"
exit_empty=$?
assert_exit "empty-diff: exits 0" 0 $exit_empty
assert_empty "empty-diff: no output" "$output_empty"

# T12: Whitespace-only diff → no-op
output_ws="$(printf '   \n\t\n   \n' | \
  env COPILOT_ADVERSARIAL_CMD="$STUB_OK" \
  bash "$ADVERSARIAL_SCRIPT" 2>/dev/null)"
exit_ws=$?
assert_exit "whitespace-diff: exits 0" 0 $exit_ws
assert_empty "whitespace-diff: no output" "$output_ws"

# ---------------------------------------------------------------------------
# SECTION 6: ESCAPE HATCH
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 6: COPILOT_ADVERSARIAL=off escape hatch ==="

# T13: COPILOT_ADVERSARIAL=off → no-op even when stub is configured
output_esc="$(printf '%s' "$SAMPLE_DIFF" | \
  env COPILOT_ADVERSARIAL_CMD="$STUB_OK" COPILOT_ADVERSARIAL=off \
  bash "$ADVERSARIAL_SCRIPT" 2>/dev/null)"
exit_esc=$?
assert_exit "escape-hatch: exits 0" 0 $exit_esc
assert_empty "escape-hatch: no output" "$output_esc"

# ---------------------------------------------------------------------------
# SECTION 7: PARSER REGRESSION — existing artifact types unchanged
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 7: Parser regression — existing types still recognized ==="

# These tests mirror the has_artifact_marker grep pattern in subagent-stop.sh
# exactly (copied here so a future change to the pattern fails both tests).

# T14: test-run still recognized
if has_artifact_marker 'ARTIFACT: test-run|pytest tests/ exit=0 "5 passed"'; then
  pass "parser: test-run recognized"
else
  fail "parser: test-run NOT recognized (REGRESSION)"
fi

# T15: file-check still recognized
if has_artifact_marker 'ARTIFACT: file-check|.claude/agents/manifest.json exists agents=15'; then
  pass "parser: file-check recognized"
else
  fail "parser: file-check NOT recognized (REGRESSION)"
fi

# T16: diff-check still recognized
if has_artifact_marker 'ARTIFACT: diff-check|expected 15 actual 15 match'; then
  pass "parser: diff-check recognized"
else
  fail "parser: diff-check NOT recognized (REGRESSION)"
fi

# T17: Case-insensitive recognition (capital ARTIFACT:)
if has_artifact_marker 'ARTIFACT: test-run|some detail here'; then
  pass "parser: case-insensitive ARTIFACT: prefix"
else
  fail "parser: case-insensitive ARTIFACT: prefix (REGRESSION)"
fi

# T18: Leading whitespace still works
if has_artifact_marker '  ARTIFACT: file-check|foo.txt exists'; then
  pass "parser: leading whitespace allowed"
else
  fail "parser: leading whitespace NOT handled (REGRESSION)"
fi

# T19: No detail after pipe → NOT recognized (type|<detail> requires non-empty detail)
if ! has_artifact_marker 'ARTIFACT: test-run|'; then
  pass "parser: empty detail after pipe not recognized"
else
  fail "parser: empty detail after pipe was incorrectly recognized"
fi

# T20: Unknown type → NOT recognized
if ! has_artifact_marker 'ARTIFACT: random-type|some detail'; then
  pass "parser: unknown type not recognized"
else
  fail "parser: unknown type was incorrectly recognized"
fi

# T21: Missing pipe delimiter → NOT recognized
if ! has_artifact_marker 'ARTIFACT: test-run some detail without pipe'; then
  pass "parser: missing pipe delimiter not recognized"
else
  fail "parser: missing pipe was incorrectly recognized"
fi

# ---------------------------------------------------------------------------
# SECTION 8: adversarial-run recognized by parser
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 8: adversarial-run recognized by parser (new) ==="

# T22: adversarial-run is now a valid type
if has_artifact_marker 'ARTIFACT: adversarial-run|llm FINDINGS: none found exit=0'; then
  pass "parser: adversarial-run recognized"
else
  fail "parser: adversarial-run NOT recognized"
fi

# T23: adversarial-run with uppercase
if has_artifact_marker 'ARTIFACT: ADVERSARIAL-RUN|codex FINDINGS: potential NPE exit=0'; then
  pass "parser: adversarial-run case-insensitive"
else
  fail "parser: adversarial-run case-insensitive NOT handled"
fi

# T24: adversarial-run with minimal detail
if has_artifact_marker 'ARTIFACT: adversarial-run|x'; then
  pass "parser: adversarial-run with minimal detail"
else
  fail "parser: adversarial-run with minimal detail not recognized"
fi

# T25: Verify the output of adversarial-pass.sh (stub present) parses correctly
artifact_line="$(printf '%s' "$SAMPLE_DIFF" | \
  env COPILOT_ADVERSARIAL_CMD="$STUB_OK" \
  bash "$ADVERSARIAL_SCRIPT" 2>/dev/null)"
if [[ -n "$artifact_line" ]] && has_artifact_marker "$artifact_line"; then
  pass "parser: adversarial-pass.sh output parses as valid artifact"
else
  fail "parser: adversarial-pass.sh output '${artifact_line}' did NOT parse as valid artifact"
fi

# ---------------------------------------------------------------------------
# SECTION 9: Gate integration — QA still unblocks on test-run alone
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 9: QA gate — test-run alone still unblocks (no adversarial required) ==="

TEST_SESSION="test-adversarial-$$"

# Step 1: Simulate @agent-me completing TASK-999 (adds to pending)
invoke_subagent_stop_me "$TEST_SESSION" \
  "Task: TASK-999 | WP: WP-1
Files Modified:
- src/foo.py: Added greet function
Summary: Implementation complete." || true

pending_after_me="$(get_pending_tasks "$TEST_SESSION")"
if [[ "$pending_after_me" -eq 1 ]]; then
  pass "gate-integration: TASK-999 added to pending_tasks after me_completed"
else
  fail "gate-integration: expected 1 pending task after me_completed, got ${pending_after_me}"
fi

# Step 2: QA passes with ONLY a test-run artifact (no adversarial artifact)
invoke_subagent_stop_qa "$TEST_SESSION" \
  "Task: TASK-999 | WP: WP-2
Test Coverage:
- Unit: 3 test cases
Summary: All tests pass.
ARTIFACT: test-run|pytest tests/test_foo.py exit=0 \"3 passed\"
VERDICT: APPROVED" || true

pending_after_qa="$(get_pending_tasks "$TEST_SESSION")"
last_event="$(get_last_event "$TEST_SESSION")"

if [[ "$pending_after_qa" -eq 0 ]]; then
  pass "gate-integration: gate cleared by test-run artifact alone (no adversarial required)"
else
  fail "gate-integration: gate NOT cleared; pending=${pending_after_qa}, last_event=${last_event}"
fi

# T27: Verify last event was qa_passed
if printf '%s' "$last_event" | grep -q "qa_passed"; then
  pass "gate-integration: last event is qa_passed"
else
  fail "gate-integration: last event was '${last_event}', expected qa_passed"
fi

# ---------------------------------------------------------------------------
# SECTION 10: Gate integration — adversarial-run alone also unblocks
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 10: QA gate — adversarial-run artifact alone also unblocks ==="

TEST_SESSION2="test-adversarial-adv-$$"

# Simulate me_completed for TASK-998
invoke_subagent_stop_me "$TEST_SESSION2" \
  "Task: TASK-998 complete." || true

# QA passes with ONLY an adversarial-run artifact
invoke_subagent_stop_qa "$TEST_SESSION2" \
  "Task: TASK-998 | WP: WP-3
ARTIFACT: adversarial-run|llm FINDINGS: none found exit=0
VERDICT: APPROVED" || true

pending_adv="$(get_pending_tasks "$TEST_SESSION2")"
if [[ "$pending_adv" -eq 0 ]]; then
  pass "gate-integration: adversarial-run artifact alone also clears the gate"
else
  fail "gate-integration: adversarial-run artifact alone did NOT clear gate; pending=${pending_adv}"
fi

# ---------------------------------------------------------------------------
# SECTION 11: Bare VERDICT: APPROVED with NO artifact still fails
# ---------------------------------------------------------------------------
echo ""
echo "=== Section 11: Bare VERDICT: APPROVED (no artifact) still fails ==="

TEST_SESSION3="test-adversarial-bare-$$"

invoke_subagent_stop_me "$TEST_SESSION3" \
  "Task: TASK-997 complete." || true

invoke_subagent_stop_qa "$TEST_SESSION3" \
  "Task: TASK-997 | WP: WP-4
VERDICT: APPROVED" || true

pending_bare="$(get_pending_tasks "$TEST_SESSION3")"
if [[ "$pending_bare" -eq 1 ]]; then
  pass "gate-integration: bare VERDICT: APPROVED (no artifact) does NOT unblock gate"
else
  fail "gate-integration: bare VERDICT: APPROVED incorrectly unblocked gate (pending should be 1, got ${pending_bare})"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "==================================================================="
echo "Results: ${PASS} passed, ${FAIL} failed"
echo "==================================================================="

[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
