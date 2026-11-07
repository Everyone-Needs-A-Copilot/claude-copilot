#!/bin/bash
# Codex UserPromptSubmit hook: always inject the coordinator rule, plus a routing nudge when needed.
# Reads only the stable .prompt field and fails open on every parse error.

JQ="$(command -v jq 2>/dev/null || true)"
[ -n "$JQ" ] || exit 0

PAYLOAD="$(cat 2>/dev/null)"
[ -n "$PAYLOAD" ] || exit 0

PROMPT="$($JQ -r '.prompt // empty' <<< "$PAYLOAD" 2>/dev/null)"
[ -n "$PROMPT" ] || exit 0

MSG=""
if printf '%s' "$PROMPT" | grep -qiE 'broken|not working|error|fails|failing|bug|crash|unexpected'; then
  MSG='Route through $qa before responding; saying you will invoke it is not invocation.'
elif printf '%s' "$PROMPT" | grep -qiE '(^|[^[:alnum:]_])(UI|UX)([^[:alnum:]_]|$)|modal|button|form|screen|layout'; then
  MSG='Route through $sd and $uxd before responding; saying so is not invocation.'
elif printf '%s' "$PROMPT" | grep -qiE 'architecture|refactor|backend|(^|[^[:alnum:]_])API([^[:alnum:]_]|$)|performance|migration'; then
  MSG='Route through $ta before responding; saying you will invoke it is not invocation.'
fi

COORD='Coordinator rule (2026-11-05): you are a coordinator. Never read project content, edit files or run work commands yourself; split the request into independent streams and dispatch agents via spawn_agent now. Read-only work needs no approval wait; approval gates only writes, outward actions and spending. Allowed: tc, cc status/list/progress/skill, git status/log/branch/worktree list, synthesis, notes. No size exceptions.'
if [ "${COPILOT_COORDINATOR:-}" = "off" ]; then
  COORD='Coordinator rule is OFF for this session (COPILOT_COORDINATOR=off).'
fi
MSG="$COORD ${MSG:+$MSG }Preserve native capacity, exclusive ownership and one convergence owner."

$JQ -cn --arg context "$MSG" \
  '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$context}}'

exit 0
