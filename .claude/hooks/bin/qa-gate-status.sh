#!/usr/bin/env bash
# qa-gate-status.sh — CLI to inspect current QA gate state
#
# Usage:
#   .claude/hooks/bin/qa-gate-status.sh [session_id]
#
# Without a session_id argument, shows all active sessions.
# With a session_id argument, shows details for that session only.
#
# Output example:
#   Session: sess_abc123
#     Pending tasks: TASK-5 (retries: 1), TASK-12 (retries: 0)
#     Last event: TASK-5 me_completed at 2026-04-22T10:30:00Z
#
# Useful for debugging the QA gate state machine.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$(dirname "$SCRIPT_DIR")/state"
GATE_FILE="${STATE_DIR}/qa-gate.json"
JQ="/usr/bin/jq"

FILTER_SESSION="${1:-}"

if [[ ! -f "$GATE_FILE" ]]; then
  echo "QA gate state file not found: ${GATE_FILE}"
  echo "No sessions are tracked yet."
  exit 0
fi

# Read all sessions
ALL_STATE="$("$JQ" '.' "$GATE_FILE" 2>/dev/null)"

if [[ -z "$ALL_STATE" || "$ALL_STATE" == "{}" ]]; then
  echo "QA gate: no active sessions."
  exit 0
fi

# Get session keys
if [[ -n "$FILTER_SESSION" ]]; then
  SESSIONS=("$FILTER_SESSION")
else
  mapfile -t SESSIONS < <("$JQ" -r 'keys[]' "$GATE_FILE" 2>/dev/null)
fi

if [[ ${#SESSIONS[@]} -eq 0 ]]; then
  echo "QA gate: no sessions found."
  exit 0
fi

for sid in "${SESSIONS[@]}"; do
  SESSION_DATA="$("$JQ" -r --arg sid "$sid" '.[$sid] // empty' "$GATE_FILE" 2>/dev/null)"

  if [[ -z "$SESSION_DATA" ]]; then
    echo "Session: ${sid} (not found)"
    continue
  fi

  PENDING="$("$JQ" -r '.pending_tasks // [] | join(", ")' <<< "$SESSION_DATA" 2>/dev/null || echo "")"
  LAST_SEEN="$("$JQ" -r '.lastSeen // "unknown"' <<< "$SESSION_DATA" 2>/dev/null || echo "unknown")"

  echo "Session: ${sid}"
  echo "  Last seen: ${LAST_SEEN}"

  if [[ -z "$PENDING" ]]; then
    echo "  Pending tasks: none (gate clear)"
  else
    # Build pending list with retry counts
    PENDING_DISPLAY="$("$JQ" -r '
      .pending_tasks as $tasks |
      .retries as $retries |
      $tasks | map(
        . as $t |
        "\($t) (retries: \($retries[$t] // 0))"
      ) | join(", ")
    ' <<< "$SESSION_DATA" 2>/dev/null || echo "$PENDING")"
    echo "  Pending tasks: ${PENDING_DISPLAY}"
  fi

  # Show last event from history
  LAST_EVENT="$("$JQ" -r '
    .history // [] |
    if length > 0 then
      .[-1] | "\(.taskId) \(.event) at \(.ts)"
    else
      "no events"
    end
  ' <<< "$SESSION_DATA" 2>/dev/null || echo "no events")"
  echo "  Last event: ${LAST_EVENT}"

  # Show history count
  HISTORY_COUNT="$("$JQ" -r '.history // [] | length' <<< "$SESSION_DATA" 2>/dev/null || echo 0)"
  echo "  History entries: ${HISTORY_COUNT}"
  echo ""
done

exit 0
