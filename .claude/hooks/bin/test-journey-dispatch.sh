#!/usr/bin/env bash
# Focused hermetic integration tests for rule_journey_dispatch.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"
HOOK="${SCRIPT_DIR}/../pretool-check.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/cc-journey-hook.XXXXXX")"
STATE_DIR="${TEST_ROOT}/state"
FAKE_BIN="${TEST_ROOT}/bin"
FAKE_LOG="${TEST_ROOT}/cc.log"
mkdir -p "$STATE_DIR" "$FAKE_BIN"

cleanup() {
  rm -rf "$TEST_ROOT"
}
trap cleanup EXIT

cat > "${FAKE_BIN}/cc" <<'FAKE_CC'
#!/usr/bin/env bash
set -uo pipefail
printf '%s\n' "$*" >> "${FAKE_CC_LOG}"

expected=(journey verify-dispatch --session)
[[ "${1:-}" == "${expected[0]}" && "${2:-}" == "${expected[1]}" && "${3:-}" == "${expected[2]}" ]] || exit 64
session="${4:-}"
[[ "${5:-}" == "--subagent" && "${7:-}" == "--marker" && "${9:-}" == "--prompt-sha256" && "${11:-}" == "--knowledge-sha256" && "${13:-}" == "--json" ]] || exit 64
subagent="${6:-}"
marker="${8:-}"
prompt_sha="${10:-}"
knowledge_sha="${12:-}"
printf 'session=%s subagent=%s marker=%s prompt=%s knowledge=%s\n' "$session" "$subagent" "$marker" "$prompt_sha" "$knowledge_sha" >> "${FAKE_CC_LOG}"

case "${FAKE_CC_MODE:-no_active}" in
  no_active)
    printf '%s\n' '{"schema_version":"2.1","state":"no_active"}'
    ;;
  authorize)
    if [[ "$marker" =~ ^[0-9a-f]{48}$ && "$prompt_sha" =~ ^[0-9a-f]{64}$ && "$knowledge_sha" =~ ^[0-9a-f]{64}$ ]]; then
      printf '%s\n' '{"schema_version":"2.1","state":"dispatch_authorized","run_id":"run-test","stage_index":0,"dispatch_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
    else
      printf '%s\n' '{"schema_version":"2.1","state":"denied","reason":"missing-marker","recovery_command":"cc journey inspect --run run-test --json"}'
      exit 2
    fi
    ;;
  active)
    printf '%s\n' '{"schema_version":"2.1","state":"denied","reason":"missing-marker","recovery_command":"cc journey inspect --run run-test --json"}'
    exit 2
    ;;
  replay)
    printf '%s\n' '{"schema_version":"2.1","state":"denied","reason":"marker-replayed","recovery_command":"cc journey inspect --run run-test --json"}'
    exit 2
    ;;
  malformed)
    printf '%s\n' 'not-json'
    exit 1
    ;;
  crash)
    exit 1
    ;;
esac
FAKE_CC
chmod +x "${FAKE_BIN}/cc"

PASS=0
FAIL=0
HOOK_EXIT=0
HOOK_STDOUT=""
HOOK_STDERR=""

invoke_hook() {
  local payload="$1" mode="$2"
  : > "$FAKE_LOG"
  HOOK_STDOUT="$(printf '%s' "$payload" | \
    PATH="${FAKE_BIN}:${PATH}" \
    FAKE_CC_LOG="$FAKE_LOG" FAKE_CC_MODE="$mode" \
    COPILOT_HOOK_STATE_DIR="$STATE_DIR" \
    COPILOT_FORCE_DELEGATE=off COPILOT_QA_GATE=off COPILOT_EXTENSIONS_GATE=off \
    bash "$HOOK" 2>"${TEST_ROOT}/stderr")"
  HOOK_EXIT=$?
  HOOK_STDERR="$(cat "${TEST_ROOT}/stderr" 2>/dev/null || true)"
}

assert_exit() {
  local name="$1" expected="$2"
  if [[ "$HOOK_EXIT" -eq "$expected" ]]; then
    printf '  PASS: %s\n' "$name"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s (exit=%s, want=%s; stdout=%s; stderr=%s)\n' "$name" "$HOOK_EXIT" "$expected" "$HOOK_STDOUT" "$HOOK_STDERR"
    FAIL=$((FAIL + 1))
  fi
}

assert_log() {
  local name="$1" pattern="$2"
  if grep -Eq -- "$pattern" "$FAKE_LOG" 2>/dev/null; then
    printf '  PASS: %s\n' "$name"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s (log=%s)\n' "$name" "$(cat "$FAKE_LOG")"
    FAIL=$((FAIL + 1))
  fi
}

assert_log_empty() {
  local name="$1"
  if [[ ! -s "$FAKE_LOG" ]]; then
    printf '  PASS: %s\n' "$name"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s (log=%s)\n' "$name" "$(cat "$FAKE_LOG")"
    FAIL=$((FAIL + 1))
  fi
}

agent_payload() {
  local session="$1" subagent="$2" prompt="$3" agent_type="${4:-}"
  /usr/bin/jq -cn --arg sid "$session" --arg sub "$subagent" --arg prompt "$prompt" --arg at "$agent_type" \
    '{session_id:$sid,tool_name:"Agent",agent_type:$at,tool_input:{subagent_type:$sub,prompt:$prompt}}'
}

MARKER="0123456789abcdef0123456789abcdef0123456789abcdef"
VALID_PROMPT="CC-JOURNEY-INVOCATION: ${MARKER}
CC-JOURNEY-KNOWLEDGE-BEGIN
exact knowledge bytes
CC-JOURNEY-KNOWLEDGE-END
Task: TASK-296"

printf '\n=== journey dispatch hook ===\n'

invoke_hook "$(agent_payload legacy me 'Task: ordinary direct work')" no_active
assert_exit "no active journey leaves legacy framework dispatch unchanged" 0
assert_log "markerless lookup uses the exact verifier command" '^journey verify-dispatch --session legacy --subagent me --marker  --prompt-sha256 [0-9a-f]{64} --knowledge-sha256  --json$'

HOOK_STDOUT="$(printf '%s' "$(agent_payload unavailable me 'Task: markerless but authority missing')" | \
  COPILOT_CC_BIN="${TEST_ROOT}/missing-cc" \
  COPILOT_HOOK_STATE_DIR="$STATE_DIR" \
  COPILOT_FORCE_DELEGATE=off COPILOT_QA_GATE=off COPILOT_EXTENSIONS_GATE=off \
  bash "$HOOK" 2>"${TEST_ROOT}/stderr")"
HOOK_EXIT=$?
HOOK_STDERR="$(cat "${TEST_ROOT}/stderr" 2>/dev/null || true)"
assert_exit "missing verifier denies markerless framework dispatch" 2

invoke_hook "$(agent_payload active me 'Task: missing journey envelope')" active
assert_exit "active journey denies missing marker" 2

# A stalled optional force-delegate streak lock must skip only streak
# bookkeeping. It must never exit the dispatcher before journey verification.
mkdir "${STATE_DIR}/streak-lock-bypass.lock"
: > "$FAKE_LOG"
HOOK_STDOUT="$(printf '%s' "$(agent_payload lock-bypass me 'Task: missing journey envelope')" | \
  PATH="${FAKE_BIN}:${PATH}" FAKE_CC_LOG="$FAKE_LOG" FAKE_CC_MODE=active \
  COPILOT_HOOK_STATE_DIR="$STATE_DIR" COPILOT_QA_GATE=off COPILOT_EXTENSIONS_GATE=off \
  bash "$HOOK" 2>"${TEST_ROOT}/stderr")"
HOOK_EXIT=$?
HOOK_STDERR="$(cat "${TEST_ROOT}/stderr" 2>/dev/null || true)"
assert_exit "stalled streak lock cannot bypass journey verification" 2
assert_log "stalled streak lock still invokes journey verifier" '^journey verify-dispatch --session lock-bypass '
rmdir "${STATE_DIR}/streak-lock-bypass.lock"

invoke_hook "$(agent_payload valid me "$VALID_PROMPT")" authorize
assert_exit "matching structural envelope is authorized" 0
assert_log "valid envelope passes marker and both digests" "marker=${MARKER} prompt=[0-9a-f]{64} knowledge=[0-9a-f]{64}"

ALTERED_PROMPT="${VALID_PROMPT/exact knowledge bytes/altered knowledge bytes}"
invoke_hook "$(agent_payload altered me "$ALTERED_PROMPT")" replay
assert_exit "runtime denial of altered prepared bytes fails closed" 2

DUPLICATE_PROMPT="${VALID_PROMPT}
CC-JOURNEY-INVOCATION: ${MARKER}"
invoke_hook "$(agent_payload duplicate me "$DUPLICATE_PROMPT")" active
assert_exit "duplicate marker is structurally rejected" 2
assert_log "malformed envelope performs non-consuming active lookup" 'marker= prompt=[0-9a-f]{64} knowledge='$

invoke_hook "$(agent_payload replay me "$VALID_PROMPT")" replay
assert_exit "replayed marker is denied" 2

invoke_hook "$(agent_payload nested me "$VALID_PROMPT" qa)" authorize
assert_exit "nested subagent traffic is ignored" 0
assert_log_empty "nested subagent traffic never reaches journey verifier"

invoke_hook "$(agent_payload generic general-purpose 'Task: generic')" active
assert_exit "generic Agent traffic is not framework journey traffic" 0
assert_log_empty "generic Agent traffic never reaches journey verifier"

invoke_hook "$(agent_payload broken me "$VALID_PROMPT")" malformed
assert_exit "malformed verifier response fails closed" 2

invoke_hook "$(agent_payload crashed me "$VALID_PROMPT")" crash
assert_exit "verifier failure fails closed" 2

# QA must run before journey verification. A pending QA task denies @agent-me,
# and the fake verifier log proves the later rule was never reached.
cat > "${STATE_DIR}/qa-gate.json" <<JSON
{"qa-order":{"pending_tasks":["TASK-296"],"retries":{},"history":[],"lastSeen":"2099-01-01T00:00:00Z"}}
JSON
: > "$FAKE_LOG"
HOOK_STDOUT="$(printf '%s' "$(agent_payload qa-order me "$VALID_PROMPT")" | \
  PATH="${FAKE_BIN}:${PATH}" FAKE_CC_LOG="$FAKE_LOG" FAKE_CC_MODE=authorize \
  COPILOT_HOOK_STATE_DIR="$STATE_DIR" COPILOT_FORCE_DELEGATE=off COPILOT_EXTENSIONS_GATE=off \
  bash "$HOOK" 2>"${TEST_ROOT}/stderr")"
HOOK_EXIT=$?
assert_exit "QA gate denies before journey verification" 2
assert_log_empty "QA gate short-circuits verifier invocation"

printf '\nResults: %s passed, %s failed\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
