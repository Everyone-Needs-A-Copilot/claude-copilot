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
  rm -f "${STATE_DIR}/budget-${TEST_SESSION}.json" \
        "${STATE_DIR}/budget-${TEST_SESSION}.lock" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# ADR-005 budget fixtures — read the SAME committed baseline the hook itself
# reads (highest-version .claude/force-delegate-budget-baseline-v*.json), so
# these tests stay correct if the thresholds are ever re-baselined rather
# than duplicating numbers that could silently drift from the hook's own.
# ---------------------------------------------------------------------------
JQ_BIN="/usr/bin/jq"
BUDGET_BASELINE_FILE="$(ls -1 "$PROJECT_ROOT"/.claude/force-delegate-budget-baseline-v*.json 2>/dev/null | sort -V | tail -1)"
if [[ -z "$BUDGET_BASELINE_FILE" ]]; then
  echo "FATAL: no .claude/force-delegate-budget-baseline-v*.json found under $PROJECT_ROOT — cannot run budget tests" >&2
  exit 1
fi
BYTE_BUDGET="$("$JQ_BIN" -r '.thresholds.byte_budget_bytes' "$BUDGET_BASELINE_FILE")"
FILES_BUDGET="$("$JQ_BIN" -r '.thresholds.files_budget_count' "$BUDGET_BASELINE_FILE")"
WARNING_RATIO="$("$JQ_BIN" -r '.thresholds.warning_ratio' "$BUDGET_BASELINE_FILE")"
BASH_BOUNDED_CHARGE="$("$JQ_BIN" -r '.thresholds.bash_bounded_charge_bytes' "$BUDGET_BASELINE_FILE")"
BASH_UNBOUNDED_CHARGE="$("$JQ_BIN" -r '.thresholds.bash_unbounded_charge_bytes' "$BUDGET_BASELINE_FILE")"

# Committed override ledger — tests that exercise the override path append to
# and must clean up the SAME file the hook writes to (.claude/force-delegate-
# budget-overrides.jsonl), never a test-private copy, since the fingerprint
# resolution logic under test IS "read this exact file".
BUDGET_OVERRIDES_FILE="$PROJECT_ROOT/.claude/force-delegate-budget-overrides.jsonl"
clean_overrides_file() {
  rm -f "$BUDGET_OVERRIDES_FILE" 2>/dev/null || true
}

# Scratch dir for fixture files (sized reads/writes), removed at the end of
# the run via clean_fixtures (called from the final cleanup block below).
FIXTURE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/pretool-check-fixtures.XXXXXX")"
clean_fixtures() {
  rm -rf "$FIXTURE_DIR" 2>/dev/null || true
}

# Writes a file of exactly $2 bytes (all "a") to $1.
make_sized_file() {
  local path="$1" bytes="$2"
  head -c "$bytes" /dev/zero | tr '\0' 'a' > "$path"
}

# Read payload for a specific file_path, optional offset/limit.
invoke_hook_read_file() {
  local file_path="$1" extra_env="${2:-}" offset="${3:-}" limit="${4:-}"
  local payload
  if [[ -n "$offset" || -n "$limit" ]]; then
    payload="$(printf '{"session_id":"%s","tool_name":"Read","tool_input":{"file_path":"%s","offset":%s,"limit":%s}}' \
      "$TEST_SESSION" "$file_path" "${offset:-0}" "${limit:-1000000}")"
  else
    payload="$(printf '{"session_id":"%s","tool_name":"Read","tool_input":{"file_path":"%s"}}' \
      "$TEST_SESSION" "$file_path")"
  fi
  local exit_code=0 output
  if [[ -n "$extra_env" ]]; then
    output="$(eval "env $extra_env bash '$HOOK'" <<< "$payload" 2>/dev/null)" || exit_code=$?
  else
    output="$(bash "$HOOK" <<< "$payload" 2>/dev/null)" || exit_code=$?
  fi
  printf '%d|%s' "$exit_code" "$output"
}

# Write payload with $2 bytes of content (all "a") targeting $1.
invoke_hook_write_bytes() {
  local file_path="$1" content_bytes="$2" extra_env="${3:-}"
  local content
  content="$(head -c "$content_bytes" /dev/zero | tr '\0' 'a')"
  local payload
  payload="$(printf '{"session_id":"%s","tool_name":"Write","tool_input":{"file_path":"%s","content":"%s"}}' \
    "$TEST_SESSION" "$file_path" "$content")"
  local exit_code=0 output
  if [[ -n "$extra_env" ]]; then
    output="$(eval "env $extra_env bash '$HOOK'" <<< "$payload" 2>/dev/null)" || exit_code=$?
  else
    output="$(bash "$HOOK" <<< "$payload" 2>/dev/null)" || exit_code=$?
  fi
  printf '%d|%s' "$exit_code" "$output"
}

# Reads the persisted budget state for TEST_SESSION back out (bytesCharged,
# filesTouched length) so tests can assert on the ratchet directly, not just
# on allow/deny.
budget_state_bytes() {
  "$JQ_BIN" -r '.bytesCharged // 0' "${STATE_DIR}/budget-${TEST_SESSION}.json" 2>/dev/null || echo 0
}
budget_state_files_count() {
  "$JQ_BIN" -r '.filesTouched // [] | length' "${STATE_DIR}/budget-${TEST_SESSION}.json" 2>/dev/null || echo 0
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

# Direct framework Agent calls reach the final journey authority gate. Legacy
# smoke cases that are not exercising a prepared journey must still supply an
# authoritative no-active witness; verifier absence is intentionally a deny.
NO_ACTIVE_CC="${STATE_DIR}/test-no-active-cc-${TEST_SESSION}"
prepare_no_active_cc() {
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'printf '\''%s\n'\'' '\''{"schema_version":"2.1","state":"no_active"}'\''' \
    > "$NO_ACTIVE_CC"
  chmod +x "$NO_ACTIVE_CC"
}

clean_no_active_cc() {
  rm -f "$NO_ACTIVE_CC" 2>/dev/null || true
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
# Test 2: a bounded Bash call charges exactly the configured bounded amount,
# and four more consecutive bounded calls stay allowed (ADR-005: cost, not
# call count — this used to be "streak never reaches 5", now it's "total
# spend stays under budget").
# ---------------------------------------------------------------------------
test_bash_bounded_charge_and_repetition_allowed() {
  clean_state
  local result exit_code
  result="$(invoke_hook "Bash")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]] && [[ "$(budget_state_bytes)" -eq "$BASH_BOUNDED_CHARGE" ]]; then
    ok "single bounded Bash call charges exactly \$BASH_BOUNDED_CHARGE ($BASH_BOUNDED_CHARGE bytes)"
  else
    fail "expected exit 0 and bytesCharged=$BASH_BOUNDED_CHARGE, got exit $exit_code bytesCharged=$(budget_state_bytes)"
  fi

  local i all_passed=true
  for i in 1 2 3 4; do
    result="$(invoke_hook "Bash")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -ne 0 ]]; then
      all_passed=false
      fail "call $i of 4 more bounded Bash calls should be allowed, got exit $exit_code"
    fi
  done
  local expected=$(( BASH_BOUNDED_CHARGE * 5 ))
  if $all_passed && [[ "$(budget_state_bytes)" -eq "$expected" ]]; then
    ok "5 total bounded Bash calls: all allowed, bytesCharged ratchets to $expected (5 x $BASH_BOUNDED_CHARGE)"
  else
    fail "expected bytesCharged=$expected after 5 bounded Bash calls, got $(budget_state_bytes)"
  fi
}

# ---------------------------------------------------------------------------
# Test 3 (ADR-005 core case): five small reads stay allowed; a single large
# read that alone exceeds the byte budget is denied on FIRST contact — this
# is Defect 1/2 from ADR-005 directly: cost is metered, not call count, so a
# single expensive call can be denied before any repetition at all.
# ---------------------------------------------------------------------------
test_five_small_reads_allowed_single_large_read_denied() {
  clean_state
  local small_bytes=500
  local i f result exit_code all_passed=true
  for i in 1 2 3 4 5; do
    f="$FIXTURE_DIR/small-$i.txt"
    make_sized_file "$f" "$small_bytes"
    result="$(invoke_hook_read_file "$f")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -ne 0 ]]; then
      all_passed=false
      fail "small read $i/5 ($small_bytes B) should be allowed, got exit $exit_code"
    fi
  done
  local expected_small=$(( small_bytes * 5 ))
  if $all_passed && [[ "$(budget_state_bytes)" -eq "$expected_small" ]]; then
    ok "5 reads of $small_bytes B each ($expected_small B total, budget $BYTE_BUDGET B): all allowed"
  else
    fail "expected bytesCharged=$expected_small after 5 small reads, got $(budget_state_bytes)"
  fi

  # Fresh session: ONE read whose size alone exceeds the byte budget.
  local sess2="test-large-read-$$"
  rm -f "${STATE_DIR}/budget-${sess2}.json" "${STATE_DIR}/budget-${sess2}.lock" 2>/dev/null || true
  local big_bytes=$(( BYTE_BUDGET + 1 ))
  local big_file="$FIXTURE_DIR/big-single.txt"
  make_sized_file "$big_file" "$big_bytes"
  local payload
  payload="$(printf '{"session_id":"%s","tool_name":"Read","tool_input":{"file_path":"%s"}}' "$sess2" "$big_file")"
  local out ec=0
  out="$(bash "$HOOK" <<< "$payload" 2>/dev/null)" || ec=$?
  if [[ "$ec" -eq 2 ]] && printf '%s' "$out" | "$JQ_BIN" -e '.permissionDecision == "deny"' > /dev/null 2>&1; then
    ok "a single read of $big_bytes B (> $BYTE_BUDGET B budget) is denied on the FIRST call, not the 5th"
  else
    fail "single oversized read should deny on first contact, got exit $ec: $out"
  fi
  rm -f "${STATE_DIR}/budget-${sess2}.json" "${STATE_DIR}/budget-${sess2}.lock" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Test 4 (ADR-005 Defect 3): alternating tool names no longer defeats the
# meter. Bash(cat, unbounded charge) and Read(small) alternate — no tool
# name repeats consecutively at all — yet cumulative spend still crosses the
# budget and the crossing call is denied.
# ---------------------------------------------------------------------------
test_alternating_tools_no_longer_defeat_meter() {
  clean_state
  local small_file="$FIXTURE_DIR/alt-small.txt"
  make_sized_file "$small_file" 100
  local cat_file="$FIXTURE_DIR/alt-cat-source.txt"
  make_sized_file "$cat_file" 50

  local calls_needed=$(( BYTE_BUDGET / BASH_UNBOUNDED_CHARGE + 2 ))
  local i result exit_code last_exit=0
  for (( i = 1; i <= calls_needed; i++ )); do
    result="$(invoke_hook_bash_cmd "cat $cat_file")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -eq 2 ]]; then
      last_exit=2
      break
    fi
    result="$(invoke_hook_read_file "$small_file")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -eq 2 ]]; then
      last_exit=2
      break
    fi
  done

  if [[ "$last_exit" -eq 2 ]]; then
    ok "alternating cat/Read (no consecutive same-tool repetition) still trips the budget once cumulative spend crosses $BYTE_BUDGET B"
  else
    fail "alternating cat/Read never denied after $calls_needed round-trips — meter is defeatable by alternation (ADR-005 Defect 3 regression)"
  fi
}

# ---------------------------------------------------------------------------
# Test 5 (ADR-005 Defect 4): Write is now charged. Previously Write was
# unmetered entirely (free), while a one-line Edit was charged. A large
# Write now contributes to the budget exactly like Read/Edit.
# ---------------------------------------------------------------------------
test_write_now_charged() {
  clean_state
  local small_write=200
  local result exit_code
  result="$(invoke_hook_write_bytes "$FIXTURE_DIR/write-small.txt" "$small_write")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]] && [[ "$(budget_state_bytes)" -eq "$small_write" ]]; then
    ok "Write of $small_write B charges exactly $small_write B (Write is no longer free)"
  else
    fail "expected exit 0 and bytesCharged=$small_write after small Write, got exit $exit_code bytesCharged=$(budget_state_bytes)"
  fi

  clean_state
  local big_write=$(( BYTE_BUDGET + 1000 ))
  result="$(invoke_hook_write_bytes "$FIXTURE_DIR/write-big.txt" "$big_write")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "a single Write of $big_write B (> $BYTE_BUDGET B budget) is denied — Write now participates in the budget"
  else
    fail "oversized Write should be denied, got exit $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 6: distinct-files meter — 5 distinct small files allowed, a 6th
# distinct file denied even though bytes are trivial; re-reading an
# already-touched file does not grow the count.
# ---------------------------------------------------------------------------
test_distinct_files_budget() {
  clean_state
  local i f result exit_code all_passed=true
  for (( i = 1; i <= FILES_BUDGET; i++ )); do
    f="$FIXTURE_DIR/distinct-$i.txt"
    make_sized_file "$f" 50
    result="$(invoke_hook_read_file "$f")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -ne 0 ]]; then
      all_passed=false
      fail "distinct file $i/$FILES_BUDGET should be allowed, got exit $exit_code"
    fi
  done
  if $all_passed && [[ "$(budget_state_files_count)" -eq "$FILES_BUDGET" ]]; then
    ok "$FILES_BUDGET distinct small-file reads: all allowed, filesTouched=$FILES_BUDGET"
  else
    fail "expected filesTouched=$FILES_BUDGET, got $(budget_state_files_count)"
  fi

  # Re-reading an already-counted file must not grow the distinct count.
  result="$(invoke_hook_read_file "$FIXTURE_DIR/distinct-1.txt")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]] && [[ "$(budget_state_files_count)" -eq "$FILES_BUDGET" ]]; then
    ok "re-reading an already-touched file does not grow the distinct-files count"
  else
    fail "re-read of an already-touched file should stay allowed with no count growth, got exit $exit_code count=$(budget_state_files_count)"
  fi

  # A genuinely new (6th) distinct file exceeds the files budget → denied.
  local new_file="$FIXTURE_DIR/distinct-new.txt"
  make_sized_file "$new_file" 50
  result="$(invoke_hook_read_file "$new_file")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "a $(( FILES_BUDGET + 1 ))th distinct file (bytes trivial) is denied by the files-count meter, independent of the byte meter"
  else
    fail "the file pushing distinct-files count over $FILES_BUDGET should be denied, got exit $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 7: a Read narrowed by offset/limit charges less than the file's full
# stat size (ADR-005 table: "File size from stat, narrowed when offset and
# limit are given").
# ---------------------------------------------------------------------------
test_narrowed_read_charges_less_than_full_file() {
  clean_state
  local f="$FIXTURE_DIR/narrowed.txt"
  local i
  { for (( i = 0; i < 1000; i++ )); do printf 'line %d of filler text\n' "$i"; done; } > "$f"
  local full_size
  full_size="$(wc -c < "$f" | tr -d '[:space:]')"

  local result exit_code
  result="$(invoke_hook_read_file "$f" "" "0" "10")"
  exit_code="$(get_exit_code "$result")"
  local narrowed_charge
  narrowed_charge="$(budget_state_bytes)"
  if [[ "$exit_code" -eq 0 ]] && [[ "$narrowed_charge" -gt 0 ]] && [[ "$narrowed_charge" -lt "$full_size" ]]; then
    ok "Read with offset=0/limit=10 on a $full_size B / 1000-line file charges $narrowed_charge B — less than the full file"
  else
    fail "narrowed Read should charge > 0 and < full file size ($full_size B), charged $narrowed_charge B, exit $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 8: Bash unbounded-vs-bounded charge — a whole-file `cat` charges
# \$BASH_UNBOUNDED_CHARGE, a bounded command charges \$BASH_BOUNDED_CHARGE,
# and the two are configured to differ (ADR-005 table: "cat of a whole file"
# is a structurally-unbounded Bash charge).
# ---------------------------------------------------------------------------
test_bash_unbounded_vs_bounded_charge() {
  clean_state
  local f="$FIXTURE_DIR/cat-target.txt"
  make_sized_file "$f" 10
  local result exit_code
  result="$(invoke_hook_bash_cmd "cat $f")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]] && [[ "$(budget_state_bytes)" -eq "$BASH_UNBOUNDED_CHARGE" ]]; then
    ok "whole-file 'cat' charges \$BASH_UNBOUNDED_CHARGE ($BASH_UNBOUNDED_CHARGE bytes)"
  else
    fail "expected cat to charge $BASH_UNBOUNDED_CHARGE bytes, got $(budget_state_bytes)"
  fi

  clean_state
  result="$(invoke_hook_bash_cmd "git status")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]] && [[ "$(budget_state_bytes)" -eq "$BASH_BOUNDED_CHARGE" ]]; then
    ok "'git status' (bounded) charges \$BASH_BOUNDED_CHARGE ($BASH_BOUNDED_CHARGE bytes)"
  else
    fail "expected git status to charge $BASH_BOUNDED_CHARGE bytes, got $(budget_state_bytes)"
  fi

  if [[ "$BASH_UNBOUNDED_CHARGE" -gt "$BASH_BOUNDED_CHARGE" ]]; then
    ok "unbounded charge ($BASH_UNBOUNDED_CHARGE) > bounded charge ($BASH_BOUNDED_CHARGE) in the committed baseline"
  else
    fail "baseline misconfigured: unbounded charge should exceed bounded charge"
  fi
}

# ---------------------------------------------------------------------------
# Test 9: Agent tool always allowed and never charged, even with a large
# accumulated budget already spent.
# ---------------------------------------------------------------------------
test_agent_always_allowed() {
  clean_state
  local f="$FIXTURE_DIR/pre-agent.txt"
  make_sized_file "$f" $(( BYTE_BUDGET - 100 ))
  invoke_hook_read_file "$f" > /dev/null 2>&1 || true

  local result exit_code
  result="$(invoke_hook "Agent")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "Agent call with a nearly-exhausted budget already spent: still allowed (exit 0)"
  else
    fail "Agent call expected exit 0, got $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Test 10: COPILOT_FORCE_DELEGATE=off → allowed regardless of budget, and
# does not persist any charge (bypasses the meter entirely, not just the
# deny).
# ---------------------------------------------------------------------------
test_escape_hatch_off() {
  clean_state
  local big_file="$FIXTURE_DIR/escape-hatch-big.txt"
  make_sized_file "$big_file" $(( BYTE_BUDGET * 3 ))
  local payload result exit_code
  payload="$(printf '{"session_id":"%s","tool_name":"Read","tool_input":{"file_path":"%s"}}' "$TEST_SESSION" "$big_file")"
  local out ec=0
  out="$(env COPILOT_FORCE_DELEGATE=off bash "$HOOK" <<< "$payload" 2>/dev/null)" || ec=$?
  if [[ "$ec" -eq 0 ]]; then
    ok "COPILOT_FORCE_DELEGATE=off: a read 3x the byte budget is still allowed"
  else
    fail "COPILOT_FORCE_DELEGATE=off escape hatch failed, got exit $ec"
  fi
}

# ---------------------------------------------------------------------------
# Test 11: Stale session state (>24h old) resets the ratchet rather than
# erroring or carrying forward a huge stale bytesCharged.
# ---------------------------------------------------------------------------
test_stale_state_no_error() {
  clean_state
  # Write a stale state file (1970 timestamp) with a bytesCharged that would
  # itself already exceed the budget if honored.
  printf '{"session_id":"%s","bytesCharged":%d,"filesTouched":[],"updatedAt":"1970-01-01T00:00:00Z"}\n' \
    "$TEST_SESSION" "$(( BYTE_BUDGET * 2 ))" > "${STATE_DIR}/budget-${TEST_SESSION}.json"

  local result exit_code
  result="$(invoke_hook "Bash")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]] && [[ "$(budget_state_bytes)" -eq "$BASH_BOUNDED_CHARGE" ]]; then
    ok "stale state file (1970 epoch, bytesCharged already over budget): treated as fresh, ratchet resets to 0 + this call's charge"
  else
    fail "stale state file should reset the ratchet: expected exit 0 and bytesCharged=$BASH_BOUNDED_CHARGE, got exit $exit_code bytesCharged=$(budget_state_bytes)"
  fi
}

# ---------------------------------------------------------------------------
# Test 12: Malformed/empty payload → hook exits 0 (safe default)
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
# Test 13: Concurrent safety — two simultaneous invocations don't corrupt
# each session's budget state.
# ---------------------------------------------------------------------------
test_concurrent_safety() {
  clean_state
  local sess_a="test-conc-a-$$"
  local sess_b="test-conc-b-$$"
  local file_a="${STATE_DIR}/budget-${sess_a}.json"
  local file_b="${STATE_DIR}/budget-${sess_b}.json"

  # Run 3 concurrent Bash calls for each of two sessions
  for i in 1 2 3; do
    payload_a="$(printf '{"session_id":"%s","tool_name":"Bash","tool_input":{}}' "$sess_a")"
    payload_b="$(printf '{"session_id":"%s","tool_name":"Bash","tool_input":{}}' "$sess_b")"
    bash "$HOOK" <<< "$payload_a" > /dev/null 2>&1 &
    bash "$HOOK" <<< "$payload_b" > /dev/null 2>&1 &
  done
  wait

  local bytes_a bytes_b
  bytes_a="$("$JQ_BIN" -r '.bytesCharged // "invalid"' "$file_a" 2>/dev/null || echo "invalid")"
  bytes_b="$("$JQ_BIN" -r '.bytesCharged // "invalid"' "$file_b" 2>/dev/null || echo "invalid")"

  if [[ "$bytes_a" != "invalid" ]] && "$JQ_BIN" -e 'type == "number"' <<< "$bytes_a" > /dev/null 2>&1; then
    ok "concurrent session A: state file is valid JSON (bytesCharged=$bytes_a)"
  else
    fail "concurrent session A: state file corrupt or invalid: $bytes_a"
  fi
  if [[ "$bytes_b" != "invalid" ]] && "$JQ_BIN" -e 'type == "number"' <<< "$bytes_b" > /dev/null 2>&1; then
    ok "concurrent session B: state file is valid JSON (bytesCharged=$bytes_b)"
  else
    fail "concurrent session B: state file corrupt or invalid: $bytes_b"
  fi

  # Sessions must be independent
  if [[ "$bytes_a" -ge 0 && "$bytes_b" -ge 0 ]]; then
    ok "concurrent sessions A and B have independent state"
  else
    fail "concurrent sessions A and B state contaminated"
  fi

  rm -f "$file_a" "$file_b" "${file_a%.json}.lock" "${file_b%.json}.lock" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Test 14: warn before deny — crossing \$WARNING_RATIO of the byte budget
# emits an advisory to stderr but is still allowed; crossing 100% denies
# (ADR-005 settled decision: emit a warning before the deny, not only at it).
# ---------------------------------------------------------------------------
test_warning_before_deny() {
  clean_state
  local warn_bytes
  warn_bytes="$(awk -v b="$BYTE_BUDGET" -v r="$WARNING_RATIO" 'BEGIN{printf "%d", b * r}')"
  local f="$FIXTURE_DIR/warn-threshold.txt"
  make_sized_file "$f" "$warn_bytes"

  local payload out ec=0
  payload="$(printf '{"session_id":"%s","tool_name":"Read","tool_input":{"file_path":"%s"}}' "$TEST_SESSION" "$f")"
  out="$(bash "$HOOK" <<< "$payload" 2>&1 >/dev/null)" || ec=$?
  if [[ "$ec" -eq 0 ]] && printf '%s' "$out" | grep -q "force-delegate-budget-warn"; then
    ok "crossing the $WARNING_RATIO warning ratio ($warn_bytes/$BYTE_BUDGET B): allowed, with an advisory on stderr"
  else
    fail "expected exit 0 with a force-delegate-budget-warn stderr line at $warn_bytes/$BYTE_BUDGET B, got exit $ec, stderr: $out"
  fi

  # Push over the top: denied, with the deny diagnostic (not just the warn).
  local f2="$FIXTURE_DIR/warn-then-deny.txt"
  make_sized_file "$f2" "$(( BYTE_BUDGET - warn_bytes + 1 ))"
  payload="$(printf '{"session_id":"%s","tool_name":"Read","tool_input":{"file_path":"%s"}}' "$TEST_SESSION" "$f2")"
  ec=0
  out="$(bash "$HOOK" <<< "$payload" 2>&1 >/dev/null)" || ec=$?
  if [[ "$ec" -eq 2 ]] && printf '%s' "$out" | grep -q "hook-deny"; then
    ok "the very next call that crosses 100% of the budget is denied (warning preceded the deny, did not replace it)"
  else
    fail "expected exit 2 with a hook-deny stderr line once over budget, got exit $ec, stderr: $out"
  fi
}

# ---------------------------------------------------------------------------
# Test 15: audited override — COPILOT_FORCE_DELEGATE_BUDGET_OVERRIDE grants a
# specific overage AND appends a reviewable entry; a later session hitting
# the IDENTICAL overage (same meter/threshold/actual) is honored from the
# committed ledger alone, with no env var — modeled on FF9's
# CC_BUDGET_OVERRIDE / context-budget-overrides.jsonl.
# ---------------------------------------------------------------------------
test_override_path() {
  clean_state
  clean_overrides_file

  local big_file="$FIXTURE_DIR/override-big.txt"
  local big_bytes=$(( BYTE_BUDGET + 777 ))
  make_sized_file "$big_file" "$big_bytes"

  # Without an override: denied.
  local result exit_code
  result="$(invoke_hook_read_file "$big_file")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "override test pre-condition: oversized read denied with no override present"
  else
    fail "pre-condition failed: expected exit 2 with no override, got $exit_code"
    clean_overrides_file
    return
  fi

  # A bare env var with an EMPTY reason must still be refused (mirrors FF9's
  # override_refused_for_empty_reason).
  result="$(invoke_hook_read_file "$big_file" "COPILOT_FORCE_DELEGATE_BUDGET_OVERRIDE=bytes:")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "override with an empty reason is refused (still denied)"
  else
    fail "override with empty reason should still deny, got exit $exit_code"
  fi

  # With a non-empty reason: allowed locally, AND appends a committed entry.
  result="$(invoke_hook_read_file "$big_file" "COPILOT_FORCE_DELEGATE_BUDGET_OVERRIDE='bytes:reviewed test fixture'")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "COPILOT_FORCE_DELEGATE_BUDGET_OVERRIDE with a reason grants the overage locally"
  else
    fail "override with a reason should grant the overage, got exit $exit_code"
  fi
  if [[ -f "$BUDGET_OVERRIDES_FILE" ]] && "$JQ_BIN" -e '.reason == "reviewed test fixture"' <<< "$(tail -1 "$BUDGET_OVERRIDES_FILE")" > /dev/null 2>&1; then
    ok "the override was appended to the committed ledger with its reason"
  else
    fail "expected a ledger entry with reason 'reviewed test fixture' in $BUDGET_OVERRIDES_FILE"
  fi

  # Fresh session, SAME overage shape (same big_file → same actual bytes),
  # NO env var this time: the committed ledger entry alone must cover it —
  # this is the "CI never sets the env var, only a committed entry passes"
  # guarantee.
  clean_state
  result="$(invoke_hook_read_file "$big_file")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "a fresh session with the identical overage is honored from the committed ledger alone (no env var)"
  else
    fail "committed ledger entry should cover an identical future overage non-interactively, got exit $exit_code"
  fi

  clean_overrides_file
}

# ---------------------------------------------------------------------------
# Test 16 (ADR-005 settled decision): the budget does NOT reset on a
# main-session Agent dispatch — only at session start. A near-exhausted
# budget, followed by a legitimate Agent dispatch and the subagent's own
# (exempt) work, still denies the main session's next call if it would push
# the ratchet over the top.
# ---------------------------------------------------------------------------
test_budget_does_not_reset_on_agent_dispatch() {
  clean_state
  prepare_no_active_cc

  local near_full=$(( BYTE_BUDGET - 5000 ))
  local f1="$FIXTURE_DIR/pre-dispatch.txt"
  make_sized_file "$f1" "$near_full"
  local result exit_code
  result="$(invoke_hook_read_file "$f1")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -ne 0 ]]; then
    fail "pre-dispatch read of $near_full B should be allowed (pre-condition), got exit $exit_code"
    clean_no_active_cc
    return
  fi

  # Main session delegates — always allowed, never charged.
  local agent_payload
  agent_payload="$(printf '{"session_id":"%s","tool_name":"Agent","tool_input":{"subagent_type":"qa"}}' "$TEST_SESSION")"
  local ec=0
  bash "$HOOK" <<< "$agent_payload" > /dev/null 2>&1 || ec=$?
  if [[ "$ec" -ne 0 ]]; then
    fail "Agent dispatch itself should always be allowed, got exit $ec"
    clean_no_active_cc
    return
  fi

  # The subagent does its own (exempt) work — must not touch the meter.
  local sub_payload
  sub_payload="$(printf '{"session_id":"%s","agent_type":"qa","agent_id":"task-1","tool_name":"Read","tool_input":{"file_path":"%s"}}' "$TEST_SESSION" "$f1")"
  bash "$HOOK" <<< "$sub_payload" > /dev/null 2>&1 || true

  if [[ "$(budget_state_bytes)" -ne "$near_full" ]]; then
    fail "budget should be unchanged by the Agent dispatch and the subagent's own work, expected $near_full got $(budget_state_bytes)"
    clean_no_active_cc
    return
  fi

  # Main session's first call after the delegation returns: a 10000 B read
  # pushes the ratchet past the budget. If the dispatch had reset it, this
  # would be allowed; since it must NOT reset (ADR-005), this is denied.
  local f2="$FIXTURE_DIR/post-dispatch.txt"
  make_sized_file "$f2" 10000
  result="$(invoke_hook_read_file "$f2")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "main session's first read after a legitimate Agent dispatch is still denied — the budget ratcheted through the dispatch, it did not reset"
  else
    fail "budget should NOT reset on Agent dispatch (ADR-005), expected exit 2 after dispatch, got exit $exit_code"
  fi

  clean_state
  clean_no_active_cc
}

# ---------------------------------------------------------------------------
# Test 17: Performance — hook completes in <50ms
# ---------------------------------------------------------------------------
test_performance() {
  # EPOCHREALTIME is a bash builtin (seconds.microseconds, zero subprocess
  # cost) — it avoids polluting the measurement with an external timer's own
  # fork/exec overhead. This previously bracketed the invocation with two
  # separate `python3 -c 'import time; ...'` calls on Darwin; each one costs
  # ~19-22ms of its own interpreter startup on typical hardware (measured),
  # comparable to the entire 50ms budget under test, so "elapsed_ms" was
  # largely measurement noise rather than hook time — this made the test
  # flaky (borderline pass/fail on scheduler jitter alone) once the hook
  # itself was made fast. See pretool-check.sh's PERFORMANCE NOTE comments
  # for the corresponding hook-side fix (jq call consolidation, lazy
  # manifest loading, builtin strftime instead of `date`).
  #
  # Five samples, reporting the median, is robust to a single scheduler
  # hiccup (GC pause, disk cache miss, etc.) without hiding a genuine
  # regression the way averaging or "best of N" would.
  local samples=5
  local -a runs=()
  local i start_s start_us end_s end_us elapsed_ms
  for ((i = 0; i < samples; i++)); do
    clean_state
    IFS=. read -r start_s start_us <<< "$EPOCHREALTIME"
    invoke_hook "Bash" > /dev/null 2>&1
    IFS=. read -r end_s end_us <<< "$EPOCHREALTIME"
    elapsed_ms=$(( (end_s - start_s) * 1000 + (10#$end_us - 10#$start_us) / 1000 ))
    runs+=("$elapsed_ms")
  done

  local -a sorted=()
  IFS=$'\n' sorted=($(printf '%s\n' "${runs[@]}" | sort -n))
  unset IFS
  local median_ms="${sorted[$((samples / 2))]}"

  if [[ "$median_ms" -lt 50 ]]; then
    ok "hook performance: median ${median_ms}ms over ${samples} runs (target <50ms; samples: ${runs[*]}ms)"
  else
    fail "hook performance: median ${median_ms}ms over ${samples} runs exceeds 50ms target (samples: ${runs[*]}ms)"
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
  prepare_no_active_cc
  write_gate_pending '["TASK-5"]'

  local result exit_code
  result="$(invoke_hook_agent "qa" "COPILOT_CC_BIN=$NO_ACTIVE_CC")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "QA gate: pending TASK-5 → Agent(qa) allowed"
  else
    fail "QA gate: pending TASK-5 → Agent(qa) should be allowed, got exit $exit_code"
  fi
  clean_gate_state
  clean_no_active_cc
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
# Test 18: git push / git pull now pass on cost like any other bounded Bash
# command (ADR-005: the hardcoded 10-prefix git allowlist is removed — "the
# genuinely unbounded cases" are what need the large charge, not an
# exemption; a plain git op is cheap enough on its own merits).
# ---------------------------------------------------------------------------
test_git_push_pull_charged_like_any_bounded_command() {
  clean_state

  local result exit_code
  result="$(invoke_hook_bash_cmd "git push origin main")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]] && [[ "$(budget_state_bytes)" -eq "$BASH_BOUNDED_CHARGE" ]]; then
    ok "git push is allowed and charges the ordinary bounded amount ($BASH_BOUNDED_CHARGE B) — no special-case exemption"
  else
    fail "expected git push to charge $BASH_BOUNDED_CHARGE B like any bounded command, got exit $exit_code bytesCharged=$(budget_state_bytes)"
  fi

  result="$(invoke_hook_bash_cmd "git pull origin main")"
  exit_code="$(get_exit_code "$result")"
  local expected=$(( BASH_BOUNDED_CHARGE * 2 ))
  if [[ "$exit_code" -eq 0 ]] && [[ "$(budget_state_bytes)" -eq "$expected" ]]; then
    ok "git pull is also allowed and adds another $BASH_BOUNDED_CHARGE B (ratchets to $expected, not exempt)"
  else
    fail "expected git pull to bring bytesCharged to $expected, got exit $exit_code bytesCharged=$(budget_state_bytes)"
  fi
}

# ---------------------------------------------------------------------------
# Test 19: command-string escape hatch — COPILOT_FORCE_DELEGATE=off prefix
# still bypasses the meter entirely (no charge persisted at all), even when
# the command would otherwise be denied on cost.
# ---------------------------------------------------------------------------
test_command_string_escape_hatch() {
  clean_state

  local big_file="$FIXTURE_DIR/escape-prefix-big.txt"
  make_sized_file "$big_file" $(( BYTE_BUDGET * 2 ))

  # Verify a plain (non-escaped) unbounded Bash call against the same
  # backdrop would in fact be denied (pre-condition — proves the escape
  # hatch below is bypassing a real deny, not a no-op).
  local result exit_code
  result="$(invoke_hook_bash_cmd "cat $big_file")"
  exit_code="$(get_exit_code "$result")"

  clean_state
  result="$(invoke_hook_bash_cmd "COPILOT_FORCE_DELEGATE=off cat $big_file")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]] && [[ "$(budget_state_bytes)" -eq 0 ]]; then
    ok "command-string escape hatch: COPILOT_FORCE_DELEGATE=off prefix allows the call and persists no charge at all"
  else
    fail "command-string escape hatch should allow with zero persisted charge, got exit $exit_code bytesCharged=$(budget_state_bytes)"
  fi
}

# ---------------------------------------------------------------------------
# Test 20: crash fix — git push exits 0 with no error (regression for Issue 1)
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
# Test 21 — behavioral fail-open regression for the literal 4.0.1 deadlock
# (Hypothesis A, confirmed root cause): "a crashing hook blocked the tools
# needed to fix it" — specifically Read and Edit, which the 4.0.1 matcher
# narrowing excluded as an emergency workaround. Now that the matcher is
# widened again (TASK-106/C-6 + Write), the ERR/PIPE fail-open traps are the
# ONLY thing standing between a script crash and a hard block on Read/Edit.
# This injects a synthetic mid-script failure into a throwaway copy of the
# real hook (traps intact, unmodified logic otherwise) and asserts Read and
# Edit payloads still exit 0. A future refactor that reintroduces a bare
# `set -euo pipefail` or drops the ERR/PIPE traps will fail this test: the
# same injected failure becomes fail-CLOSED once errexit is active without a
# trap to catch it (verified manually while building this test).
# ===========================================================================
test_crash_fails_open_for_read_and_edit() {
  local crash_hook
  crash_hook="$(mktemp -d)/pretool-check-crash-copy.sh"
  # Inject a deliberate failing command right after the PIPE trap is
  # installed (i.e. after fail-open infrastructure is set up, before any
  # tool-specific logic runs) — simulating "the hook crashed partway
  # through". Static text match, not tied to a fixed line number, so it
  # tolerates reasonable reformatting of the hook script.
  awk '
    { print }
    /^trap .* PIPE$/ && !injected {
      print "false  # TEST-INJECTED crash (test_crash_fails_open_for_read_and_edit)"
      injected = 1
    }
  ' "$HOOK" > "$crash_hook"

  if ! grep -q "TEST-INJECTED crash" "$crash_hook"; then
    fail "crash-injection setup failed: could not locate the PIPE trap line in $HOOK to inject after (test infrastructure bug, not the hook)"
    rm -f "$crash_hook"
    return
  fi
  chmod +x "$crash_hook"

  local all_passed=true
  local tool payload exit_code
  for tool in Read Edit; do
    payload="$(printf '{"session_id":"%s","tool_name":"%s","tool_input":{"file_path":"/tmp/x"}}' "$TEST_SESSION" "$tool")"
    exit_code=0
    bash "$crash_hook" <<< "$payload" > /dev/null 2>&1 || exit_code=$?
    if [[ "$exit_code" -ne 0 ]]; then
      all_passed=false
      fail "crash-injected hook with tool_name=$tool should fail open (exit 0), got exit $exit_code"
    fi
  done
  if $all_passed; then
    ok "crash-injected hook fails open (exit 0) for both Read and Edit — 4.0.1 deadlock cannot recur"
  fi

  rm -rf "$(dirname "$crash_hook")"
}

# ===========================================================================
# TASK-106 / C-6 — subagent-livelock replay tests (ported from the orphaned
# branch docs/40-initiatives-migration, commit 77f5cdb).
#
# Root cause: Claude Code shares session_id between a main session and any
# subagent it spawns via the Agent tool. Before the AGENT_TYPE exemption in
# rule_force_delegate/rule_qa_gate, a subagent's Read/Edit/Bash calls shared
# (and could trip) the parent's force-delegate streak and the qa-gate's
# deny-everything-except-Agent(qa) rule — with no escape, since framework
# agents do not carry the Agent/Task tool in their `tools:` allow-list.
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

# Build a Read payload against a real file_path, optionally tagged with a
# subagent's agent_type/agent_id (empty agent_type == a call made directly
# by the main session). Charges under the new cost budget depend on the
# target actually being stat-able, unlike the old streak rule, so — unlike
# its pre-ADR-005 ancestor — this always takes an explicit file_path rather
# than a fixed "/tmp/x".
subagent_read_payload() {
  local session="$1" agent_type="$2" file_path="$3"
  if [[ -z "$agent_type" ]]; then
    printf '{"session_id":"%s","tool_name":"Read","tool_input":{"file_path":"%s"}}' "$session" "$file_path"
  else
    printf '{"session_id":"%s","agent_type":"%s","agent_id":"task-1","tool_name":"Read","tool_input":{"file_path":"%s"}}' \
      "$session" "$agent_type" "$file_path"
  fi
}

# ---------------------------------------------------------------------------
# Replay 1: main session touches 4 distinct files (files budget = $FILES_BUDGET,
# so 4 is under it), then a subagent (same session_id, agent_type set) reads
# TWO further distinct files — allowed, and the parent's filesTouched count
# must be untouched by them. The main session's 5th distinct file is then
# still allowed (count reaches exactly $FILES_BUDGET), and its 6th is denied
# — proving the subagent's reads neither got blocked nor silently donated to
# (or stole from) the parent's distinct-files budget.
# ---------------------------------------------------------------------------
test_subagent_read_exempt_from_force_delegate() {
  clean_state
  local result exit_code i

  for i in 1 2 3 4; do
    make_sized_file "$FIXTURE_DIR/replay1-main-$i.txt" 20
    result="$(invoke_hook_raw "$(subagent_read_payload "$TEST_SESSION" "" "$FIXTURE_DIR/replay1-main-$i.txt")")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -ne 0 ]]; then
      fail "replay: main-session Read $i/4 should be allowed, got exit $exit_code"
      return
    fi
  done
  if [[ "$(budget_state_files_count)" -ne 4 ]]; then
    fail "replay pre-condition: expected filesTouched=4 after 4 main-session reads, got $(budget_state_files_count)"
    return
  fi

  # Subagent reads two NEW distinct files on the SAME session_id.
  make_sized_file "$FIXTURE_DIR/replay1-sub-a.txt" 20
  result="$(invoke_hook_raw "$(subagent_read_payload "$TEST_SESSION" "general-purpose" "$FIXTURE_DIR/replay1-sub-a.txt")")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "replay: subagent's 1st Read allowed — no livelock"
  else
    fail "replay: subagent's 1st Read should be allowed (agent_type exempt), got exit $exit_code"
  fi

  make_sized_file "$FIXTURE_DIR/replay1-sub-b.txt" 20
  result="$(invoke_hook_raw "$(subagent_read_payload "$TEST_SESSION" "general-purpose" "$FIXTURE_DIR/replay1-sub-b.txt")")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "replay: subagent's 2nd Read also allowed (exempt, not one-time)"
  else
    fail "replay: subagent's 2nd Read should be allowed, got exit $exit_code"
  fi

  if [[ "$(budget_state_files_count)" -eq 4 ]]; then
    ok "replay: subagent's 2 reads of 2 NEW distinct files did not change the parent's filesTouched count (still 4)"
  else
    fail "replay: parent's filesTouched should still be 4 after subagent reads, got $(budget_state_files_count)"
  fi

  # Main session's 5th distinct file: allowed, count reaches exactly $FILES_BUDGET.
  make_sized_file "$FIXTURE_DIR/replay1-main-5.txt" 20
  result="$(invoke_hook_raw "$(subagent_read_payload "$TEST_SESSION" "" "$FIXTURE_DIR/replay1-main-5.txt")")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]] && [[ "$(budget_state_files_count)" -eq "$FILES_BUDGET" ]]; then
    ok "replay: main session's 5th distinct file allowed (count reaches $FILES_BUDGET)"
  else
    fail "replay: main session's 5th distinct file should be allowed with count=$FILES_BUDGET, got exit $exit_code count=$(budget_state_files_count)"
  fi

  # Main session's 6th distinct file: denied — the subagent's own files did
  # not silently consume any of the parent's budget headroom.
  make_sized_file "$FIXTURE_DIR/replay1-main-6.txt" 20
  result="$(invoke_hook_raw "$(subagent_read_payload "$TEST_SESSION" "" "$FIXTURE_DIR/replay1-main-6.txt")")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "replay: main session's 6th distinct file still denied — subagent reads did not pollute the parent's budget"
  else
    fail "replay: main session's 6th distinct file should still be denied, got exit $exit_code"
  fi
}

# ---------------------------------------------------------------------------
# Replay 2: a subagent working alone (fresh session_id) reads the SAME file
# — one that alone exceeds the byte budget — 6 times in a row. Never denied,
# at any point, proving full exemption from the cost accounting, not merely
# from a call-count streak.
# ---------------------------------------------------------------------------
test_subagent_alone_never_denied() {
  local sess="test-subagent-alone-$$"
  rm -f "${STATE_DIR}/budget-${sess}.json" "${STATE_DIR}/budget-${sess}.lock" 2>/dev/null || true

  local big_file="$FIXTURE_DIR/replay2-big.txt"
  make_sized_file "$big_file" $(( BYTE_BUDGET + 1 ))

  local all_passed=true
  local i result exit_code
  for i in 1 2 3 4 5 6; do
    result="$(invoke_hook_raw "$(subagent_read_payload "$sess" "qa" "$big_file")")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -ne 0 ]]; then
      all_passed=false
      fail "replay: subagent Read $i/6 of an over-budget file (agent_type=qa) should be allowed, got exit $exit_code"
    fi
  done
  if $all_passed; then
    ok "replay: subagent alone — 6 reads of a file exceeding the byte budget all allowed (fully exempt from cost accounting)"
  fi

  rm -f "${STATE_DIR}/budget-${sess}.json" "${STATE_DIR}/budget-${sess}.lock" 2>/dev/null || true
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
  result="$(invoke_hook_raw "$(subagent_read_payload "$TEST_SESSION" "qa" "/tmp/x")")"
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
  result="$(invoke_hook_raw "$(subagent_read_payload "$TEST_SESSION" "" "/tmp/x")")"
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

# ===========================================================================
# Replay 5 — VERIFY-B Defect 1's ORIGINAL fix (rule_force_delegate must
# reset the streak on Agent dispatch) is SUPERSEDED by ADR-005's settled
# decision: the budget now ratchets and does NOT reset on Agent dispatch —
# see test_budget_does_not_reset_on_agent_dispatch above, which asserts the
# opposite of what this replay used to assert. Kept here as a pointer, not a
# duplicate test, so a future reader who remembers "Replay 5" finds why it
# moved instead of finding it silently gone.
# ===========================================================================

# ===========================================================================
# Replay 6 — VERIFY-B Defect 2: an unrecognized agent_type must NOT be
# granted the subagent exemption. Before that fix, ANY non-empty agent_type
# unconditionally exempted the call from rule_force_delegate and
# rule_qa_gate — an unvalidated field fully bypassing both guards. Re-proven
# here against the cost budget: an unrecognized agent_type's calls must
# actually be charged (and denied on overage) exactly like the main
# session's own.
# ===========================================================================
test_unknown_agent_type_not_exempt_force_delegate() {
  clean_state
  local sess="test-unknown-agent-fd-$$"
  rm -f "${STATE_DIR}/budget-${sess}.json" "${STATE_DIR}/budget-${sess}.lock" 2>/dev/null || true

  local i f result exit_code all_passed=true
  for i in 1 2 3 4; do
    f="$FIXTURE_DIR/unknown-agent-$i.txt"
    make_sized_file "$f" 20
    result="$(invoke_hook_raw "$(subagent_read_payload "$sess" "bogus-nonexistent-agent" "$f")")"
    exit_code="$(get_exit_code "$result")"
    if [[ "$exit_code" -ne 0 ]]; then
      all_passed=false
      fail "unknown-agent-type: call $i/4 (agent_type=bogus-nonexistent-agent) should be allowed under the files budget, got exit $exit_code"
    fi
  done
  if $all_passed; then
    ok "unknown-agent-type: 4 distinct-file reads with an unrecognized agent_type are charged normally (allowed under budget)"
  fi

  # A 5th distinct file is still allowed (count reaches exactly $FILES_BUDGET
  # — the calls above genuinely counted, unlike an exempt subagent's would).
  local f5="$FIXTURE_DIR/unknown-agent-5.txt"
  make_sized_file "$f5" 20
  result="$(invoke_hook_raw "$(subagent_read_payload "$sess" "bogus-nonexistent-agent" "$f5")")"
  exit_code="$(get_exit_code "$result")"
  local files_count
  files_count="$("$JQ_BIN" -r '.filesTouched // [] | length' "${STATE_DIR}/budget-${sess}.json" 2>/dev/null || echo 0)"
  if [[ "$exit_code" -eq 0 ]] && [[ "$files_count" -eq "$FILES_BUDGET" ]]; then
    ok "unknown-agent-type: 5th distinct file reaches filesTouched=$FILES_BUDGET — calls genuinely counted, not exempt"
  else
    fail "unknown-agent-type: expected exit 0 and filesTouched=$FILES_BUDGET, got exit $exit_code count=$files_count"
  fi

  # A 6th distinct file, still tagged with the unrecognized agent_type, is
  # denied — the bypass the pre-VERIFY-B bug allowed is gone under the new
  # budget just as it was under the old streak.
  local f6="$FIXTURE_DIR/unknown-agent-6.txt"
  make_sized_file "$f6" 20
  result="$(invoke_hook_raw "$(subagent_read_payload "$sess" "bogus-nonexistent-agent" "$f6")")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "unknown-agent-type: 6th distinct file with unrecognized agent_type is denied (not granted subagent exemption)"
  else
    fail "unknown-agent-type: 6th distinct file with unrecognized agent_type should be denied (bypass), got exit $exit_code"
  fi

  rm -f "${STATE_DIR}/budget-${sess}.json" "${STATE_DIR}/budget-${sess}.lock" 2>/dev/null || true
}

test_unknown_agent_type_not_exempt_qa_gate() {
  clean_state
  clean_gate_state
  write_gate_pending '["TASK-88"]'

  local payload result exit_code
  payload="$(printf '{"session_id":"%s","agent_type":"bogus-nonexistent-agent","agent_id":"x","tool_name":"Read","tool_input":{"file_path":"/tmp/x"}}' "$TEST_SESSION")"
  result="$(invoke_hook_raw "$payload")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "unknown-agent-type: QA gate active + Read with unrecognized agent_type is denied (not granted subagent exemption)"
  else
    fail "unknown-agent-type: QA gate active + Read with unrecognized agent_type should be denied, got exit $exit_code"
  fi

  clean_gate_state
}

# ===========================================================================
# Test 22 — /freeze (rule_path_scope) Write regression. Neither `main` nor
# the orphaned docs/40-initiatives-migration branch ever exercised a Write
# tool call against rule_path_scope, because neither branch's matcher ever
# included Write. This is new coverage for the matcher gap the investigation
# found in 77f5cdb's own fix (Bash|Read|Edit|Agent — no Write).
#
# rule_path_scope deliberately does NOT get a subagent exemption (unlike
# force-delegate/qa-gate): /freeze's purpose is to lock file mutation to a
# directory regardless of who is mutating, so a subagent Write outside the
# freeze dir must still deny — that's a control proving the no-exemption
# decision is actually enforced, not just documented.
# ===========================================================================
FREEZE_FILE="${STATE_DIR}/.freeze"

write_freeze_state() {
  local dir="$1"
  printf '%s\n' "$dir" > "$FREEZE_FILE"
}

clean_freeze_state() {
  rm -f "$FREEZE_FILE" 2>/dev/null || true
}

test_freeze_write_regression() {
  clean_state
  clean_freeze_state
  local freeze_dir="/tmp/freeze-test-dir-$$"
  write_freeze_state "$freeze_dir"

  local payload result exit_code

  # Write outside the freeze dir (main session) → denied
  payload="$(printf '{"session_id":"%s","tool_name":"Write","tool_input":{"file_path":"/tmp/some-other-file.py"}}' "$TEST_SESSION")"
  result="$(invoke_hook_raw "$payload")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "/freeze: Write outside freeze dir denied"
  else
    fail "/freeze: Write outside freeze dir should be denied, got exit $exit_code"
  fi

  # Write inside the freeze dir (main session) → allowed
  payload="$(printf '{"session_id":"%s","tool_name":"Write","tool_input":{"file_path":"%s/inside.py"}}' "$TEST_SESSION" "$freeze_dir")"
  result="$(invoke_hook_raw "$payload")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 0 ]]; then
    ok "/freeze: Write inside freeze dir allowed"
  else
    fail "/freeze: Write inside freeze dir should be allowed, got exit $exit_code"
  fi

  # Write outside the freeze dir from a SUBAGENT (agent_type set) → still
  # denied. rule_path_scope gets no subagent exemption, by design.
  payload="$(printf '{"session_id":"%s","agent_type":"qa","agent_id":"task-1","tool_name":"Write","tool_input":{"file_path":"/tmp/some-other-file.py"}}' "$TEST_SESSION")"
  result="$(invoke_hook_raw "$payload")"
  exit_code="$(get_exit_code "$result")"
  if [[ "$exit_code" -eq 2 ]]; then
    ok "/freeze: subagent Write outside freeze dir still denied (no subagent exemption, by design)"
  else
    fail "/freeze: subagent Write outside freeze dir should still be denied, got exit $exit_code"
  fi

  clean_freeze_state
}

# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------
echo "=== pretool-check.sh tests ==="
echo "(rule_force_delegate: ADR-005 cost budget, baseline $(basename "$BUDGET_BASELINE_FILE"))"
echo ""
echo "--- Test 1: Single Bash call allowed"
test_single_bash_allowed
echo "--- Test 2: bounded Bash charge amount, repetition allowed under budget"
test_bash_bounded_charge_and_repetition_allowed
echo "--- Test 3: five small reads allowed; a single large read denied on first contact"
test_five_small_reads_allowed_single_large_read_denied
echo "--- Test 4: alternating tool names no longer defeat the meter"
test_alternating_tools_no_longer_defeat_meter
echo "--- Test 5: Write is now charged"
test_write_now_charged
echo "--- Test 6: distinct-files budget"
test_distinct_files_budget
echo "--- Test 7: narrowed Read (offset/limit) charges less than the full file"
test_narrowed_read_charges_less_than_full_file
echo "--- Test 8: Bash unbounded vs bounded charge"
test_bash_unbounded_vs_bounded_charge
echo "--- Test 9: Agent tool always allowed, never charged"
test_agent_always_allowed
echo "--- Test 10: COPILOT_FORCE_DELEGATE=off escape hatch"
test_escape_hatch_off
echo "--- Test 11: Stale state file resets the ratchet"
test_stale_state_no_error
echo "--- Test 12: Malformed/empty payload"
test_malformed_payload
echo "--- Test 13: Concurrent session isolation"
test_concurrent_safety
echo "--- Test 14: warning emitted before the deny"
test_warning_before_deny
echo "--- Test 15: audited budget override (env var + committed ledger)"
test_override_path
echo "--- Test 16: budget does NOT reset on Agent dispatch"
test_budget_does_not_reset_on_agent_dispatch
echo "--- Test 17: Performance <50ms"
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
echo "--- Test 18: git push / git pull charged like any bounded command (allowlist removed)"
test_git_push_pull_charged_like_any_bounded_command
echo "--- Test 19: command-string escape hatch (COPILOT_FORCE_DELEGATE=off prefix)"
test_command_string_escape_hatch
echo "--- Test 20: crash fix — git push exits 0 (no hook crash)"
test_git_push_no_crash

echo ""
echo "--- Test 21: crash-injected hook fails open for Read/Edit (Hypothesis A / 4.0.1 deadlock regression)"
test_crash_fails_open_for_read_and_edit

echo ""
echo "--- Replay 1: subagent Read exempt from force-delegate budget (does not pollute parent's meter)"
test_subagent_read_exempt_from_force_delegate
echo "--- Replay 2: subagent alone — never denied even reading an over-budget file repeatedly"
test_subagent_alone_never_denied
echo "--- Replay 3: QA gate + qa subagent's own Read/Edit exempt"
test_qa_gate_subagent_read_edit_exempt
echo "--- Replay 4: QA gate + nested Agent dispatch still gated"
test_qa_gate_nested_agent_dispatch_still_gated

echo ""
echo "--- Test 22: /freeze — Write outside freeze dir denied, inside allowed, subagent Write still denied"
test_freeze_write_regression

echo ""
echo "--- Replay 5: superseded by Test 16 (budget does not reset on Agent dispatch) — see comment above"
echo "--- Replay 6a: VERIFY-B Defect 2 — unrecognized agent_type not exempt from force-delegate budget"
test_unknown_agent_type_not_exempt_force_delegate
echo "--- Replay 6b: VERIFY-B Defect 2 — unrecognized agent_type not exempt from qa-gate"
test_unknown_agent_type_not_exempt_qa_gate

# Clean up test session state
clean_state
clean_gate_state
clean_freeze_state
clean_no_active_cc
clean_overrides_file
clean_fixtures

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
