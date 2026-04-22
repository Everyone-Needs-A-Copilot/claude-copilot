#!/usr/bin/env bash
# subagent-stop.sh — SubagentStop hook for Claude Copilot QA gate
#
# PURPOSE:
#   Manages QA-gate state in .claude/hooks/state/qa-gate.json.
#
#   When @agent-me completes: adds task_id to pending_tasks[session_id].
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
STATE_DIR="${SCRIPT_DIR}/state"
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
# Extract first TASK-N reference from a message string.
# Returns empty string if none found.
# ---------------------------------------------------------------------------
extract_task_id() {
  local msg="$1"
  # Look for TASK-N (digits only) pattern
  printf '%s' "$msg" | grep -oE 'TASK-[0-9]+' | head -1 || echo ""
}

# ---------------------------------------------------------------------------
# QA verdict parsing
# Returns: "pass", "fail", or "unknown"
# Precedence (case-insensitive):
#   1. VERDICT: APPROVED or APPROVED-WITH-MINOR-FIXES → pass
#   2. VERDICT: REJECTED → fail
#   3. <promise>COMPLETE</promise> with no REJECTED → implicit pass
#   4. Otherwise → unknown (treated as fail for safety)
# ---------------------------------------------------------------------------
parse_qa_verdict() {
  local msg="$1"
  local msg_upper
  msg_upper="$(printf '%s' "$msg" | tr '[:lower:]' '[:upper:]')"

  # Explicit VERDICT tokens (highest precedence)
  if printf '%s' "$msg_upper" | grep -qE 'VERDICT:[[:space:]]*(APPROVED-WITH-MINOR-FIXES|APPROVED)'; then
    echo "pass"
    return
  fi
  if printf '%s' "$msg_upper" | grep -qE 'VERDICT:[[:space:]]*REJECTED'; then
    echo "fail"
    return
  fi

  # Implicit pass: COMPLETE promise with no REJECTED language
  if printf '%s' "$msg" | grep -qF '<promise>COMPLETE</promise>'; then
    if ! printf '%s' "$msg_upper" | grep -qE 'REJECTED|VERDICT:[[:space:]]*FAIL'; then
      echo "pass"
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
  local task_id
  task_id="$(extract_task_id "$LAST_MSG")"

  if [[ -z "$task_id" ]]; then
    log_warn "agent-me completed but no TASK-N found in last_assistant_message (session: ${SESSION_ID})"
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
  local task_id verdict
  task_id="$(extract_task_id "$LAST_MSG")"
  verdict="$(parse_qa_verdict "$LAST_MSG")"

  if [[ -z "$task_id" ]]; then
    log_warn "agent-qa completed but no TASK-N found in last_assistant_message (session: ${SESSION_ID}, verdict: ${verdict})"
    exit 0
  fi

  acquire_lock
  trap 'release_lock' EXIT

  local state session_entry now
  now="$(now_iso)"
  state="$(read_gate_state)"
  session_entry="$(get_session "$state")"

  local updated_entry advisory_msg=""

  if [[ "$verdict" == "pass" ]]; then
    # Remove task from pending_tasks, clear retries
    updated_entry="$(printf '%s' "$session_entry" | "$JQ" \
      --arg tid "$task_id" \
      --arg now "$now" \
      --arg event "qa_passed" '
      .pending_tasks = (.pending_tasks | map(select(. != $tid))) |
      .retries = (.retries | del(.[$tid])) |
      .history = .history + [{"taskId": $tid, "event": $event, "ts": $now}] |
      .lastSeen = $now
    ' 2>/dev/null)"
    log_info "qa_passed: removed ${task_id} from pending_tasks (session: ${SESSION_ID})"
  else
    # Increment retry counter
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
    log_warn "Failed to compute updated entry for qa completion (task: ${task_id})"
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
