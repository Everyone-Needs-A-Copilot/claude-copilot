#!/usr/bin/env bash
# test-pre-compact-handoff.sh — PreCompact handoff hook (gap plan A9).
# Real tc database in a temp project, fake transcript, hook driven by stdin.
# Run: bash tests/hooks/test-pre-compact-handoff.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
HOOK="$PROJECT_ROOT/.claude/hooks/pre-compact-handoff.sh"
PASS=0; FAIL=0
ok()   { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

echo "=== test-pre-compact-handoff.sh ==="
command -v tc &>/dev/null || { echo "  SKIP: tc not on PATH"; exit 0; }

SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT
P="$SCRATCH/proj"; mkdir -p "$P/src"
cd "$P" && git init -q
tc init >/dev/null 2>&1
tc prd create --title "Handoff PRD" --json >/dev/null
tc task create --title "Handoff task" --prd 1 --description $'First paragraph.\n\nSecond paragraph.' --json >/dev/null
cat > contract.json <<'J'
{"schemaVersion":2,"criteria":[{"id":"C1","expected":"does a"},{"id":"C2","expected":"does b"}],"sources":["src"],"doneBlock":"stop at two","excluded":["no live calls"],"assumptions":["stubs"]}
J
tc task contract 1 --file contract.json --json >/dev/null
tc task update 1 --status in_progress --json >/dev/null
tc wp store --task 1 --type qa --title "QA packet" --json \
  --content $'CRITERION: C1\nEXPECTED: does a\nOBSERVED: ok\nARTIFACT: test-run|pytest x exit=0 "3 passed"\nVERDICT: APPROVED' >/dev/null

cat > "$SCRATCH/t.jsonl" <<'J'
{"type":"user","message":{"role":"user","content":"owner one"}}
{"type":"assistant","message":{"content":[{"type":"text","text":"ok"}]}}
{"type":"user","message":{"role":"user","content":"owner two"}}
{"type":"user","message":{"role":"user","content":"owner three"}}
J

payload() { printf '{"session_id":"abcdef123456","transcript_path":"%s","cwd":"%s","hook_event_name":"PreCompact","trigger":"auto","custom_instructions":""}' "$SCRATCH/t.jsonl" "$1"; }

payload "$P" | bash "$HOOK" 2>"$SCRATCH/err"; RC=$?
[[ $RC -eq 0 ]] && ok "exit 0 with a task" || fail "exit $RC"
F="$(ls "$P"/.copilot/handoffs/*-abcdef12.md 2>/dev/null | head -1)"
[[ -n "$F" ]] && ok "handoff file named <stamp>-<session8>.md" || { fail "no handoff file"; F=/dev/null; }
[[ "$(head -1 "$F")" == '**Kickoff:** Read this file, then continue from "Remaining" item 1. Do not re-verify items under "Verified".' ]] && ok "line 1 is the Kickoff line" || fail "line 1 not Kickoff"
for H in 'Outcome being pursued:' 'Verified:' 'Governing decisions:' 'Remaining:' 'Evidence:' 'Last owner messages:'; do
  grep -qF "**$H**" "$F" && ok "heading $H" || fail "heading $H missing"
done
for M in "owner one" "owner two" "owner three"; do grep -qF "$M" "$F" && ok "owner message: $M" || fail "missing owner message: $M"; done
grep -q 'Handoff task' "$F" && grep -q 'First paragraph' "$F" && ! grep -q 'Second paragraph' "$F" && grep -q 'Handoff PRD' "$F" && ok "outcome: title, first paragraph only, PRD title" || fail "outcome content"
grep -q 'VERDICT: APPROVED' "$F" && grep -q 'ARTIFACT: test-run' "$F" && ok "verified carries VERDICT and ARTIFACT" || fail "verified content"
grep -q 'criterion C2 not yet approved' "$F" && ! grep -q 'criterion C1 not yet' "$F" && ok "remaining lists only the uncovered criterion" || fail "remaining content"
grep -q 'stop at two' "$F" && grep -q 'no live calls' "$F" && ok "governing decisions from the contract" || fail "decisions content"
grep -q 'WP-1' "$F" && grep -qF "$SCRATCH/t.jsonl" "$F" && ok "evidence: work product and transcript" || fail "evidence content"
[[ "$(tc wp list --task 1 --type handoff --json | jq length)" == "1" ]] && ok "handoff work product stored" || fail "handoff work product not stored"
grep -q 'handoff written' "$SCRATCH/err" && ok "stderr names the file" || fail "stderr note missing"
[[ "$(grep -c '' "$F")" -lt 30 ]] && ok "no hard-wrapped prose (short file)" || fail "unexpected length"

# Session match beats recency: second task is newer, but the log stamps the session on task 1.
tc task create --title "Newer task" --json >/dev/null
tc task update 2 --status in_progress --json >/dev/null
sqlite3 .copilot/tasks.db "UPDATE agent_log SET details='{\"session\":\"zzzzzzzz-1\"}' WHERE task_id=2; UPDATE agent_log SET details='{\"session\":\"abcdef123456\"}' WHERE task_id=1;"
sleep 1
payload "$P" | bash "$HOOK" 2>/dev/null
LAST="$(ls -t "$P"/.copilot/handoffs/*.md | head -1)"
grep -q 'Handoff task' "$LAST" && ! grep -q 'Newer task' "$LAST" && ok "task chosen by session id over recency" || fail "session matching"

# No task: file still written with owner messages and transcript path.
N="$SCRATCH/notask"; mkdir -p "$N/.copilot"
payload "$N" | bash "$HOOK" 2>/dev/null; RC=$?
NF="$(ls "$N"/.copilot/handoffs/*.md 2>/dev/null | head -1)"
[[ $RC -eq 0 && -n "$NF" ]] && grep -q 'owner three' "$NF" && grep -qF "$SCRATCH/t.jsonl" "$NF" && ok "no task: file written with owner messages and transcript" || fail "no-task handoff"

# cwd without .copilot: exit 0.
W="$SCRATCH/plain"; mkdir -p "$W"
payload "$W" | bash "$HOOK" 2>/dev/null; [[ $? -eq 0 ]] && ok "exit 0 on cwd without .copilot" || fail "nonzero without .copilot"

# Empty stdin and garbage: exit 0, nothing written.
E="$SCRATCH/empty"; mkdir -p "$E"
(cd "$E" && bash "$HOOK" </dev/null 2>/dev/null); [[ $? -eq 0 ]] && ok "exit 0 on empty stdin" || fail "nonzero on empty stdin"
(cd "$E" && echo 'not json' | bash "$HOOK" 2>/dev/null); [[ $? -eq 0 && ! -d "$E/.copilot" ]] && ok "exit 0 on garbage stdin, nothing written" || fail "garbage stdin"

echo ""; echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
