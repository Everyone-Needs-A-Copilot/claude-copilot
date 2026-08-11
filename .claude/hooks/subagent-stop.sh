#!/usr/bin/env bash
# subagent-stop.sh — SubagentStop hook for Claude Copilot QA gate
#
# PURPOSE:
#   Manages QA-gate state in .claude/hooks/state/qa-gate.json.
#
#   When @agent-me completes: extracts a task_id from the agent's structured
#     "Task: TASK-N" header (see extract_task_id below), VALIDATES it against
#     THIS project's tc database (see task_id_valid_in_project), and only
#     then adds it to pending_tasks[session_id]. An ID that doesn't parse or
#     doesn't resolve locally never arms the gate (see fail-safe note in
#     handle_me_completion) — this is the RC-2 fix: a gate must never arm
#     against a task ID that only exists in a DIFFERENT project's database.
#   When @agent-qa completes: parses verdict, removes task from pending_tasks
#     on pass, increments retry counter on fail. After 3 failures, auto-unblocks
#     and emits an advisory systemMessage.
#
# INPUT (stdin):
#   JSON payload from Claude Code SubagentStop event. Expected fields:
#     session_id          — parent session identifier
#     agent_type          — subagent type (e.g. "me", "qa", "ta")
#     last_assistant_message — the subagent's final output text
#   (other fields ignored)
#
# TASK ID SOURCE OF TRUST (RC-2):
#   Task IDs are read from the agent's structured "Task: TASK-N | WP: WP-N"
#   header line (a contract-mandated field, not narrative prose — see
#   .claude/agents/_shared/output-contract.md and each agent's Output Format
#   section), then validated against the CURRENT project's tc database
#   (`tc task get <N> --json`, resolved via $CLAUDE_PROJECT_DIR). Both steps
#   are required: anchoring alone cannot rule out a well-formed header that
#   references the wrong project's task graph. See task_id_valid_in_project().
#
# OUTPUT:
#   Exit 0 always (this hook is non-blocking for SubagentStop).
#   On 3rd consecutive QA failure: emits JSON with systemMessage advisory.
#
# STATE FILE:
#   .claude/hooks/state/qa-gate.json
#   Shape: {
#     "<session_id>": {
#       "pending_tasks": ["TASK-5", "TASK-12"],
#       "retries": { "TASK-5": 1 },
#       "history": [{ "taskId": "TASK-5", "event": "me_completed", "ts": "<ISO>" }],
#       "lastSeen": "<ISO>"
#     }
#   }
#
# LOG FILE:
#   .claude/hooks/state/qa-gate.log — warnings for missing task IDs etc.
#
# ADVERSARIAL PASS (TASK-131):
#   Optional second-model "try to break this diff" pass.  When a configured CLI
#   is present, @agent-qa can run `.claude/hooks/bin/adversarial-pass.sh` and
#   include the emitted ARTIFACT: adversarial-run|... line in its verdict.
#   Configure via COPILOT_ADVERSARIAL_CMD env var or auto-probe (codex/llm/mods).
#   When no CLI is present the script is a clean no-op — gate never blocked.
#
# ESCAPE HATCH:
#   Set COPILOT_QA_GATE=off to disable all QA gate state management.
#
# STALE CLEANUP:
#   Sessions with lastSeen > 72 hours are pruned on each state write.

set -uo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${COPILOT_HOOK_STATE_DIR:-${SCRIPT_DIR}/state}"
GATE_FILE="${STATE_DIR}/qa-gate.json"
LOCK_FILE="${STATE_DIR}/qa-gate.lock"
LOG_FILE="${STATE_DIR}/qa-gate.log"
JQ="/usr/bin/jq"

MAX_RETRIES=3
STALE_SECONDS=259200  # 72 hours

# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------
if [[ "${COPILOT_QA_GATE:-}" == "off" ]]; then
  exit 0
fi

# ---------------------------------------------------------------------------
# Read hook payload from stdin
# ---------------------------------------------------------------------------
PAYLOAD="$(cat)"

if [[ -z "$PAYLOAD" ]]; then
  exit 0
fi

SESSION_ID="$(printf '%s' "$PAYLOAD" | "$JQ" -r '.session_id // ""' 2>/dev/null || echo "")"
AGENT_TYPE="$(printf '%s' "$PAYLOAD" | "$JQ" -r '.agent_type // ""' 2>/dev/null || echo "")"
LAST_MSG="$(printf '%s' "$PAYLOAD" | "$JQ" -r '.last_assistant_message // ""' 2>/dev/null || echo "")"

# Only act on me and qa agent types
if [[ "$AGENT_TYPE" != "me" && "$AGENT_TYPE" != "qa" ]]; then
  exit 0
fi

if [[ -z "$SESSION_ID" ]]; then
  exit 0
fi

# ---------------------------------------------------------------------------
# Lock helpers (mkdir atomicity, POSIX-guaranteed)
# ---------------------------------------------------------------------------
acquire_lock() {
  local i=0
  while ! mkdir "$LOCK_FILE" 2>/dev/null; do
    sleep 0.02
    i=$((i + 1))
    if [[ $i -ge 15 ]]; then
      # Could not acquire in ~300ms — bail, non-blocking
      exit 0
    fi
  done
}

release_lock() {
  rmdir "$LOCK_FILE" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# ISO timestamp
# ---------------------------------------------------------------------------
now_iso() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log_warn() {
  local msg="$1"
  printf '[%s] WARN: %s\n' "$(now_iso)" "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

log_info() {
  local msg="$1"
  printf '[%s] INFO: %s\n' "$(now_iso)" "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# State read/write
# ---------------------------------------------------------------------------
read_gate_state() {
  if [[ ! -f "$GATE_FILE" ]]; then
    echo '{}'
    return
  fi
  "$JQ" '.' "$GATE_FILE" 2>/dev/null || echo '{}'
}

write_gate_state() {
  local json="$1"
  local tmp="${GATE_FILE}.tmp.$$"
  printf '%s\n' "$json" > "$tmp"
  mv "$tmp" "$GATE_FILE"
}

# Prune sessions with lastSeen > 72h
prune_stale() {
  local state="$1"
  printf '%s' "$state" | "$JQ" --argjson stale "$STALE_SECONDS" '
    to_entries
    | map(select(
        (.value.lastSeen // "") != "" and
        (now - (.value.lastSeen | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime)) < $stale
      ))
    | from_entries
  ' 2>/dev/null || printf '%s' "$state"
}

# Get or initialize session entry
get_session() {
  local state="$1"
  printf '%s' "$state" | "$JQ" -r --arg sid "$SESSION_ID" '
    .[$sid] // {"pending_tasks":[],"retries":{},"history":[],"lastSeen":""}
  ' 2>/dev/null || echo '{"pending_tasks":[],"retries":{},"history":[],"lastSeen":""}'
}

# ---------------------------------------------------------------------------
# Task ID extraction
#
# RC-2 (the false-gate incident this fix closes): the previous implementation
# was `grep -oE 'TASK-[0-9]+' | head -1` over the ENTIRE raw message -- a
# scan of free narrative prose, not a structured field. It scraped a stray
# "TASK-612" mentioned somewhere in an agent's summary (a reference in
# passing, not the agent's own task) and armed a QA gate against it, even
# though TASK-612 does not exist in this project's tc database at all -- it
# exists only in a DIFFERENT project's (convoco's) database.
#
# Fix: anchor extraction to the structured "Task: TASK-N | WP: WP-N" header
# line that @agent-me's and @agent-qa's Output Format contracts REQUIRE as
# their first reported line (see .claude/agents/me.md, .claude/agents/qa.md,
# .claude/agents/_shared/output-contract.md's agent-to-agent register --
# "Task/WP IDs" are called out there as structured, precision-over-prose
# fields, not narrative). A bare "TASK-N" appearing mid-sentence anywhere
# else in the message body no longer matches.
#
# This narrows the surface but is not sufficient alone -- a well-formed
# "Task:" header can still reference the wrong project's task graph (stale
# context, a copy-pasted example, cross-session bleed). See
# task_id_valid_in_project() below, which is the hard boundary: extraction
# picks a CANDIDATE, validation is what decides whether it may arm a gate.
#
# Returns empty string if no structured Task: header line is found.
# ---------------------------------------------------------------------------
extract_task_id() {
  local msg="$1"
  local line
  line="$(printf '%s\n' "$msg" | grep -oE '^[[:space:]]*Task:[[:space:]]*TASK-[0-9]+' | head -1 2>/dev/null)" || line=""
  printf '%s' "$line" | grep -oE 'TASK-[0-9]+' 2>/dev/null || echo ""
}

# Extract ALL TASK-N references from a message string.
# Returns a JSON array of unique task IDs, e.g. '["TASK-5","TASK-12"]'
#
# NOTE (sibling audit, see JOB-1 item 5): this one intentionally still scans
# the whole message body rather than anchoring to the "Task:" header, because
# it feeds ONLY the qa-pass CLEAR path (handle_qa_completion's targeted vs.
# full-clear decision) -- never the arm path. A stray extra ID here can at
# most cause a targeted-clear to also happen to match, or fall through to
# the already-safe full-clear fallback; it can never arm a gate against an
# unvalidated task. That asymmetry (arm must be conservative, clear may be
# generous -- see fail-safe note in handle_me_completion) is why this
# function was left unanchored rather than changed to match extract_task_id.
extract_all_task_ids() {
  local msg="$1"
  local ids_raw
  ids_raw="$(printf '%s' "$msg" | grep -oE 'TASK-[0-9]+' | sort -u)" || ids_raw=""
  if [[ -z "$ids_raw" ]]; then
    echo '[]'
    return
  fi
  # Build a JSON array
  printf '%s\n' "$ids_raw" | "$JQ" -R . | "$JQ" -sc . 2>/dev/null || echo '[]'
}

# ---------------------------------------------------------------------------
# Task ID validation — confirm a task ID actually exists in THIS project's
# tc (Task Copilot) database before it is trusted to arm a gate.
#
# This is the sharp edge RC-2 exposed: a QA gate in one project (here,
# copilot-control-tower) was armed against a task ID that resolves only in
# a DIFFERENT project's database (convoco's). Anchored extraction (above)
# narrows *where* a candidate ID can come from; it cannot rule out a
# well-formed header pointing at the wrong project. Validation against the
# LOCAL tc database is the one channel that is actual ground truth rather
# than another heuristic: tc task IDs are project-scoped integers backed by
# a per-project SQLite file, and `tc task get <N> --json` resolves that file
# by walking up from cwd to the nearest `.copilot/tasks.db` -- so "does this
# ID exist in the project we are actually running in" is a real check, not
# a guess.
#
# Returns 0 (valid, arm-eligible) only when `tc task get <N> --json`
# succeeds against the project rooted at $CLAUDE_PROJECT_DIR (the env var
# Claude Code sets for hook invocations; falls back to $PWD, which is what
# the harness uses as cwd for hooks anyway). Any other outcome — malformed
# ID, tc not on PATH, no tasks.db for this project, or a well-formed ID tc
# reports as not found — returns non-zero. There is deliberately no
# "unknown, assume valid" branch: see the fail-safe note at the call site
# for why "cannot validate" and "invalid" get the identical response.
# ---------------------------------------------------------------------------
task_id_valid_in_project() {
  local task_id="$1"
  local num="${task_id#TASK-}"
  [[ "$num" =~ ^[0-9]+$ ]] || return 1

  command -v tc &>/dev/null || return 1

  local project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"
  ( cd "$project_dir" 2>/dev/null && tc task get "$num" --json >/dev/null 2>&1 )
}

# ---------------------------------------------------------------------------
# QA verdict parsing
# Returns: "pass", "fail", or "unknown"
# Precedence (case-insensitive):
#   1. VERDICT: APPROVED or APPROVED-WITH-MINOR-FIXES WITH an ARTIFACT marker → pass
#   2. VERDICT: APPROVED or APPROVED-WITH-MINOR-FIXES WITHOUT an ARTIFACT marker → fail
#      (a bare pass with no artifact is invalid per ADR-001 / WS1 failable-check gate)
#   3. VERDICT: REJECTED → fail
#   4. <promise>COMPLETE</promise> with no REJECTED AND an ARTIFACT marker → implicit pass
#   5. Otherwise → unknown (treated as fail for safety)
#
# ARTIFACT marker format (R3 WS1 / TASK-115, extended TASK-131):
#   ARTIFACT: <type>|<detail>
#   where type ∈ {test-run, file-check, diff-check, adversarial-run}
#   Example: ARTIFACT: test-run|pytest tests/foo.py exit=0 "3 passed"
#   Example: ARTIFACT: adversarial-run|llm FINDINGS: none found exit=0
#
# adversarial-run is OPTIONAL / bonus — emitted by adversarial-pass.sh when a
# second-model CLI is available.  It satisfies the artifact requirement on its
# own but is never a NEW mandatory requirement.  The gate still passes on any
# single recognized artifact type (e.g. test-run alone is sufficient).
#
# ESCAPE HATCH:
#   COPILOT_QA_GATE=off bypasses all gate logic in the caller (subagent-stop.sh).
# ---------------------------------------------------------------------------

# has_artifact_marker: returns 0 (true) if the message contains a valid ARTIFACT line.
has_artifact_marker() {
  local msg="$1"
  # Case-insensitive match for ARTIFACT: <type>|<detail>
  # type must be one of: test-run, file-check, diff-check, adversarial-run
  # adversarial-run added in TASK-131 (availability-gated; optional/bonus type).
  # Adding it here is ADDITIVE — existing types are unchanged; the new type
  # satisfies the artifact requirement but is never a mandatory gate of its own.
  printf '%s' "$msg" | grep -qiE '^[[:space:]]*ARTIFACT:[[:space:]]+(test-run|file-check|diff-check|adversarial-run)\|.+$'
}

parse_qa_verdict() {
  local msg="$1"
  local msg_upper
  msg_upper="$(printf '%s' "$msg" | tr '[:lower:]' '[:upper:]')"

  # Explicit VERDICT tokens (highest precedence)
  if printf '%s' "$msg_upper" | grep -qE 'VERDICT:[[:space:]]*(APPROVED-WITH-MINOR-FIXES|APPROVED)'; then
    # APPROVED verdict is only valid when accompanied by an ARTIFACT marker.
    # A bare "VERDICT: APPROVED" with no artifact is an invalid/insufficient verdict
    # and must NOT unblock the gate (ADR-001 / WS1 principle: verdicts bind to artifacts).
    if has_artifact_marker "$msg"; then
      echo "pass"
    else
      echo "fail"
      log_warn "VERDICT: APPROVED received but NO ARTIFACT marker found — gate NOT unblocked (session: ${SESSION_ID}). QA must include ARTIFACT: test-run|..., ARTIFACT: file-check|..., or ARTIFACT: diff-check|..."
    fi
    return
  fi
  if printf '%s' "$msg_upper" | grep -qE 'VERDICT:[[:space:]]*REJECTED'; then
    echo "fail"
    return
  fi

  # Implicit pass: COMPLETE promise with no REJECTED language, AND an ARTIFACT marker
  if printf '%s' "$msg" | grep -qF '<promise>COMPLETE</promise>'; then
    if ! printf '%s' "$msg_upper" | grep -qE 'REJECTED|VERDICT:[[:space:]]*FAIL'; then
      if has_artifact_marker "$msg"; then
        echo "pass"
      else
        echo "fail"
        log_warn "Implicit pass (<promise>COMPLETE</promise>) but NO ARTIFACT marker — gate NOT unblocked (session: ${SESSION_ID})."
      fi
      return
    fi
  fi

  # Default: unknown → fail (safe default)
  echo "fail"
}

# ---------------------------------------------------------------------------
# Handle @agent-me completion
# ---------------------------------------------------------------------------
handle_me_completion() {
  # Guard: BLOCKED and CONFUSED are non-completion terminal states.
  # Neither represents a finished implementation that needs QA review:
  #   <promise>BLOCKED</promise> — external/technical blocker; agent cannot proceed
  #   <promise>CONFUSED</promise> — decision fork that requires user input
  # In both cases, skip the QA gate so the signal surfaces to the user.
  if printf '%s' "$LAST_MSG" | grep -qF '<promise>BLOCKED</promise>'; then
    local blocked_task
    blocked_task="$(extract_task_id "$LAST_MSG")"
    log_info "me_completed with BLOCKED promise — skipping QA gate for ${blocked_task:-unknown} (session: ${SESSION_ID})"
    exit 0
  fi
  if printf '%s' "$LAST_MSG" | grep -qF '<promise>CONFUSED</promise>'; then
    local confused_task
    confused_task="$(extract_task_id "$LAST_MSG")"
    log_info "me_completed with CONFUSED promise — skipping QA gate for ${confused_task:-unknown} (session: ${SESSION_ID})"
    exit 0
  fi

  local task_id
  task_id="$(extract_task_id "$LAST_MSG")"

  if [[ -z "$task_id" ]]; then
    log_warn "agent-me completed but no TASK-N found in last_assistant_message (session: ${SESSION_ID})"
    exit 0
  fi

  if ! task_id_valid_in_project "$task_id"; then
    # FAIL-SAFE DIRECTION: do NOT arm on an ID that doesn't validate.
    #
    # A gate that fails to arm degrades to the pre-hook status quo for this
    # one completion — QA review is still the mandatory *social* contract in
    # every agent's Route-To table, only the mechanical backstop is missing,
    # and that gap is visible (this WARN) and recoverable by a human or a
    # later pass.
    #
    # A gate that arms on a bad ID is NOT self-healing: it denies every
    # Bash/Agent tool call in the session except Agent(qa) and a short tc
    # allowlist, and its only exit is 3 consecutive QA failure cycles
    # against a task QA can never find in this project's database (RC-2
    # burned exactly one such cycle before this fix landed). Under-enforcing
    # once is far cheaper than a session-wide false block, so validation
    # failure fails OPEN on the gate (skip arming), never closed.
    log_warn "agent-me completed with ${task_id} but it does not resolve in this project's tc database (cross-project or stale ID) — NOT arming QA gate (session: ${SESSION_ID})"
    exit 0
  fi

  acquire_lock
  trap 'release_lock' EXIT

  local state session_entry now
  now="$(now_iso)"
  state="$(read_gate_state)"
  session_entry="$(get_session "$state")"

  # Add task to pending_tasks (if not already present)
  local updated_entry
  updated_entry="$(printf '%s' "$session_entry" | "$JQ" \
    --arg tid "$task_id" \
    --arg now "$now" \
    --arg event "me_completed" '
    .pending_tasks = (
      if (.pending_tasks | map(. == $tid) | any) then .pending_tasks
      else .pending_tasks + [$tid]
      end
    ) |
    .history = .history + [{"taskId": $tid, "event": $event, "ts": $now}] |
    .lastSeen = $now
  ' 2>/dev/null)"

  if [[ -z "$updated_entry" ]]; then
    log_warn "Failed to update session entry for me_completed (task: ${task_id})"
    release_lock
    trap - EXIT
    exit 0
  fi

  local merged pruned
  merged="$(printf '%s' "$state" | "$JQ" \
    --arg sid "$SESSION_ID" \
    --argjson entry "$updated_entry" \
    '.[$sid] = $entry' 2>/dev/null || echo "$state")"
  pruned="$(prune_stale "$merged")"
  write_gate_state "$pruned"

  log_info "me_completed: added ${task_id} to pending_tasks (session: ${SESSION_ID})"

  release_lock
  trap - EXIT
}

# ---------------------------------------------------------------------------
# Handle @agent-qa completion
# ---------------------------------------------------------------------------
handle_qa_completion() {
  local task_id verdict all_task_ids
  task_id="$(extract_task_id "$LAST_MSG")"
  verdict="$(parse_qa_verdict "$LAST_MSG")"

  # On a pass verdict, we can proceed even without a task_id — QA's approval
  # unblocks ALL pending tasks for the session (a passing QA run clears the gate).
  # On a fail verdict, we need a task_id to track retries.
  if [[ -z "$task_id" && "$verdict" != "pass" ]]; then
    log_warn "agent-qa completed but no TASK-N found in last_assistant_message (session: ${SESSION_ID}, verdict: ${verdict})"
    exit 0
  fi

  all_task_ids="$(extract_all_task_ids "$LAST_MSG")"

  acquire_lock
  trap 'release_lock' EXIT

  local state session_entry now
  now="$(now_iso)"
  state="$(read_gate_state)"
  session_entry="$(get_session "$state")"

  local updated_entry advisory_msg=""

  if [[ "$verdict" == "pass" ]]; then
    # Strategy: clear all pending_tasks that appear in the QA message OR (when
    # the message references a different set of tasks) clear ALL pending tasks.
    # Rationale: a passing QA verdict means the work round-trip is complete.
    # The common failure mode is QA mentioning an old/different TASK-N while a
    # *different* task sits in pending_tasks — the pass should still unblock.
    #
    # Algorithm:
    #   1. Find the intersection of pending_tasks with all IDs mentioned in msg.
    #   2. If the intersection is non-empty → clear only those (targeted).
    #   3. If the intersection is empty (QA mentioned unrelated IDs) → clear ALL
    #      pending tasks (QA has approved work for this session).
    local pending_json
    pending_json="$(printf '%s' "$session_entry" | "$JQ" '.pending_tasks // []' 2>/dev/null || echo '[]')"
    local intersection_count
    intersection_count="$(printf '%s' "$pending_json" | "$JQ" \
      --argjson mentioned "$all_task_ids" \
      '[.[] | select(. as $t | $mentioned | map(. == $t) | any)] | length' 2>/dev/null || echo 0)"

    if [[ "$intersection_count" -gt 0 ]]; then
      # Targeted clear: remove only the tasks QA mentioned
      local history_entries
      history_entries="$(printf '%s' "$all_task_ids" | "$JQ" \
        --arg now "$now" \
        --arg event "qa_passed" \
        '[.[] | {"taskId": ., "event": $event, "ts": $now}]' 2>/dev/null || echo '[]')"
      updated_entry="$(printf '%s' "$session_entry" | "$JQ" \
        --argjson mentioned "$all_task_ids" \
        --argjson hist "$history_entries" \
        --arg now "$now" '
        .pending_tasks = (.pending_tasks | map(select(. as $t | $mentioned | map(. == $t) | any | not))) |
        .retries = (reduce $mentioned[] as $tid (.retries; del(.[$tid]))) |
        .history = .history + $hist |
        .lastSeen = $now
      ' 2>/dev/null)"
      log_info "qa_passed (targeted): cleared tasks ${all_task_ids} from pending_tasks (session: ${SESSION_ID})"
    else
      # Full clear: QA passed but mentioned different task IDs — unblock entire session
      local pending_arr
      pending_arr="$(printf '%s' "$pending_json" | "$JQ" -c '.' 2>/dev/null || echo '[]')"
      local history_entries
      history_entries="$(printf '%s' "$pending_json" | "$JQ" \
        --arg now "$now" \
        --arg event "qa_passed_full_clear" \
        '[.[] | {"taskId": ., "event": $event, "ts": $now}]' 2>/dev/null || echo '[]')"
      updated_entry="$(printf '%s' "$session_entry" | "$JQ" \
        --argjson hist "$history_entries" \
        --arg now "$now" '
        .pending_tasks = [] |
        .retries = {} |
        .history = .history + $hist |
        .lastSeen = $now
      ' 2>/dev/null)"
      log_info "qa_passed (full clear): cleared all pending tasks ${pending_arr} because QA approved for session ${SESSION_ID} (mentioned: ${all_task_ids})"
    fi
  else
    # Fail path: track retries by task_id
    local current_retries
    current_retries="$(printf '%s' "$session_entry" | "$JQ" -r --arg tid "$task_id" \
      '.retries[$tid] // 0' 2>/dev/null || echo 0)"
    local new_retries=$(( current_retries + 1 ))

    if [[ "$new_retries" -ge "$MAX_RETRIES" ]]; then
      # Auto-unblock: remove from pending_tasks after 3 failures
      local event="qa_failed_advisory_unblock"
      updated_entry="$(printf '%s' "$session_entry" | "$JQ" \
        --arg tid "$task_id" \
        --arg now "$now" \
        --arg event "$event" \
        --argjson retries "$new_retries" '
        .pending_tasks = (.pending_tasks | map(select(. != $tid))) |
        .retries[$tid] = $retries |
        .history = .history + [{"taskId": $tid, "event": $event, "ts": $now}] |
        .lastSeen = $now
      ' 2>/dev/null)"
      advisory_msg="QA gate degraded to advisory: ${task_id} failed QA ${new_retries} consecutive times. Main session is unblocked, but human review is strongly recommended — the code has not passed automated verification."
      log_warn "qa_failed_advisory_unblock: ${task_id} failed ${new_retries}x, auto-unblocking (session: ${SESSION_ID})"
    else
      local event="qa_failed_retry_${new_retries}"
      updated_entry="$(printf '%s' "$session_entry" | "$JQ" \
        --arg tid "$task_id" \
        --arg now "$now" \
        --arg event "$event" \
        --argjson retries "$new_retries" '
        .retries[$tid] = $retries |
        .history = .history + [{"taskId": $tid, "event": $event, "ts": $now}] |
        .lastSeen = $now
      ' 2>/dev/null)"
      log_info "qa_failed: ${task_id} retry ${new_retries}/${MAX_RETRIES} (session: ${SESSION_ID})"
    fi
  fi

  if [[ -z "$updated_entry" ]]; then
    log_warn "Failed to compute updated entry for qa completion (task: ${task_id:-unknown})"
    release_lock
    trap - EXIT
    exit 0
  fi

  local merged pruned
  merged="$(printf '%s' "$state" | "$JQ" \
    --arg sid "$SESSION_ID" \
    --argjson entry "$updated_entry" \
    '.[$sid] = $entry' 2>/dev/null || echo "$state")"
  pruned="$(prune_stale "$merged")"
  write_gate_state "$pruned"

  release_lock
  trap - EXIT

  # Emit advisory if needed (after lock released)
  if [[ -n "$advisory_msg" ]]; then
    printf '{"systemMessage":"%s"}\n' \
      "$(printf '%s' "$advisory_msg" | sed 's/"/\\"/g')"
  fi
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
case "$AGENT_TYPE" in
  me)  handle_me_completion ;;
  qa)  handle_qa_completion ;;
esac

exit 0
