#!/usr/bin/env bash
# test-single-registration.sh — every framework hook handler is registered once per event.
#
# ROOT CAUSE THIS GUARDS AGAINST: .claude/settings.json registered both the direct
# script (session-start.sh) and the copilot-hook.sh shim for the same event. The shim
# delegates to the very same script, so the handler ran twice per event and the
# guardrails message was injected twice in a headless `claude -p` session.
#
# For each event, each handler is identified by its script name, whether the command
# names the script directly or passes the event name to copilot-hook.sh
# (session-start, pretool-check, ... are both the shim argument and the script basename).
# Fails if any (event, handler) pair is reached more than once.
#
# Run: bash tests/hooks/test-single-registration.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
SETTINGS_FILE="${1:-$PROJECT_ROOT/.claude/settings.json}"
PASS=0; FAIL=0
ok()   { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

echo "=== test-single-registration.sh ==="
if [[ ! -f "$SETTINGS_FILE" ]]; then
  fail "settings file not found: $SETTINGS_FILE"; echo "Results: $PASS passed, $FAIL failed"; exit 1
fi

out="$(python3 - "$SETTINGS_FILE" <<'PY'
import json, re, sys
from collections import defaultdict
hooks = json.load(open(sys.argv[1])).get("hooks", {})
bad = 0
for event, groups in hooks.items():
    seen = defaultdict(list)
    for g in groups:
        for h in g.get("hooks", []):
            cmd = h.get("command", "")
            m = re.search(r'copilot-hook\.sh"?\s+([a-z][a-z-]*)', cmd) or re.search(r'/([a-z][a-z-]*)\.sh"?\s*$', cmd)
            if m:
                seen[m.group(1)].append(cmd)
    for handler, cmds in seen.items():
        if len(cmds) > 1:
            bad += 1
            print(f"FAIL: {event}: handler '{handler}' reached {len(cmds)} times: " + " | ".join(cmds))
        else:
            print(f"PASS: {event}: handler '{handler}' registered once")
sys.exit(1 if bad else 0)
PY
)"
rc=$?
while IFS= read -r line; do
  case "$line" in PASS:*) ok "${line#PASS: }";; FAIL:*) fail "${line#FAIL: }";; esac
done <<< "$out"
[[ $rc -ne 0 && $FAIL -eq 0 ]] && fail "registration scan errored"

echo ""; echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -gt 0 ]] && exit 1
exit 0
