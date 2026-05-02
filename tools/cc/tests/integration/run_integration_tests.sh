#!/usr/bin/env bash
# run_integration_tests.sh — quick integration smoke-tests for the cc CLI.
#
# Usage:
#   bash run_integration_tests.sh [project_dir]
#
# If project_dir is given, cd into it first (must be a git repo).
# Defaults to the current directory.
#
# Works in both bash and zsh.

set -euo pipefail

# ---------------------------------------------------------------------------
# Color helpers (only when stdout is a terminal)
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    RESET='\033[0m'
else
    RED='' GREEN='' YELLOW='' RESET=''
fi

pass()  { printf "${GREEN}PASS${RESET}  %s\n" "$1"; }
fail()  { printf "${RED}FAIL${RESET}  %s\n" "$1"; FAILURES=$((FAILURES + 1)); }
info()  { printf "${YELLOW}INFO${RESET}  %s\n" "$1"; }
section() { printf "\n%s\n%s\n" "$1" "$(printf '%0.s-' {1..60})"; }

FAILURES=0

# ---------------------------------------------------------------------------
# Change to project directory if given
# ---------------------------------------------------------------------------
if [ "${1:-}" != "" ]; then
    cd "$1"
fi

PROJECT_DIR="$(pwd)"
info "Running integration tests from: $PROJECT_DIR"

# Verify we're in a git repo
if ! git rev-parse --show-toplevel > /dev/null 2>&1; then
    printf "${RED}ERROR${RESET}  Not inside a git repository. cd into a project first.\n"
    exit 1
fi

CC="/Users/pabs/.local/bin/cc"

# Verify cc exists
if [ ! -x "$CC" ]; then
    printf "${RED}ERROR${RESET}  cc binary not found at $CC\n"
    exit 1
fi

# ---------------------------------------------------------------------------
# Test: Installation
# ---------------------------------------------------------------------------
section "Installation"

if $CC --version > /dev/null 2>&1; then
    pass "cc --version"
else
    fail "cc --version (exit code: $?)"
fi

if bash -c "command -v cc" > /dev/null 2>&1; then
    pass "cc on PATH"
else
    fail "cc on PATH"
fi

# ---------------------------------------------------------------------------
# Test: Config
# ---------------------------------------------------------------------------
section "Config"

if $CC config list > /dev/null 2>&1; then
    pass "cc config list"
else
    fail "cc config list (exit code: $?)"
fi

if $CC config list --scope machine > /dev/null 2>&1; then
    pass "cc config list --scope machine"
else
    fail "cc config list --scope machine"
fi

# ---------------------------------------------------------------------------
# Test: Env
# ---------------------------------------------------------------------------
section "Env"

ENV_OUTPUT="$($CC env 2>&1)"
if [ $? -eq 0 ]; then
    pass "cc env exits 0"
else
    fail "cc env exits non-zero"
fi

if echo "$ENV_OUTPUT" | grep -q "^export "; then
    pass "cc env output contains 'export '"
else
    fail "cc env output does not contain any 'export ' lines"
    info "Output was: $ENV_OUTPUT"
fi

# ---------------------------------------------------------------------------
# Test: Memory store, search, list, delete
# ---------------------------------------------------------------------------
section "Memory"

UNIQUE_CONTENT="integration test entry $(date '+%Y%m%d%H%M%S') pid$$"

STORE_OUTPUT="$($CC memory store --type context --tags cc-integration-test --json "$UNIQUE_CONTENT" 2>&1)"
STORE_EXIT=$?

if [ $STORE_EXIT -eq 0 ]; then
    pass "cc memory store"
else
    fail "cc memory store (exit code: $STORE_EXIT)"
    info "Output: $STORE_OUTPUT"
fi

# Extract ID from JSON output
ENTRY_ID=""
if echo "$STORE_OUTPUT" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['id'])" > /dev/null 2>&1; then
    ENTRY_ID="$(echo "$STORE_OUTPUT" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['id'])")"
    ENTRY_PATH="$(echo "$STORE_OUTPUT" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['path'])")"
    pass "cc memory store output is valid JSON with id"
else
    fail "cc memory store output is not valid JSON or missing id"
    info "Output: $STORE_OUTPUT"
fi

# Verify file created on disk
if [ -n "$ENTRY_PATH" ] && [ -f "$ENTRY_PATH" ]; then
    pass "cc memory store creates .md file"
else
    fail "cc memory store: .md file not found at expected path"
    info "Expected path: ${ENTRY_PATH:-unknown}"
fi

# Verify frontmatter
if [ -n "$ENTRY_PATH" ] && [ -f "$ENTRY_PATH" ]; then
    if head -1 "$ENTRY_PATH" | grep -q "^---"; then
        pass "entry .md file has YAML frontmatter"
    else
        fail "entry .md file missing YAML frontmatter"
    fi
fi

# Search for the entry
# NOTE: capture output first then grep — piping directly into grep causes rich to
# raise BrokenPipeError (broken pipe) and cc exits 1 when run with set -o pipefail.
UNIQUE_WORD="pid$$"
SEARCH_OUTPUT="$($CC memory search "$UNIQUE_WORD" 2>&1)" || true
if echo "$SEARCH_OUTPUT" | grep -q "$UNIQUE_WORD"; then
    pass "cc memory search finds entry"
else
    fail "cc memory search: entry not found by keyword"
    info "Search output: $SEARCH_OUTPUT"
fi

# List entries
if $CC memory list --type context 2>&1 | grep -q "cc-integration-test"; then
    pass "cc memory list shows entry"
else
    fail "cc memory list: entry tag not visible in output"
fi

# Check .gitignore
MEMORY_GITIGNORE="$(git rev-parse --show-toplevel)/.claude/memory/.gitignore"
if [ -f "$MEMORY_GITIGNORE" ] && grep -q "memory.db" "$MEMORY_GITIGNORE"; then
    pass ".claude/memory/.gitignore contains memory.db"
else
    fail ".claude/memory/.gitignore missing or does not contain memory.db"
fi

# Check entries dir
ENTRIES_DIR="$(git rev-parse --show-toplevel)/.claude/memory/entries"
if [ -d "$ENTRIES_DIR" ]; then
    pass ".claude/memory/entries/ directory exists"
else
    fail ".claude/memory/entries/ directory not found"
fi

# Delete the entry
if [ -n "$ENTRY_ID" ]; then
    DELETE_OUTPUT="$($CC memory delete --yes "$ENTRY_ID" 2>&1)"
    DELETE_EXIT=$?
    if [ $DELETE_EXIT -eq 0 ]; then
        pass "cc memory delete exits 0"
    else
        fail "cc memory delete (exit code: $DELETE_EXIT)"
        info "Output: $DELETE_OUTPUT"
    fi

    # Verify file is gone
    if [ -n "$ENTRY_PATH" ] && [ ! -f "$ENTRY_PATH" ]; then
        pass "cc memory delete removes .md file"
    else
        fail "cc memory delete: .md file still exists at $ENTRY_PATH"
    fi
else
    info "Skipping delete test — no entry id available"
fi

# ---------------------------------------------------------------------------
# Test: Skills
# ---------------------------------------------------------------------------
section "Skills"

if $CC skill list > /dev/null 2>&1; then
    pass "cc skill list exits 0"
else
    fail "cc skill list (exit code: $?)"
fi

# ---------------------------------------------------------------------------
# Test: Migration
# ---------------------------------------------------------------------------
section "Migration"

if $CC memory migrate --status > /dev/null 2>&1; then
    pass "cc memory migrate --status exits 0"
else
    fail "cc memory migrate --status (exit code: $?)"
fi

# ---------------------------------------------------------------------------
# Test: MCP shim
# ---------------------------------------------------------------------------
section "MCP"

MCP_OUTPUT="$($CC mcp config 2>&1)"
MCP_EXIT=$?
if [ $MCP_EXIT -eq 0 ]; then
    pass "cc mcp config exits 0"
else
    fail "cc mcp config (exit code: $MCP_EXIT)"
fi

if echo "$MCP_OUTPUT" | python3 -c "import sys, json; json.load(sys.stdin)" > /dev/null 2>&1; then
    pass "cc mcp config output is valid JSON"
else
    fail "cc mcp config output is not valid JSON"
    info "Output: $MCP_OUTPUT"
fi

if echo "$MCP_OUTPUT" | python3 -c "import sys, json; d=json.load(sys.stdin); assert 'cc' in d" > /dev/null 2>&1; then
    pass "cc mcp config JSON has 'cc' key"
else
    fail "cc mcp config JSON missing 'cc' key"
fi

# ---------------------------------------------------------------------------
# Cleanup — delete any leftover integration test entries
# ---------------------------------------------------------------------------
section "Cleanup"

LEFTOVER_OUTPUT="$($CC memory list --json 2>/dev/null || echo '[]')"
if echo "$LEFTOVER_OUTPUT" | python3 -c "
import sys, json
entries = json.load(sys.stdin)
leftovers = [e for e in entries if 'cc-integration-test' in e.get('tags', [])]
for e in leftovers:
    print(e['id'])
" > /tmp/cc_integration_leftover_ids.txt 2>/dev/null; then
    while IFS= read -r leftover_id; do
        if [ -n "$leftover_id" ]; then
            /Users/pabs/.local/bin/cc memory delete --yes "$leftover_id" > /dev/null 2>&1 || true
            info "Cleaned up leftover entry: $leftover_id"
        fi
    done < /tmp/cc_integration_leftover_ids.txt
    rm -f /tmp/cc_integration_leftover_ids.txt
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\n"
printf '%0.s=' {1..60}
printf "\n"

if [ $FAILURES -eq 0 ]; then
    printf "${GREEN}All tests passed!${RESET}\n"
    exit 0
else
    printf "${RED}${FAILURES} test(s) failed.${RESET}\n"
    exit 1
fi
