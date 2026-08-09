#!/usr/bin/env bash
# test-hook-wiring.sh — Static wiring-contract test for the PreToolUse hook
#
# ROOT CAUSE THIS GUARDS AGAINST:
# Claude Code filters which tool calls even invoke a PreToolUse hook process
# based on the registered "matcher" in .claude/settings.json, BEFORE the hook
# script ever runs. If pretool-check.sh branches on a tool name the matcher
# never admits, that branch is unreachable in production even though it is
# internally correct — and even though tests/hooks/test-pretool-check.sh,
# which invokes the script directly with a synthetic payload, will happily
# exercise it. That is exactly how the Read/Edit/Agent legs of
# rule_force_delegate/rule_qa_gate, and the Write leg of rule_path_scope
# (/freeze), shipped dead for months while dozens of payload-level assertions
# passed.
#
# This test is deliberately STATIC. It never invokes pretool-check.sh. It
# parses the registered matcher out of settings.json and the tool names each
# rule function branches on out of pretool-check.sh's source text, then
# asserts the script's tool set is a SUBSET of the matcher's tool set —
# i.e. every tool a rule can possibly act on is actually delivered to it.
#
# Run: bash tests/hooks/test-hook-wiring.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
SETTINGS_FILE="$PROJECT_ROOT/.claude/settings.json"
HOOK_SCRIPT="$PROJECT_ROOT/.claude/hooks/pretool-check.sh"
JQ="/usr/bin/jq"

PASS=0
FAIL=0

ok()   { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

echo "=== test-hook-wiring.sh: PreToolUse matcher/branch static contract ==="
echo ""

if [[ ! -f "$SETTINGS_FILE" ]]; then
  fail "settings file not found: $SETTINGS_FILE"
  echo ""; echo "Results: $PASS passed, $FAIL failed"; exit 1
fi
if [[ ! -f "$HOOK_SCRIPT" ]]; then
  fail "hook script not found: $HOOK_SCRIPT"
  echo ""; echo "Results: $PASS passed, $FAIL failed"; exit 1
fi

# ---------------------------------------------------------------------------
# 1. Parse the registered PreToolUse matcher into a set of tool names.
# ---------------------------------------------------------------------------
MATCHER_RAW="$("$JQ" -r '.hooks.PreToolUse[0].matcher // empty' "$SETTINGS_FILE" 2>/dev/null)"
if [[ -z "$MATCHER_RAW" ]]; then
  fail "could not read .hooks.PreToolUse[0].matcher from $SETTINGS_FILE (empty or missing)"
  echo ""; echo "Results: $PASS passed, $FAIL failed"; exit 1
fi
ok "registered PreToolUse matcher: \"$MATCHER_RAW\""

MATCHER_TOOLS_FILE="$(mktemp)"
tr '|' '\n' <<< "$MATCHER_RAW" | sed '/^[[:space:]]*$/d' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sort -u > "$MATCHER_TOOLS_FILE"

# ---------------------------------------------------------------------------
# 2. Statically extract every tool name pretool-check.sh branches on, paired
#    with the source line it was found on (tool:lineno). Two shapes are
#    handled, both keyed on the literal shell variable TOOL_NAME (this
#    hook's local convention for the parsed tool_name field):
#      a) case "$TOOL_NAME" in Foo|Bar) ... ;; *) ... ;; esac
#      b) [[ "$TOOL_NAME" == "Foo" ]]  /  [[ "$TOOL_NAME" != "Foo" ]]
#    The awk pass for (a) scans line-by-line between "case ... in" and the
#    matching "esac" rather than assuming the alternation lives at a fixed
#    offset, so it tolerates reasonable reformatting (blank lines, comments,
#    multi-line case bodies).
# ---------------------------------------------------------------------------
PAIRS_FILE="$(mktemp)"

# 2a. case "$TOOL_NAME" in ...) blocks -> "Tool:lineno"
awk '
  /case[ \t]+"\$TOOL_NAME"[ \t]+in/ { in_case = 1; next }
  in_case && /esac/ { in_case = 0; next }
  in_case {
    line = $0
    sub(/^[ \t]+/, "", line)
    if (line ~ /^\*\)/) next
    if (match(line, /^[A-Za-z_][A-Za-z_|]*\)/)) {
      pat = substr(line, RSTART, RLENGTH - 1)
      n = split(pat, arr, "|")
      for (i = 1; i <= n; i++) print arr[i] ":" FNR
    }
  }
' "$HOOK_SCRIPT" >> "$PAIRS_FILE"

# 2b. [[ "$TOOL_NAME" == "Foo" ]] / != "Foo" comparisons -> "Tool:lineno"
grep -noE '"\$TOOL_NAME"[[:space:]]*(==|!=)[[:space:]]*"[A-Za-z_]+"' "$HOOK_SCRIPT" \
  | while IFS=: read -r lineno match; do
      name="$(sed -E 's/.*"([A-Za-z_]+)"$/\1/' <<< "$match")"
      echo "${name}:${lineno}"
    done >> "$PAIRS_FILE"

if [[ ! -s "$PAIRS_FILE" ]]; then
  fail "static scan found zero TOOL_NAME-keyed branches in $HOOK_SCRIPT — extraction is broken (this test has a bug, not necessarily the hook)"
  echo ""; echo "Results: $PASS passed, $FAIL failed"; exit 1
fi

SCRIPT_TOOLS_FILE="$(mktemp)"
cut -d: -f1 "$PAIRS_FILE" | sort -u > "$SCRIPT_TOOLS_FILE"
ok "script tool-name branches found: $(tr '\n' ',' < "$SCRIPT_TOOLS_FILE" | sed 's/,$//')"

# ---------------------------------------------------------------------------
# 2c. Map each source line to its enclosing function (this file's rule_*
#     functions and helpers are declared as "name() {" at column 0), so
#     failures below can name "function @ line" instead of a bare line
#     number.
# ---------------------------------------------------------------------------
FUNC_STARTS_FILE="$(mktemp)"
grep -noE '^[A-Za-z_][A-Za-z0-9_]*\(\)[[:space:]]*\{' "$HOOK_SCRIPT" \
  | sed -E 's/^([0-9]+):([A-Za-z_][A-Za-z0-9_]*)\(\).*/\1:\2/' > "$FUNC_STARTS_FILE"

enclosing_function() {
  local target_line="$1"
  awk -F: -v target="$target_line" '
    $1 <= target { fn = $2 }
    END { print (fn == "" ? "(top level)" : fn) }
  ' "$FUNC_STARTS_FILE"
}

# ---------------------------------------------------------------------------
# 3. Assert: script's tool set is a subset of the matcher's tool set.
#    Any tool name a rule branches on that the matcher does not admit is a
#    silently-unreachable branch — fail loudly, name it, and point at the
#    function/line so this doesn't repeat the "shipped dead for months"
#    failure mode.
# ---------------------------------------------------------------------------
UNREACHABLE_FILE="$(mktemp)"
comm -23 "$SCRIPT_TOOLS_FILE" "$MATCHER_TOOLS_FILE" > "$UNREACHABLE_FILE"

if [[ -s "$UNREACHABLE_FILE" ]]; then
  fail "script branches on tool names the registered matcher never delivers — these branches are DEAD CODE in production:"
  while IFS= read -r tool; do
    echo "         - \"$tool\":"
    grep "^${tool}:" "$PAIRS_FILE" | cut -d: -f2 | sort -un | while read -r ln; do
      echo "             line ${ln}, function $(enclosing_function "$ln")()"
    done
  done < "$UNREACHABLE_FILE"
  echo ""
  echo "  Registered matcher tool set    : $(tr '\n' ',' < "$MATCHER_TOOLS_FILE" | sed 's/,$//')"
  echo "  Script-implemented tool set    : $(tr '\n' ',' < "$SCRIPT_TOOLS_FILE" | sed 's/,$//')"
  echo "  Unreachable (script - matcher) : $(tr '\n' ',' < "$UNREACHABLE_FILE" | sed 's/,$//')"
  echo ""
  echo "  Fix: widen .hooks.PreToolUse[0].matcher in $SETTINGS_FILE to include"
  echo "  the unreachable tool name(s) above, or remove the dead branch if it"
  echo "  is genuinely no longer needed."
else
  ok "script's tool-name branch set is a subset of the registered matcher — no unreachable branches"
fi

# ---------------------------------------------------------------------------
# 4. Informational (non-failing): matcher admits tools no branch handles.
#    Dead permissiveness, not dead enforcement — worth flagging, not itself
#    a failure.
# ---------------------------------------------------------------------------
EXTRA_FILE="$(mktemp)"
comm -13 "$SCRIPT_TOOLS_FILE" "$MATCHER_TOOLS_FILE" > "$EXTRA_FILE"
if [[ -s "$EXTRA_FILE" ]]; then
  echo "  INFO: matcher admits tool(s) no rule in pretool-check.sh currently branches on (harmless, informational): $(tr '\n' ',' < "$EXTRA_FILE" | sed 's/,$//')"
fi

rm -f "$MATCHER_TOOLS_FILE" "$SCRIPT_TOOLS_FILE" "$PAIRS_FILE" "$FUNC_STARTS_FILE" "$UNREACHABLE_FILE" "$EXTRA_FILE"

# ---------------------------------------------------------------------------
# 5. Item 1's shim path: `cc settings-hook add` / `_claude_setup()` register
#    a SEPARATE copy of this same matcher string (mutations.py's
#    DEFAULT_HOOK_ENTRIES) into every consuming project's own
#    settings.json, via the vendored copilot-hook.sh shim rather than a
#    direct pretool-check.sh path. This static check proves invariants 3/4
#    above ONLY for THIS repo's own settings.json — the whole point of the
#    shim is that a project's registered matcher is a byte-for-byte COPY of
#    that string, not independently re-derived. If the two ever drift, a
#    consuming project could register a matcher that admits fewer (or
#    different) tool names than the one just proven correct above, silently
#    reintroducing the "shipped dead for months" failure mode one level
#    removed. Fail loudly here rather than let that coupling go unchecked.
# ---------------------------------------------------------------------------
MUTATIONS_FILE="$PROJECT_ROOT/tools/cc/src/cc/core/ecosystem/mutations.py"
if [[ ! -f "$MUTATIONS_FILE" ]]; then
  fail "mutations.py not found: $MUTATIONS_FILE"
else
  SHIM_MATCHER="$(grep -A1 '"PreToolUse"' "$MUTATIONS_FILE" | grep -oE '"[A-Za-z|]+"' | sed -n '2p' | tr -d '"')"
  if [[ -z "$SHIM_MATCHER" ]]; then
    fail "could not extract DEFAULT_HOOK_ENTRIES' PreToolUse matcher from $MUTATIONS_FILE"
  elif [[ "$SHIM_MATCHER" == "$MATCHER_RAW" ]]; then
    ok "DEFAULT_HOOK_ENTRIES' PreToolUse matcher (\"$SHIM_MATCHER\") matches this repo's own registered matcher — the shim path inherits the same coverage proven above"
  else
    fail "DEFAULT_HOOK_ENTRIES' PreToolUse matcher (\"$SHIM_MATCHER\") in $MUTATIONS_FILE has drifted from this repo's registered matcher (\"$MATCHER_RAW\") in $SETTINGS_FILE — every project registered via the shim would get the DRIFTED matcher, not the one this test just verified"
  fi
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
