#!/usr/bin/env bash
# pretool-check.sh — PreToolUse hook entrypoint for Claude Copilot
#
# ARCHITECTURE:
#   This is the single PreToolUse hook dispatcher. All PreToolUse rule sets
#   (force-delegate, QA-gate, etc.) are implemented here or sourced from
#   sibling files. To add a new rule set (e.g., task 16's QA gate):
#     1. Add a function rule_<name>() below
#     2. Call it in the dispatch section near the bottom
#     3. Each rule returns 0 (allow) or writes a deny JSON to stdout and exits 2
#
# ESCAPE HATCH:
#   Set COPILOT_FORCE_DELEGATE=off to bypass all force-delegate checks.
#   Security rules are never bypassed.
#
# INPUT (stdin):
#   JSON object with fields:
#     session_id  — unique session identifier
#     tool_name   — e.g. "Bash", "Read", "Edit", "Agent"
#     tool_input  — tool-specific parameters (object)
#
# OUTPUT:
#   Exit 0 + empty stdout  → allow
#   Exit 2 + JSON stdout   → deny with reason
#   JSON shape: { "permissionDecision": "deny", "reason": "..." }
#
# PERFORMANCE TARGET: <50ms per invocation
#
# STATE FILES:
#   .claude/hooks/state/streak-<session_id>.json
#   Shape: { "session_id": "...", "lastTool": "Bash", "streak": 3, "updatedAt": "<ISO>" }
#
#   .claude/hooks/state/qa-gate.json
#   Shape: { "<session_id>": { "pending_tasks": ["TASK-5"], "retries": { "TASK-5": 1 },
#             "history": [{ "taskId": "TASK-5", "event": "me_completed", "ts": "<ISO>" }],
#             "lastSeen": "<ISO>" } }
#
# RULE SETS:
#   1. force-delegate — deny after 5 consecutive same-tool calls (Bash|Read|Edit)
#      Task: 17 (P4.2).
#   2. qa-gate — deny all tool calls except Agent(qa) and safe tc Bash calls
#      while any task is in pending-qa state for this session.
#      Task: 16 (P4.1). Bypass: COPILOT_QA_GATE=off

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${SCRIPT_DIR}/state"
JQ="/usr/bin/jq"

# ---------------------------------------------------------------------------
# Read hook payload from stdin
# ---------------------------------------------------------------------------
PAYLOAD="$(cat)"

if [[ -z "$PAYLOAD" ]]; then
  exit 0
fi

SESSION_ID="$(printf '%s' "$PAYLOAD" | "$JQ" -r '.session_id // ""' 2>/dev/null || echo "")"
TOOL_NAME="$(printf '%s' "$PAYLOAD" | "$JQ" -r '.tool_name // ""' 2>/dev/null || echo "")"

if [[ -z "$SESSION_ID" || -z "$TOOL_NAME" ]]; then
  # Malformed payload — allow and let Claude handle it
  exit 0
fi

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------
STATE_FILE="${STATE_DIR}/streak-${SESSION_ID}.json"
LOCK_FILE="${STATE_DIR}/streak-${SESSION_ID}.lock"
STALENESS_SECONDS=86400  # 24 hours

# Acquire a simple lock to prevent concurrent corruption
# Uses mkdir atomicity (POSIX-guaranteed).
acquire_lock() {
  local i=0
  while ! mkdir "$LOCK_FILE" 2>/dev/null; do
    sleep 0.02
    i=$((i + 1))
    if [[ $i -ge 10 ]]; then
      # Could not acquire lock in ~200ms — allow and bail
      exit 0
    fi
  done
}

release_lock() {
  rmdir "$LOCK_FILE" 2>/dev/null || true
}

read_streak() {
  if [[ ! -f "$STATE_FILE" ]]; then
    echo '{"lastTool":"","streak":0}'
    return
  fi
  local updated_at
  updated_at="$("$JQ" -r '.updatedAt // ""' "$STATE_FILE" 2>/dev/null || echo "")"
  if [[ -n "$updated_at" ]]; then
    local now_epoch file_epoch
    now_epoch="$(date -u +%s)"
    # date -j -f "%Y-%m-%dT%H:%M:%SZ" on macOS; fallback on Linux
    if [[ "$(uname)" == "Darwin" ]]; then
      file_epoch="$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "${updated_at}" +%s 2>/dev/null || echo 0)"
    else
      file_epoch="$(date -d "${updated_at}" +%s 2>/dev/null || echo 0)"
    fi
    local age=$(( now_epoch - file_epoch ))
    if [[ "$age" -gt "$STALENESS_SECONDS" ]]; then
      # Stale — treat as fresh
      echo '{"lastTool":"","streak":0}'
      return
    fi
  fi
  "$JQ" '{lastTool: .lastTool, streak: .streak}' "$STATE_FILE" 2>/dev/null \
    || echo '{"lastTool":"","streak":0}'
}

write_streak() {
  local last_tool="$1"
  local streak="$2"
  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local tmp="${STATE_FILE}.tmp.$$"
  printf '{"session_id":"%s","lastTool":"%s","streak":%d,"updatedAt":"%s"}\n' \
    "$SESSION_ID" "$last_tool" "$streak" "$now" > "$tmp"
  mv "$tmp" "$STATE_FILE"
}

deny() {
  local reason="$1"
  printf '{"permissionDecision":"deny","reason":"%s"}\n' \
    "$(printf '%s' "$reason" | sed 's/"/\\"/g')"
  exit 2
}

# ---------------------------------------------------------------------------
# Rule: force-delegate
# Deny when the same tool (Bash|Read|Edit) is called 5+ times consecutively.
# The Agent tool is never subject to this rule (delegation is always allowed).
# Bypass: COPILOT_FORCE_DELEGATE=off
# ---------------------------------------------------------------------------
rule_force_delegate() {
  # Check escape hatch
  if [[ "${COPILOT_FORCE_DELEGATE:-}" == "off" ]]; then
    return 0
  fi

  # Only track Bash, Read, Edit — not Agent or other tools
  case "$TOOL_NAME" in
    Bash|Read|Edit) ;;
    *) return 0 ;;
  esac

  acquire_lock
  trap 'release_lock' EXIT

  local state
  state="$(read_streak)"
  local last_tool streak
  last_tool="$(printf '%s' "$state" | "$JQ" -r '.lastTool')"
  streak="$(printf '%s' "$state" | "$JQ" -r '.streak')"

  if [[ "$TOOL_NAME" == "$last_tool" ]]; then
    streak=$((streak + 1))
  else
    streak=1
  fi

  if [[ "$streak" -ge 5 ]]; then
    # Reset streak on deny so the next call starts fresh
    write_streak "$TOOL_NAME" 0
    release_lock
    trap - EXIT
    deny "Main session has issued 5+ consecutive ${TOOL_NAME} calls. Delegate to @agent-me (code), @agent-do (infra), or @agent-qa (verification) instead. This preserves context budget and matches the framework's core purpose."
  fi

  write_streak "$TOOL_NAME" "$streak"
  release_lock
  trap - EXIT
  return 0
}

# ---------------------------------------------------------------------------
# Rule: qa-gate
# Deny all tool calls while any task is in pending-qa state for this session,
# EXCEPT:
#   - Agent tool with subagent_type == "qa"
#   - Bash commands that match safe read-only tc introspection prefixes
# Bypass: COPILOT_QA_GATE=off
# State: .claude/hooks/state/qa-gate.json (written by subagent-stop.sh)
# ---------------------------------------------------------------------------

# Safe Bash prefixes allowed while QA gate is active
QA_GATE_SAFE_PREFIXES=(
  "tc task get"
  "tc task list"
  "tc wp get"
  "tc wp list"
  "tc progress"
  "tc log"
)

is_safe_bash_command() {
  local cmd="$1"
  local prefix
  for prefix in "${QA_GATE_SAFE_PREFIXES[@]}"; do
    if [[ "$cmd" == "${prefix}"* ]]; then
      return 0
    fi
  done
  return 1
}

rule_qa_gate() {
  # Escape hatch
  if [[ "${COPILOT_QA_GATE:-}" == "off" ]]; then
    return 0
  fi

  local gate_file="${STATE_DIR}/qa-gate.json"

  # No gate file → no pending tasks → allow
  if [[ ! -f "$gate_file" ]]; then
    return 0
  fi

  # Read pending_tasks for this session
  local pending_json
  pending_json="$("$JQ" -r --arg sid "$SESSION_ID" \
    '.[$sid].pending_tasks // [] | @json' "$gate_file" 2>/dev/null || echo "[]")"

  local pending_count
  pending_count="$(printf '%s' "$pending_json" | "$JQ" 'length' 2>/dev/null || echo 0)"

  if [[ "$pending_count" -eq 0 ]]; then
    return 0
  fi

  # Build a readable list of blocking task IDs
  local blocking_ids
  blocking_ids="$(printf '%s' "$pending_json" | "$JQ" -r 'join(", ")' 2>/dev/null || echo "unknown")"

  # Allow: Agent tool with subagent_type == "qa"
  if [[ "$TOOL_NAME" == "Agent" ]]; then
    local subagent_type
    subagent_type="$(printf '%s' "$PAYLOAD" | "$JQ" -r '.tool_input.subagent_type // ""' 2>/dev/null || echo "")"
    if [[ "$subagent_type" == "qa" ]]; then
      return 0
    fi
    # All other Agent calls are denied while gate is active
    deny "QA gate active: ${blocking_ids} require @agent-qa verification before further work. Invoke @agent-qa to unblock."
  fi

  # Allow: Bash with safe tc introspection command
  if [[ "$TOOL_NAME" == "Bash" ]]; then
    local cmd
    cmd="$(printf '%s' "$PAYLOAD" | "$JQ" -r '.tool_input.command // ""' 2>/dev/null || echo "")"
    if is_safe_bash_command "$cmd"; then
      return 0
    fi
  fi

  # Deny everything else
  deny "QA gate active: ${blocking_ids} require @agent-qa verification before further work. Only @agent-qa invocation and read-only tc commands (tc task get, tc wp get, etc.) are allowed until QA passes."
}

# ---------------------------------------------------------------------------
# Dispatch — rule sets run in order; first deny wins
# ---------------------------------------------------------------------------
rule_force_delegate
rule_qa_gate

exit 0
