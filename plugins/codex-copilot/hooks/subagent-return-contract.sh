#!/bin/bash
# Codex SubagentStart hook: keep delegated results decision-sized.

JQ="$(command -v jq 2>/dev/null || true)"
[ -n "$JQ" ] || exit 0

MSG='Return at most three sentences: outcome, root cause if known, and any anomaly or decision. Put full evidence in a file and give its path.'

$JQ -cn --arg context "$MSG" \
  '{hookSpecificOutput:{hookEventName:"SubagentStart",additionalContext:$context}}'

exit 0
