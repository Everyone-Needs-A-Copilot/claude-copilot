#!/usr/bin/env bash
# test-shim-e2e.sh — End-to-end proof for item 1 (enforcement travels):
# a scratch project, vendored ONLY with the shim (no rule scripts, no
# security-rules.json, nothing else), registered via `cc settings-hook add`
# against THIS machine's real global install, must actually block a direct
# Edit under an active /freeze -- the exact case that cannot fire today in
# any of the 46 projects with materialized agents but no wired hooks.
#
# This is deliberately the ONE assertion that proves the whole chain in a
# single shot: matcher (simulated by calling copilot-hook.sh directly, the
# way settings.json's registered command does) -> shim -> resolution ->
# COPILOT_HOOK_STATE_DIR -> the real, global rule_path_scope() -> deny.
#
# Run: bash tests/hooks/test-shim-e2e.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
SHIM_SOURCE="$PROJECT_ROOT/.claude/hooks/copilot-hook.sh"

PASS=0
FAIL=0
ok()   { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

echo "=== test-shim-e2e.sh: vendored shim delegates to the real global rules ==="
echo ""

if [[ ! -x "$SHIM_SOURCE" ]]; then
  fail "shim source not found or not executable: $SHIM_SOURCE"
  echo ""; echo "Results: $PASS passed, $FAIL failed"; exit 1
fi

SCRATCH="$(mktemp -d)"
cleanup() { rm -rf "$SCRATCH"; }
trap cleanup EXIT

PROJECT="$SCRATCH/consuming-project"
mkdir -p "$PROJECT/.claude/hooks" "$PROJECT/scoped" "$PROJECT/outside"
cp "$SHIM_SOURCE" "$PROJECT/.claude/hooks/copilot-hook.sh"
chmod 755 "$PROJECT/.claude/hooks/copilot-hook.sh"
cd "$PROJECT" && git init -q && git config user.email t@example.invalid && git config user.name t
cd "$PROJECT"

# ---------------------------------------------------------------------------
# 1. Sanity: the project directory carries ONLY the shim under .claude/hooks
#    -- no pretool-check.sh, no bin/, no security-rules.json. If the deny
#    below still fires, it can only be because the shim reached the GLOBAL
#    install, not a local copy.
# ---------------------------------------------------------------------------
if [[ -f "$PROJECT/.claude/hooks/pretool-check.sh" ]]; then
  fail "test setup bug: a rule script leaked into the scratch project"
else
  ok "scratch project carries only the shim -- no vendored rule scripts"
fi

# ---------------------------------------------------------------------------
# 2. Turn /freeze on, scoped to scratch/consuming-project/scoped, via the
#    REAL global freeze.sh -- exactly what a session's own /freeze command
#    would invoke -- with COPILOT_HOOK_STATE_DIR pointed at this project's
#    own state dir (mirrors what the shim itself sets before delegating).
# ---------------------------------------------------------------------------
export CLAUDE_PROJECT_DIR="$PROJECT"
export COPILOT_HOOK_STATE_DIR="$PROJECT/.claude/hooks/state"
mkdir -p "$COPILOT_HOOK_STATE_DIR"
GLOBAL_HOOKS_ROOT="$PROJECT_ROOT/.claude/hooks"
bash "$GLOBAL_HOOKS_ROOT/bin/freeze.sh" on "$PROJECT/scoped" >/dev/null

if [[ -f "$COPILOT_HOOK_STATE_DIR/.freeze" ]]; then
  ok "/freeze wrote its state file under THIS project's own state dir (per-project state)"
else
  fail "/freeze did not write state under COPILOT_HOOK_STATE_DIR"
fi

# ---------------------------------------------------------------------------
# 3. The one assertion that proves the whole chain: a direct Edit OUTSIDE
#    the frozen directory, delivered to the vendored shim exactly the way
#    settings.json's registered PreToolUse command would deliver it, must
#    be denied by the GLOBAL rule_path_scope() -- unreachable without a
#    working matcher -> shim -> resolution -> state-dir chain.
# ---------------------------------------------------------------------------
PAYLOAD='{"session_id":"e2e-shim","tool_name":"Edit","tool_input":{"file_path":"'"$PROJECT"'/outside/file.md"}}'
STDOUT="$(printf '%s' "$PAYLOAD" | COPILOT_HOOKS_ROOT="$GLOBAL_HOOKS_ROOT" bash "$PROJECT/.claude/hooks/copilot-hook.sh" pretool-check)"
EXIT=$?

if [[ "$EXIT" -eq 2 ]]; then
  ok "Edit outside the frozen directory is denied (exit 2) through the vendored shim"
else
  fail "expected exit 2 (deny), got exit $EXIT"
fi
if printf '%s' "$STDOUT" | grep -q '"permissionDecision":"deny"'; then
  ok "deny JSON has the expected permissionDecision field"
else
  fail "stdout did not contain a deny JSON: $STDOUT"
fi

# ---------------------------------------------------------------------------
# 4. Symmetric control: the SAME Edit, INSIDE the frozen directory, is
#    allowed -- proves this is /freeze's real logic firing, not a blanket
#    deny.
# ---------------------------------------------------------------------------
PAYLOAD_INSIDE='{"session_id":"e2e-shim","tool_name":"Edit","tool_input":{"file_path":"'"$PROJECT"'/scoped/file.md"}}'
printf '%s' "$PAYLOAD_INSIDE" | COPILOT_HOOKS_ROOT="$GLOBAL_HOOKS_ROOT" bash "$PROJECT/.claude/hooks/copilot-hook.sh" pretool-check >/dev/null
EXIT_INSIDE=$?
if [[ "$EXIT_INSIDE" -eq 0 ]]; then
  ok "Edit inside the frozen directory is allowed (exit 0) through the vendored shim"
else
  fail "expected exit 0 (allow) inside the frozen dir, got exit $EXIT_INSIDE"
fi

# ---------------------------------------------------------------------------
# 5. Fail-open, unreachable install, non-Bash tool.
# ---------------------------------------------------------------------------
PAYLOAD_READ='{"session_id":"e2e-shim","tool_name":"Read","tool_input":{}}'
printf '%s' "$PAYLOAD_READ" | COPILOT_HOOKS_ROOT=/nonexistent bash "$PROJECT/.claude/hooks/copilot-hook.sh" pretool-check >/dev/null 2>/tmp/shim-e2e-stderr
EXIT_UNREACHABLE_READ=$?
if [[ "$EXIT_UNREACHABLE_READ" -eq 0 ]] && grep -q "enforcement is unavailable" /tmp/shim-e2e-stderr; then
  ok "unreachable install + Read: fails open (exit 0) with a non-silent stderr diagnostic"
else
  fail "unreachable install + Read: expected exit 0 with a diagnostic, got exit $EXIT_UNREACHABLE_READ"
fi

# ---------------------------------------------------------------------------
# 6. Fail-closed, unreachable install, Bash tool (the destructive-command
#    guard's own tool) -- deny, not silent allow.
# ---------------------------------------------------------------------------
PAYLOAD_BASH='{"session_id":"e2e-shim","tool_name":"Bash","tool_input":{"command":"echo hi"}}'
printf '%s' "$PAYLOAD_BASH" | COPILOT_HOOKS_ROOT=/nonexistent bash "$PROJECT/.claude/hooks/copilot-hook.sh" pretool-check >/dev/null 2>/tmp/shim-e2e-stderr-bash
EXIT_UNREACHABLE_BASH=$?
if [[ "$EXIT_UNREACHABLE_BASH" -eq 2 ]]; then
  ok "unreachable install + Bash: fails closed (exit 2) -- the destructive-command guard is never silently absent"
else
  fail "unreachable install + Bash: expected exit 2 (deny), got exit $EXIT_UNREACHABLE_BASH"
fi

rm -f /tmp/shim-e2e-stderr /tmp/shim-e2e-stderr-bash

# ---------------------------------------------------------------------------
# 7. VERIFY-B Defect 3 — ambiguous/unparseable stdin during an unreachable
#    install must take the SAME fail-closed path as a known Bash call, not
#    fail open. The bug: the python except-handler printed the literal
#    sentinel "__unknown__" (non-empty), which never matched the bash-side
#    `[[ -z "$tool_name" ]]` check meant to catch exactly this case, so
#    ambiguous payloads fell through to _exit_open (exit 0) with zero
#    enforcement -- the opposite of the documented "bias toward Bash on
#    ambiguity."
# ---------------------------------------------------------------------------
STDERR_TMP="$SCRATCH/stderr-ambiguous"

assert_ambiguous_fails_closed() {
  local label="$1" stdin_payload="$2"
  local exit_code
  printf '%s' "$stdin_payload" | COPILOT_HOOKS_ROOT=/nonexistent bash "$PROJECT/.claude/hooks/copilot-hook.sh" pretool-check >/dev/null 2>"$STDERR_TMP"
  exit_code=$?
  if [[ "$exit_code" -eq 2 ]]; then
    ok "ambiguous stdin ($label): fails closed (exit 2), same path as a known Bash call"
  else
    fail "ambiguous stdin ($label): expected exit 2 (fail closed, assumed Bash), got exit $exit_code"
  fi
}

assert_ambiguous_fails_closed "empty stdin" ""
assert_ambiguous_fails_closed "malformed JSON" 'not json at all {{{'
assert_ambiguous_fails_closed "JSON array, not an object" '[1,2,3]'
assert_ambiguous_fails_closed "non-string tool_name" '{"session_id":"s1","tool_name":123}'

rm -f "$STDERR_TMP"

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
