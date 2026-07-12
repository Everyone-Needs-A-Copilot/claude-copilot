#!/bin/bash
# Test Knowledge Sync Scripts
# Validates the knowledge sync implementation without modifying anything

set -e

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_PASSED=0
TESTS_FAILED=0

echo ""
echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}Knowledge Sync Test Suite${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

# Test helper functions
pass() {
    echo -e "${GREEN}✓ $1${NC}"
    # NOTE: `((TESTS_PASSED++))` is a bash gotcha under `set -e` — the
    # post-increment expression evaluates to the OLD (falsy, when 0) value,
    # so `set -e` aborts the whole script on the very first pass(). Use
    # arithmetic assignment instead, which always "succeeds".
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

fail() {
    echo -e "${RED}✗ $1${NC}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

# Test 1: Scripts exist
echo "Test 1: Verify scripts exist"
if [ -f "$SCRIPT_DIR/extract-release-changes.sh" ]; then
    pass "extract-release-changes.sh exists"
else
    fail "extract-release-changes.sh missing"
fi

if [ -f "$SCRIPT_DIR/update-product-knowledge.sh" ]; then
    pass "update-product-knowledge.sh exists"
else
    fail "update-product-knowledge.sh missing"
fi

if [ -f "$SCRIPT_DIR/sync-knowledge.sh" ]; then
    pass "sync-knowledge.sh exists"
else
    fail "sync-knowledge.sh missing"
fi

echo ""

# Test 2: Scripts are executable
echo "Test 2: Verify scripts are executable"
if [ -x "$SCRIPT_DIR/extract-release-changes.sh" ]; then
    pass "extract-release-changes.sh is executable"
else
    fail "extract-release-changes.sh not executable"
fi

if [ -x "$SCRIPT_DIR/update-product-knowledge.sh" ]; then
    pass "update-product-knowledge.sh is executable"
else
    fail "update-product-knowledge.sh not executable"
fi

if [ -x "$SCRIPT_DIR/sync-knowledge.sh" ]; then
    pass "sync-knowledge.sh is executable"
else
    fail "sync-knowledge.sh not executable"
fi

echo ""

# Test 3: Scripts have valid syntax
echo "Test 3: Verify script syntax"
if bash -n "$SCRIPT_DIR/extract-release-changes.sh"; then
    pass "extract-release-changes.sh syntax valid"
else
    fail "extract-release-changes.sh syntax error"
fi

if bash -n "$SCRIPT_DIR/update-product-knowledge.sh"; then
    pass "update-product-knowledge.sh syntax valid"
else
    fail "update-product-knowledge.sh syntax error"
fi

if bash -n "$SCRIPT_DIR/sync-knowledge.sh"; then
    pass "sync-knowledge.sh syntax valid"
else
    fail "sync-knowledge.sh syntax error"
fi

echo ""

# Test 4: Help messages work
echo "Test 4: Verify help messages"
if "$SCRIPT_DIR/extract-release-changes.sh" --help >/dev/null 2>&1; then
    pass "extract-release-changes.sh --help works"
else
    fail "extract-release-changes.sh --help failed"
fi

if "$SCRIPT_DIR/update-product-knowledge.sh" --help >/dev/null 2>&1; then
    pass "update-product-knowledge.sh --help works"
else
    fail "update-product-knowledge.sh --help failed"
fi

if "$SCRIPT_DIR/sync-knowledge.sh" --help >/dev/null 2>&1; then
    pass "sync-knowledge.sh --help works"
else
    fail "sync-knowledge.sh --help failed"
fi

echo ""

# Test 5: Hook template exists
echo "Test 5: Verify hook template"
HOOK_TEMPLATE="$SCRIPT_DIR/../../templates/hooks/post-tag"
if [ -f "$HOOK_TEMPLATE" ]; then
    pass "post-tag hook template exists"
else
    fail "post-tag hook template missing"
fi

if [ -f "$HOOK_TEMPLATE" ] && bash -n "$HOOK_TEMPLATE"; then
    pass "post-tag hook syntax valid"
else
    fail "post-tag hook syntax error"
fi

echo ""

# Test 6: Command exists
echo "Test 6: Verify setup command"
SETUP_CMD="$SCRIPT_DIR/../../.claude/commands/setup-knowledge-sync.md"
if [ -f "$SETUP_CMD" ]; then
    pass "setup-knowledge-sync.md exists"
else
    fail "setup-knowledge-sync.md missing"
fi

echo ""

# Test 7: Extract changes from this repo (if tags exist)
echo "Test 7: Test extraction (if tags exist)"
cd "$SCRIPT_DIR/../.."  # Go to repo root

if git describe --tags --abbrev=0 >/dev/null 2>&1; then
    LATEST_TAG=$(git describe --tags --abbrev=0)
    echo "  Testing with tag: $LATEST_TAG"

    # Test markdown output
    if "$SCRIPT_DIR/extract-release-changes.sh" --to-tag "$LATEST_TAG" >/dev/null 2>&1; then
        pass "Extract changes (markdown) works"
    else
        fail "Extract changes (markdown) failed"
    fi

    # Test JSON output
    if "$SCRIPT_DIR/extract-release-changes.sh" --to-tag "$LATEST_TAG" --format json >/dev/null 2>&1; then
        pass "Extract changes (json) works"
    else
        fail "Extract changes (json) failed"
    fi
else
    echo -e "${YELLOW}  Skipped (no tags in repository)${NC}"
fi

echo ""

# Test 8: install-extensions.py exists, is syntactically valid, and --help works
echo "Test 8: Verify install-extensions.py"
if [ -f "$SCRIPT_DIR/install-extensions.py" ]; then
    pass "install-extensions.py exists"
else
    fail "install-extensions.py missing"
fi

if command -v python3 &>/dev/null && python3 -m py_compile "$SCRIPT_DIR/install-extensions.py" 2>/dev/null; then
    pass "install-extensions.py compiles"
else
    fail "install-extensions.py failed to compile"
fi

if command -v python3 &>/dev/null && python3 "$SCRIPT_DIR/install-extensions.py" --help >/dev/null 2>&1; then
    pass "install-extensions.py --help works"
else
    fail "install-extensions.py --help failed"
fi

echo ""

# Test 9: sync-knowledge.sh calls install-extensions.py (Step 3 is wired in)
echo "Test 9: Verify sync-knowledge.sh invokes the extension installer"
if grep -q "install-extensions.py" "$SCRIPT_DIR/sync-knowledge.sh"; then
    pass "sync-knowledge.sh references install-extensions.py"
else
    fail "sync-knowledge.sh does not invoke install-extensions.py"
fi

echo ""

# Test 10: End-to-end fixture test — install, idempotence, update, removal
echo "Test 10: End-to-end extension install (fixture)"

if command -v python3 &>/dev/null; then
    FIXTURE_DIR="$(mktemp -d)"
    trap 'rm -rf "$FIXTURE_DIR"' EXIT

    mkdir -p "$FIXTURE_DIR/kr/.claude/extensions"
    mkdir -p "$FIXTURE_DIR/project/.claude/agents"

    cat > "$FIXTURE_DIR/kr/knowledge-manifest.json" <<'JSON'
{
  "extensions": [
    { "agent": "cw", "type": "extension", "file": ".claude/extensions/cw.extension.md", "description": "fixture" }
  ]
}
JSON

    cat > "$FIXTURE_DIR/kr/.claude/extensions/cw.extension.md" <<'MD'
---
extends: cw
type: extension
description: fixture
---

Fixture extension body v1.
MD

    cat > "$FIXTURE_DIR/project/.claude/agents/cw.md" <<'MD'
---
name: cw
description: fixture agent
---

Base agent body.
MD

    python3 "$SCRIPT_DIR/install-extensions.py" \
        --project-root "$FIXTURE_DIR/project" \
        --knowledge-repo "$FIXTURE_DIR/kr" >/dev/null

    if grep -q "kc-extension:begin name=cw" "$FIXTURE_DIR/project/.claude/agents/cw.md" && \
       grep -q "Fixture extension body v1." "$FIXTURE_DIR/project/.claude/agents/cw.md" && \
       grep -q "Base agent body." "$FIXTURE_DIR/project/.claude/agents/cw.md"; then
        pass "extension content installed inside fenced markers, base body preserved"
    else
        fail "extension content not installed correctly"
    fi

    BEFORE_HASH="$(shasum -a 256 "$FIXTURE_DIR/project/.claude/agents/cw.md" | awk '{print $1}')"
    python3 "$SCRIPT_DIR/install-extensions.py" \
        --project-root "$FIXTURE_DIR/project" \
        --knowledge-repo "$FIXTURE_DIR/kr" >/dev/null
    AFTER_HASH="$(shasum -a 256 "$FIXTURE_DIR/project/.claude/agents/cw.md" | awk '{print $1}')"

    if [ "$BEFORE_HASH" = "$AFTER_HASH" ]; then
        pass "re-run is idempotent (no diff)"
    else
        fail "re-run produced a diff (not idempotent)"
    fi

    cat > "$FIXTURE_DIR/kr/.claude/extensions/cw.extension.md" <<'MD'
---
extends: cw
type: extension
description: fixture
---

Fixture extension body v2 CHANGED.
MD

    python3 "$SCRIPT_DIR/install-extensions.py" \
        --project-root "$FIXTURE_DIR/project" \
        --knowledge-repo "$FIXTURE_DIR/kr" >/dev/null

    BLOCK_COUNT="$(grep -c "kc-extension:begin" "$FIXTURE_DIR/project/.claude/agents/cw.md")"
    if grep -q "Fixture extension body v2 CHANGED." "$FIXTURE_DIR/project/.claude/agents/cw.md" && [ "$BLOCK_COUNT" -eq 1 ]; then
        pass "changed extension updates the block in place (no duplication)"
    else
        fail "changed extension did not update cleanly"
    fi

    python3 "$SCRIPT_DIR/install-extensions.py" \
        --project-root "$FIXTURE_DIR/project" \
        --knowledge-repo "$FIXTURE_DIR/kr" --remove >/dev/null

    if ! grep -q "kc-extension" "$FIXTURE_DIR/project/.claude/agents/cw.md" && \
       grep -q "Base agent body." "$FIXTURE_DIR/project/.claude/agents/cw.md"; then
        pass "--remove cleanly strips the block and preserves the base agent body"
    else
        fail "--remove did not clean up correctly"
    fi

    rm -rf "$FIXTURE_DIR"
    trap - EXIT
else
    echo -e "${YELLOW}  Skipped (python3 not available)${NC}"
fi

echo ""

# Summary
echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}Test Summary${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Run /setup-knowledge-sync in a project"
    echo "  2. Create a test tag: git tag v0.0.1-test"
    echo "  3. Verify knowledge sync runs"
    exit 0
else
    echo -e "${RED}Some tests failed${NC}"
    exit 1
fi
