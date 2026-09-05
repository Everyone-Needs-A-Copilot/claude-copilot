#!/bin/bash
# Codex PreToolUse/PostToolUse hook: warn after a command shape fails twice,
# then deny one third repeat. State is isolated per Codex session and shape.
# The hook always fails open if it cannot parse input or maintain state.

if [ "${COPILOT_DEBUG_BLOCK:-}" = "off" ]; then
  exit 0
fi

JQ="$(command -v jq 2>/dev/null || true)"
SHASUM="$(command -v shasum 2>/dev/null || true)"
[ -n "$JQ" ] && [ -n "$SHASUM" ] || exit 0

PAYLOAD="$(cat 2>/dev/null)"
[ -n "$PAYLOAD" ] || exit 0

EVENT="$($JQ -r '.hook_event_name // empty' <<< "$PAYLOAD" 2>/dev/null)"
TOOL_NAME="$($JQ -r '.tool_name // empty' <<< "$PAYLOAD" 2>/dev/null)"
COMMAND="$($JQ -r '.tool_input.command // empty' <<< "$PAYLOAD" 2>/dev/null)"
SESSION_ID="$($JQ -r '.session_id // "unknown"' <<< "$PAYLOAD" 2>/dev/null)"

[ "$TOOL_NAME" = "Bash" ] && [ -n "$COMMAND" ] || exit 0

normalize_command_shape() {
  printf '%s' "$1" | sed -E \
    -e 's/"[^"]*"/Q/g' \
    -e "s/'[^']*'/Q/g" \
    -e 's/=[^ ]+/=VAL/g' \
    -e 's#/[A-Za-z0-9_./+-]+#PATH#g' \
    -e 's/[0-9]+/NUM/g' \
    -e 's/[[:space:]]+/ /g' \
    -e 's/^ | $//g'
}

SHAPE="$(normalize_command_shape "$COMMAND")"
STATE_KEY="$(printf '%s\n%s' "$SESSION_ID" "$SHAPE" | "$SHASUM" -a 256 2>/dev/null | cut -c1-24)"
[ -n "$STATE_KEY" ] || exit 0

STATE_ROOT="${CODEX_COPILOT_HOOK_STATE_DIR:-${PLUGIN_DATA:-${TMPDIR:-/tmp}/codex-copilot}/debug-block}"
mkdir -p "$STATE_ROOT" 2>/dev/null || exit 0
STATE_FILE="$STATE_ROOT/$STATE_KEY"

read_count() {
  local count=0
  if [ -f "$STATE_FILE" ]; then
    count="$(cat "$STATE_FILE" 2>/dev/null)"
    case "$count" in
      ''|*[!0-9]*) count=0 ;;
    esac
  fi
  printf '%s' "$count"
}

if [ "$EVENT" = "PreToolUse" ]; then
  COUNT="$(read_count)"
  [ "$COUNT" -ge 2 ] || exit 0

  printf '0\n' > "$STATE_FILE" 2>/dev/null || exit 0
  REASON='This command shape failed twice. Read the enforcing code and cite file:line, or run a materially different diagnostic. Set COPILOT_DEBUG_BLOCK=off to override.'
  $JQ -cn --arg reason "$REASON" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}'
  exit 0
fi

[ "$EVENT" = "PostToolUse" ] || exit 0

EXIT_CODE="$($JQ -r '.tool_response.exit_code // .tool_response.exitCode // .tool_response.code // empty' <<< "$PAYLOAD" 2>/dev/null)"
RESPONSE_TEXT="$($JQ -r 'if (.tool_response | type) == "string" then .tool_response else (.tool_response // {} | tostring) end' <<< "$PAYLOAD" 2>/dev/null)"

IS_ERROR=0
case "$EXIT_CODE" in
  '' )
    if printf '%s' "$RESPONSE_TEXT" | grep -qiE 'command not found|permission denied|fatal:|Traceback|ERROR:|exit code [1-9]|exited with code [1-9]'; then
      IS_ERROR=1
    fi
    ;;
  *[!0-9-]* ) exit 0 ;;
  0 ) IS_ERROR=0 ;;
  * ) IS_ERROR=1 ;;
esac

if [ "$IS_ERROR" -eq 0 ]; then
  printf '0\n' > "$STATE_FILE" 2>/dev/null
  exit 0
fi

COUNT="$(read_count)"
COUNT=$((COUNT + 1))
printf '%s\n' "$COUNT" > "$STATE_FILE" 2>/dev/null || exit 0
[ "$COUNT" -eq 2 ] || exit 0

MSG='This command shape failed twice. Verify what it exercised; read the enforcing code and cite file:line before another hypothesis.'
$JQ -cn --arg context "$MSG" \
  '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$context}}'

exit 0
