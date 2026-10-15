#!/usr/bin/env bash
# test-security-rules-urls.sh — credential-URL and database-URL rules in
# .claude/hooks/security-rules.json, exercised through the real hook and its
# jq test($pat;"i") path (no reimplementation of the regex).
#
# True positives (URLs with embedded credentials) must stay blocked; ordinary
# commands that merely contain a "://", a ":" and an "@" must not.
#
# Run: bash tests/hooks/test-security-rules-urls.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
HOOK="$PROJECT_ROOT/.claude/hooks/pretool-check.sh"
RULES="$PROJECT_ROOT/.claude/hooks/security-rules.json"
JQ_BIN="/usr/bin/jq"
SESSION="test-urls-$$"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/security-rules-urls.XXXXXX")"
trap 'rm -rf "$WORK"; rm -f "$PROJECT_ROOT/.claude/hooks/state/budget-${SESSION}."* 2>/dev/null || true' EXIT
: > "$WORK/transcript.jsonl"

PASS=0
FAIL=0
ok()   { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

# Prints the hook exit code for a Bash command (2 = blocked).
hook_exit() {
  local payload code=0
  payload="$("$JQ_BIN" -cn --arg s "$SESSION" --arg c "$1" --arg t "$WORK/transcript.jsonl" \
    '{session_id:$s, tool_name:"Bash", transcript_path:$t, tool_input:{command:$c}}')"
  bash "$HOOK" <<< "$payload" >/dev/null 2>&1 || code=$?
  echo "$code"
}

# Prints the names of the block rules whose patterns match the command (jq path
# identical to rule_destructive_command in pretool-check.sh).
matching_rules() {
  "$JQ_BIN" -r --arg cmd "$1" '
    [.rules[] | select(.enabled == true and .action == "block") | . as $rule |
     $rule.patterns[] as $pat | select(($cmd | test($pat; "i")) == true) | $rule.id] | unique | join(",")
  ' "$RULES"
}

expect_blocked() {
  local cmd="$1" rule="$2" got
  got="$(matching_rules "$cmd")"
  if [[ ",$got," == *",$rule,"* && "$(hook_exit "$cmd")" == "2" ]]; then ok "blocked ($rule): $cmd"; else fail "should block ($rule), matched [$got]: $cmd"; fi
}

expect_allowed_by() {
  local cmd="$1" rule="$2" got
  got="$(matching_rules "$cmd")"
  if [[ ",$got," != *",$rule,"* ]]; then ok "$rule does not fire: $cmd"; else fail "$rule false positive: $cmd"; fi
}

echo "== true positives stay blocked =="
expect_blocked 'curl https://user:pass@host.example.com/x' credential-url
expect_blocked 'curl http://a:b@x.io/p' credential-url
expect_blocked 'git clone https://deploy:s3cr3t-token@github.com/org/repo.git' credential-url
expect_blocked 'psql postgres://admin:hunter22@db.internal:5432/app' secret-detection
expect_blocked 'mysql --url mysql://root:rootpw@127.0.0.1/db' secret-detection
expect_blocked 'mongosh mongodb://svc:p4ss@cluster0.example.net/test' secret-detection

echo "== observed false positives no longer fire =="
expect_allowed_by 'curl https://example.com/a?t=10:30 -H "x: me@b.com"' credential-url
expect_allowed_by "git log --format='%an <%ae>' https://h/x" credential-url
expect_allowed_by 'curl https://example.com/api && echo "ratio 1:2 mail me@example.com"' credential-url
expect_allowed_by 'psql postgres://localhost:5432/mydb -c "select 1" # ping me@example.com' secret-detection
expect_allowed_by 'echo mysql://localhost:3306/db; ssh -o X=1:2 git@github.com' secret-detection
expect_allowed_by 'echo mongodb://localhost:27017 note: contact ops@example.com' secret-detection

echo "== ordinary commands still run through the hook =="
if [[ "$(hook_exit 'curl https://example.com/a?t=10:30 -H "x: me@b.com"')" == "0" ]]; then ok "benign URL command allowed end to end"; else fail "benign URL command was blocked"; fi

echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
