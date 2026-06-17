#!/usr/bin/env bash
# test-user-prompt-submit.sh — Tests for .claude/hooks/user-prompt-submit.sh
#
# Mirrors the pattern of test-pretool-check.sh (plain bash assertions).
#
# Run: bash tests/hooks/test-user-prompt-submit.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
HOOK="$PROJECT_ROOT/.claude/hooks/user-prompt-submit.sh"
STATE_DIR="$PROJECT_ROOT/.claude/hooks/state"
STATE_FILE="${STATE_DIR}/session-turns.json"

TEST_SESSION="test-ups-$$"

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

# Build a minimal UserPromptSubmit payload
make_payload() {
  local session_id="$1"
  local prompt="${2:-hello}"
  printf '{"session_id":"%s","prompt":"%s"}' "$session_id" "$prompt"
}

# Invoke hook once and return "exit_code|stdout"
invoke_hook() {
  local session_id="$1"
  local extra_env="${2:-}"
  local payload
  payload="$(make_payload "$session_id")"
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

# Inject a session state directly into session-turns.json
seed_turns() {
  local session_id="$1"
  local turns="$2"
  local warned="${3:-false}"
  local warned_strong="${4:-false}"
  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  local entry
  entry="$(printf '{"turns":%d,"firstSeen":"%s","lastSeen":"%s","warned":%s,"warnedStrong":%s}' \
    "$turns" "$now" "$now" "$warned" "$warned_strong")"

  # Read existing state (if any) and merge
  local existing='{}'
  if [[ -f "$STATE_FILE" ]]; then
    existing="$(cat "$STATE_FILE" 2>/dev/null || echo '{}')"
  fi
  local merged
  merged="$(printf '%s' "$existing" | /usr/bin/jq \
    --arg sid "$session_id" \
    --argjson e "$entry" \
    '.[$sid] = $e' 2>/dev/null || echo "$existing")"
  printf '%s\n' "$merged" > "$STATE_FILE"
}

# Read turns for a session from state file
read_turns() {
  local session_id="$1"
  if [[ ! -f "$STATE_FILE" ]]; then
    echo 0
    return
  fi
  /usr/bin/jq -r --arg sid "$session_id" '.[$sid].turns // 0' "$STATE_FILE" 2>/dev/null || echo 0
}

read_warned() {
  local session_id="$1"
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "false"
    return
  fi
  /usr/bin/jq -r --arg sid "$session_id" '.[$sid].warned // false' "$STATE_FILE" 2>/dev/null || echo "false"
}

read_warned_strong() {
  local session_id="$1"
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "false"
    return
  fi
  /usr/bin/jq -r --arg sid "$session_id" '.[$sid].warnedStrong // false' "$STATE_FILE" 2>/dev/null || echo "false"
}

# Clean a specific test session from state
clean_session() {
  local session_id="$1"
  if [[ -f "$STATE_FILE" ]]; then
    local cleaned
    cleaned="$(/usr/bin/jq --arg sid "$session_id" 'del(.[$sid])' "$STATE_FILE" 2>/dev/null || cat "$STATE_FILE")"
    printf '%s\n' "$cleaned" > "$STATE_FILE"
  fi
  rm -f "${STATE_DIR}/session-turns.lock" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Test 1: New session → turns=1, no advisory, exit 0
# ---------------------------------------------------------------------------
test_new_session() {
  local sid="${TEST_SESSION}-new"
  clean_session "$sid"

  local result output exit_code
  result="$(invoke_hook "$sid")"
  exit_code="$(get_exit_code "$result")"
  output="$(get_output "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "new session exits 0"
  else
    fail "new session expected exit 0, got $exit_code"
  fi

  if [[ -z "$output" ]]; then
    ok "new session produces no advisory output"
  else
    fail "new session expected no output, got: $output"
  fi

  local turns
  turns="$(read_turns "$sid")"
  if [[ "$turns" -eq 1 ]]; then
    ok "new session turn count is 1"
  else
    fail "new session expected turns=1, got $turns"
  fi

  clean_session "$sid"
}

# ---------------------------------------------------------------------------
# Test 2: 499 turns → no advisory
# ---------------------------------------------------------------------------
test_499_turns_no_advisory() {
  local sid="${TEST_SESSION}-499"
  clean_session "$sid"
  seed_turns "$sid" 498 "false" "false"

  local result output
  result="$(invoke_hook "$sid")"
  output="$(get_output "$result")"

  if [[ -z "$output" ]]; then
    ok "499th turn produces no advisory"
  else
    fail "499th turn expected no output, got: $output"
  fi

  local turns
  turns="$(read_turns "$sid")"
  if [[ "$turns" -eq 499 ]]; then
    ok "499th turn increments counter to 499"
  else
    fail "expected turns=499, got $turns"
  fi

  clean_session "$sid"
}

# ---------------------------------------------------------------------------
# Test 3: 500 turns → advisory emitted, warned flag set
# ---------------------------------------------------------------------------
test_500_turns_advisory() {
  local sid="${TEST_SESSION}-500"
  clean_session "$sid"
  seed_turns "$sid" 499 "false" "false"

  local result output
  result="$(invoke_hook "$sid")"
  output="$(get_output "$result")"

  if [[ -n "$output" ]]; then
    ok "500th turn produces advisory output"
  else
    fail "500th turn expected advisory output, got nothing"
  fi

  if printf '%s' "$output" | /usr/bin/jq -e '.systemMessage' >/dev/null 2>&1; then
    ok "500th turn advisory has systemMessage field"
  else
    fail "500th turn advisory missing systemMessage field; output was: $output"
  fi

  local warned
  warned="$(read_warned "$sid")"
  if [[ "$warned" == "true" ]]; then
    ok "500th turn sets warned=true"
  else
    fail "500th turn expected warned=true, got $warned"
  fi

  local turns
  turns="$(read_turns "$sid")"
  if [[ "$turns" -eq 500 ]]; then
    ok "500th turn increments counter to 500"
  else
    fail "expected turns=500, got $turns"
  fi

  clean_session "$sid"
}

# ---------------------------------------------------------------------------
# Test 4: 501 turns with warned=true → no repeat advisory
# ---------------------------------------------------------------------------
test_501_no_repeat_advisory() {
  local sid="${TEST_SESSION}-501"
  clean_session "$sid"
  seed_turns "$sid" 500 "true" "false"

  local result output
  result="$(invoke_hook "$sid")"
  output="$(get_output "$result")"

  if [[ -z "$output" ]]; then
    ok "501st turn with warned=true produces no repeat advisory"
  else
    fail "501st turn expected no output (warned already), got: $output"
  fi

  clean_session "$sid"
}

# ---------------------------------------------------------------------------
# Test 5: 749 turns → no second advisory (warnedStrong still false, but below 750)
# ---------------------------------------------------------------------------
test_749_no_strong_advisory() {
  local sid="${TEST_SESSION}-749"
  clean_session "$sid"
  seed_turns "$sid" 748 "true" "false"

  local result output
  result="$(invoke_hook "$sid")"
  output="$(get_output "$result")"

  if [[ -z "$output" ]]; then
    ok "749th turn produces no strong advisory"
  else
    fail "749th turn expected no output, got: $output"
  fi

  clean_session "$sid"
}

# ---------------------------------------------------------------------------
# Test 6: 750 turns → stronger advisory emitted, warnedStrong set
# ---------------------------------------------------------------------------
test_750_strong_advisory() {
  local sid="${TEST_SESSION}-750"
  clean_session "$sid"
  seed_turns "$sid" 749 "true" "false"

  local result output
  result="$(invoke_hook "$sid")"
  output="$(get_output "$result")"

  if [[ -n "$output" ]]; then
    ok "750th turn produces strong advisory output"
  else
    fail "750th turn expected advisory output, got nothing"
  fi

  if printf '%s' "$output" | /usr/bin/jq -e '.systemMessage' >/dev/null 2>&1; then
    ok "750th turn advisory has systemMessage field"
  else
    fail "750th turn advisory missing systemMessage field; output was: $output"
  fi

  local warned_strong
  warned_strong="$(read_warned_strong "$sid")"
  if [[ "$warned_strong" == "true" ]]; then
    ok "750th turn sets warnedStrong=true"
  else
    fail "750th turn expected warnedStrong=true, got $warned_strong"
  fi

  clean_session "$sid"
}

# ---------------------------------------------------------------------------
# Test 7: COPILOT_SESSION_CAP=off → no advisory regardless of count
# ---------------------------------------------------------------------------
test_escape_hatch() {
  local sid="${TEST_SESSION}-cap-off"
  clean_session "$sid"
  seed_turns "$sid" 999 "false" "false"

  local result output exit_code
  result="$(invoke_hook "$sid" "COPILOT_SESSION_CAP=off")"
  exit_code="$(get_exit_code "$result")"
  output="$(get_output "$result")"

  if [[ "$exit_code" -eq 0 ]]; then
    ok "COPILOT_SESSION_CAP=off exits 0"
  else
    fail "COPILOT_SESSION_CAP=off expected exit 0, got $exit_code"
  fi

  if [[ -z "$output" ]]; then
    ok "COPILOT_SESSION_CAP=off produces no advisory at 1000 turns"
  else
    fail "COPILOT_SESSION_CAP=off expected no output, got: $output"
  fi

  clean_session "$sid"
}

# ---------------------------------------------------------------------------
# Test 8: Stale session pruned on write
# ---------------------------------------------------------------------------
test_stale_prune() {
  local sid_stale="${TEST_SESSION}-stale"
  local sid_active="${TEST_SESSION}-active"
  clean_session "$sid_stale"
  clean_session "$sid_active"

  # Inject a stale entry: lastSeen = 73 hours ago
  local stale_ts
  if [[ "$(uname)" == "Darwin" ]]; then
    stale_ts="$(date -u -v-73H +%Y-%m-%dT%H:%M:%SZ)"
  else
    stale_ts="$(date -u -d '73 hours ago' +%Y-%m-%dT%H:%M:%SZ)"
  fi

  local stale_entry
  stale_entry="$(printf '{"turns":100,"firstSeen":"%s","lastSeen":"%s","warned":false,"warnedStrong":false}' \
    "$stale_ts" "$stale_ts")"

  local existing='{}'
  if [[ -f "$STATE_FILE" ]]; then
    existing="$(cat "$STATE_FILE" 2>/dev/null || echo '{}')"
  fi
  local merged
  merged="$(printf '%s' "$existing" | /usr/bin/jq \
    --arg sid "$sid_stale" \
    --argjson e "$stale_entry" \
    '.[$sid] = $e' 2>/dev/null || echo "$existing")"
  printf '%s\n' "$merged" > "$STATE_FILE"

  # Trigger hook for the active session (this causes prune on write)
  invoke_hook "$sid_active" >/dev/null 2>&1 || true

  # Check stale session was pruned
  if [[ -f "$STATE_FILE" ]]; then
    local stale_remains
    stale_remains="$(/usr/bin/jq --arg sid "$sid_stale" 'has($sid)' "$STATE_FILE" 2>/dev/null || echo "true")"
    if [[ "$stale_remains" == "false" ]]; then
      ok "stale session (73h old) pruned from state file"
    else
      fail "stale session still present in state file after prune"
    fi
  else
    ok "state file pruned cleanly (no file = no stale entries)"
  fi

  clean_session "$sid_stale"
  clean_session "$sid_active"
}

# ---------------------------------------------------------------------------
# Test 9: Concurrent safety — two simultaneous prompts don't corrupt state
# ---------------------------------------------------------------------------
test_concurrent_safety() {
  local sid="${TEST_SESSION}-concurrent"
  clean_session "$sid"
  seed_turns "$sid" 5 "false" "false"

  # Launch two hook invocations in parallel
  local payload
  payload="$(make_payload "$sid")"
  bash "$HOOK" <<< "$payload" >/dev/null 2>&1 &
  local pid1=$!
  bash "$HOOK" <<< "$payload" >/dev/null 2>&1 &
  local pid2=$!
  wait "$pid1" "$pid2"

  # After two concurrent invocations starting at 5, turns should be 7
  local turns
  turns="$(read_turns "$sid")"
  if [[ "$turns" -eq 7 ]]; then
    ok "concurrent invocations both counted (turns=7)"
  else
    # Accept 6 or 7: lock contention exit-0 may drop one
    if [[ "$turns" -eq 6 ]]; then
      ok "concurrent invocations: one counted (turns=6, lock contention expected)"
    else
      fail "concurrent invocations: expected turns=6 or 7, got $turns"
    fi
  fi

  # Verify state file is valid JSON
  if /usr/bin/jq '.' "$STATE_FILE" >/dev/null 2>&1; then
    ok "state file is valid JSON after concurrent writes"
  else
    fail "state file corrupted by concurrent writes"
  fi

  clean_session "$sid"
}

# ---------------------------------------------------------------------------
# Test 10: Empty payload exits cleanly
# ---------------------------------------------------------------------------
test_empty_payload() {
  local exit_code=0
  bash "$HOOK" <<< "" >/dev/null 2>&1 || exit_code=$?
  if [[ "$exit_code" -eq 0 ]]; then
    ok "empty payload exits 0"
  else
    fail "empty payload expected exit 0, got $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 11: Missing session_id exits cleanly
# ---------------------------------------------------------------------------
test_missing_session_id() {
  local exit_code=0
  bash "$HOOK" <<< '{"prompt":"hello"}' >/dev/null 2>&1 || exit_code=$?
  if [[ "$exit_code" -eq 0 ]]; then
    ok "missing session_id exits 0"
  else
    fail "missing session_id expected exit 0, got $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------
echo ""
echo "=== user-prompt-submit.sh tests ==="
echo ""

test_new_session
echo ""
test_499_turns_no_advisory
echo ""
test_500_turns_advisory
echo ""
test_501_no_repeat_advisory
echo ""
test_749_no_strong_advisory
echo ""
test_750_strong_advisory
echo ""
test_escape_hatch
echo ""
test_stale_prune
echo ""
test_concurrent_safety
echo ""
test_empty_payload
echo ""
test_missing_session_id
echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="
echo ""

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
