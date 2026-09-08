#!/bin/bash
# Codex UserPromptSubmit hook: emit one short routing nudge only when needed.
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

[ -n "$MSG" ] || exit 0

$JQ -cn --arg context "$MSG" \
  '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$context}}'

exit 0
