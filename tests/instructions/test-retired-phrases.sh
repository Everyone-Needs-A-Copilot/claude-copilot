#!/usr/bin/env bash
# test-retired-phrases.sh — instruction fitness check for the consolidated
# execution-limit and approval rules (PRD-12). Fails when any agent or command
# file carries a retired rule phrase that contradicted, or duplicated without
# enforcing, what `tc execution` now enforces in code.
#
# Usage: bash tests/instructions/test-retired-phrases.sh [REPO_ROOT]
# Includes a negative control: a file carrying a retired phrase must be rejected.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${1:-$(dirname "$(dirname "$SCRIPT_DIR")")}"

RETIRED=(
  "Debug-spiral circuit breaker"
  "three consecutive unsuccessful"
  "max 3 iterations"
  "warn after 3 iterations"
  "Warns if >5 continuations"
  "Blocks if >10 continuations"
  "Auto-proceed at checkpoints - ALWAYS wait"
  "CRITICAL: Explicit approval required.** No auto-proceed."
)

PASS=0
FAIL=0
ok()   { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

# Prints "file: phrase" for each retired phrase found in the given paths.
scan() {
  local phrase
  for phrase in "${RETIRED[@]}"; do
    grep -rnF --include='*.md' -- "$phrase" "$@" 2>/dev/null | sed "s|^|retired phrase [$phrase]: |"
  done
}

TARGETS=()
for d in "$ROOT/.claude/agents" "$ROOT/.claude/commands"; do
  [[ -d "$d" ]] && TARGETS+=("$d")
done
[[ ${#TARGETS[@]} -gt 0 ]] || { echo "FATAL: no .claude/agents or .claude/commands under $ROOT" >&2; exit 1; }

HITS="$(scan "${TARGETS[@]}")"
if [[ -z "$HITS" ]]; then
  ok "no retired approval/limit phrases in agents and commands"
else
  fail "retired phrases remain:"
  echo "$HITS" | sed 's/^/    /'
fi

# Negative control: the lint must reject a file that still carries the old rule.
CONTROL="$(mktemp -d "${TMPDIR:-/tmp}/retired-phrases.XXXXXX")"
trap 'rm -rf "$CONTROL"' EXIT
printf '**Debug-spiral circuit breaker.** After three consecutive unsuccessful fix attempts.\n' > "$CONTROL/agent.md"
if [[ -n "$(scan "$CONTROL")" ]]; then
  ok "negative control: a file carrying the retired rule is rejected"
else
  fail "negative control: the lint failed to flag a retired phrase"
fi

echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
