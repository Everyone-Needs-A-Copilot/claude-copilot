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
    ((TESTS_PASSED++))
}

fail() {
    echo -e "${RED}✗ $1${NC}"
    ((TESTS_FAILED++))
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
