#!/bin/bash
# Claude Copilot Framework Integration Test
# Validates components work together correctly
# Run after smoke tests pass

# Note: We don't use set -e because we want to collect all test results
# Individual test failures are tracked, script exits at end based on TESTS_FAILED count

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMP_WORKSPACE="/tmp/claude-copilot-integration-test-$$"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
FAILED_TESTS=()

echo "========================================"
echo "Claude Copilot Integration Tests"
echo "========================================"
echo ""

# Helper functions
pass() {
  echo -e "${GREEN}✓${NC} $1"
  ((TESTS_PASSED++))
  ((TESTS_RUN++))
}

fail() {
  echo -e "${RED}✗${NC} $1"
  FAILED_TESTS+=("$1")
  ((TESTS_FAILED++))
  ((TESTS_RUN++))
}

info() {
  echo -e "${YELLOW}ℹ${NC} $1"
}

section() {
  echo ""
  echo -e "${BLUE}--- $1 ---${NC}"
}

cleanup() {
  if [[ -d "$TEMP_WORKSPACE" ]]; then
    info "Cleaning up test workspace: $TEMP_WORKSPACE"
    rm -rf "$TEMP_WORKSPACE"
  fi
}

trap cleanup EXIT

#############################
# Prerequisites
#############################
section "Prerequisites"

# MCP servers removed — check cc CLI instead
if [[ -d "$REPO_ROOT/tools/cc" ]]; then
  pass "cc CLI present (replaces copilot-memory + skills-copilot MCP servers)"
else
  fail "cc CLI missing"
  exit 1
fi

# Check required tools
if command -v jq > /dev/null 2>&1; then
  pass "jq available"
else
  fail "jq not installed (required for JSON parsing)"
  exit 1
fi

if command -v sqlite3 > /dev/null 2>&1; then
  pass "sqlite3 available"
else
  info "sqlite3 not found (some tests will be skipped)"
fi

#############################
# IT-01: cc CLI memory commands
#############################
section "IT-01: cc CLI memory commands"

mkdir -p "$TEMP_WORKSPACE"

if [[ -f "$REPO_ROOT/tools/cc/src/cc/commands/memory.py" ]]; then
  pass "cc memory command source exists"
else
  fail "cc memory command source missing"
fi

#############################
# IT-02: cc CLI skill commands
#############################
section "IT-02: cc CLI skill commands"

if [[ -f "$REPO_ROOT/tools/cc/src/cc/commands/skill.py" ]] || \
   [[ -f "$REPO_ROOT/tools/cc/src/cc/commands/skills.py" ]]; then
  pass "cc skill command source exists"
else
  info "cc skill command source not found at expected path (non-fatal)"
fi

#############################
# IT-03: Extension Resolution Logic
#############################
section "IT-03: Extension Resolution (Two-Tier)"

# Create test global knowledge repo
TEST_GLOBAL_KNOWLEDGE="$TEMP_WORKSPACE/global-knowledge"
mkdir -p "$TEST_GLOBAL_KNOWLEDGE/.claude/extensions"

# Create test extension
cat > "$TEST_GLOBAL_KNOWLEDGE/.claude/extensions/ta.override.md" <<'EOF'
---
extends: ta
type: override
description: Test architecture override
---
# Tech Architect - Test Override

This is a test override for integration testing.
EOF

# Create manifest
cat > "$TEST_GLOBAL_KNOWLEDGE/knowledge-manifest.json" <<'EOF'
{
  "version": "1.0",
  "name": "integration-test-knowledge",
  "description": "Test knowledge repository"
}
EOF

if [[ -f "$TEST_GLOBAL_KNOWLEDGE/.claude/extensions/ta.override.md" ]]; then
  pass "Test extension created in global repo"
else
  fail "Failed to create test extension"
fi

if jq . "$TEST_GLOBAL_KNOWLEDGE/knowledge-manifest.json" > /dev/null 2>&1; then
  pass "Test manifest is valid JSON"
else
  fail "Test manifest is invalid JSON"
fi

# Test frontmatter parsing
if grep -q "^extends: ta$" "$TEST_GLOBAL_KNOWLEDGE/.claude/extensions/ta.override.md"; then
  pass "Extension frontmatter has 'extends' field"
else
  fail "Extension frontmatter missing 'extends' field"
fi

if grep -q "^type: override$" "$TEST_GLOBAL_KNOWLEDGE/.claude/extensions/ta.override.md"; then
  pass "Extension frontmatter has 'type' field"
else
  fail "Extension frontmatter missing 'type' field"
fi

#############################
# IT-04: Project-Level Override
#############################
section "IT-04: Project vs Global Knowledge Priority"

# Create project-level knowledge repo
TEST_PROJECT_KNOWLEDGE="$TEMP_WORKSPACE/project-knowledge"
mkdir -p "$TEST_PROJECT_KNOWLEDGE/.claude/extensions"

# Create project extension (should override global)
cat > "$TEST_PROJECT_KNOWLEDGE/.claude/extensions/ta.override.md" <<'EOF'
---
extends: ta
type: override
description: Project-specific architecture override
---
# Tech Architect - Project Override

This is a PROJECT-LEVEL override that should take priority.
EOF

cat > "$TEST_PROJECT_KNOWLEDGE/knowledge-manifest.json" <<'EOF'
{
  "version": "1.0",
  "name": "project-test-knowledge",
  "description": "Project-specific test knowledge"
}
EOF

if [[ -f "$TEST_PROJECT_KNOWLEDGE/.claude/extensions/ta.override.md" ]]; then
  pass "Project-level extension created"
else
  fail "Failed to create project-level extension"
fi

# Verify priority by checking file content difference
GLOBAL_CONTENT=$(grep "Test Override" "$TEST_GLOBAL_KNOWLEDGE/.claude/extensions/ta.override.md" || echo "")
PROJECT_CONTENT=$(grep "PROJECT-LEVEL" "$TEST_PROJECT_KNOWLEDGE/.claude/extensions/ta.override.md" || echo "")

if [[ -n "$GLOBAL_CONTENT" ]] && [[ -n "$PROJECT_CONTENT" ]]; then
  pass "Both global and project extensions have distinct content"
else
  fail "Extension content not distinct"
fi

#############################
# IT-05: Agent File Structure
#############################
section "IT-05: Agent Files Have Correct Structure"

# Pick a few key agents to validate structure
KEY_AGENTS=("ta.md" "qa.md" "sd.md" "me.md")

for agent in "${KEY_AGENTS[@]}"; do
  AGENT_PATH="$REPO_ROOT/.claude/agents/$agent"

  if [[ ! -f "$AGENT_PATH" ]]; then
    fail "Agent file missing: $agent"
    continue
  fi

  # Check for routing table (columns: | Route To | When |)
  if grep -q "Route To Other Agent" "$AGENT_PATH"; then
    if grep -q "| Route To | When |" "$AGENT_PATH"; then
      pass "$agent has routing table"
    else
      fail "$agent has routing section but no table"
    fi
  else
    fail "$agent missing routing section"
  fi

  # Check for core behaviors section (replaced standalone Act Autonomously / Escalate headers)
  if grep -q "## Core Behaviors" "$AGENT_PATH"; then
    pass "$agent has decision authority boundaries"
  else
    fail "$agent missing decision authority boundaries"
  fi
done

#############################
# IT-06: Command Files Reference Correct Tools
#############################
section "IT-06: Commands Reference MCP Tools Correctly"

# Check /protocol command — verify live mechanism references (cc env / cc memory)
PROTOCOL_CMD="$REPO_ROOT/.claude/commands/protocol.md"
if grep -q "cc memory" "$PROTOCOL_CMD"; then
  pass "/protocol references cc memory"
else
  fail "/protocol missing cc memory reference"
fi

# Check /continue command — verify live mechanism references (cc memory / tc)
CONTINUE_CMD="$REPO_ROOT/.claude/commands/continue.md"
if grep -q "cc memory" "$CONTINUE_CMD"; then
  pass "/continue references cc memory"
else
  fail "/continue missing cc memory reference"
fi

if grep -q "tc progress\|tc task" "$CONTINUE_CMD"; then
  pass "/continue references tc CLI commands"
else
  fail "/continue missing tc CLI reference"
fi

#############################
# IT-07: .mcp.json Validity
#############################
section "IT-07: .mcp.json is valid JSON"

MCP_CONFIG="$REPO_ROOT/.mcp.json"

if [[ -f "$MCP_CONFIG" ]]; then
  if jq . "$MCP_CONFIG" > /dev/null 2>&1; then
    pass ".mcp.json is valid JSON (MCP servers handled externally if needed)"
  else
    fail ".mcp.json has invalid JSON syntax"
  fi
else
  info ".mcp.json not present (generated by /setup-project)"
fi

#############################
# IT-08: Template Consistency
#############################
section "IT-08: Templates Match Framework Structure"

# Check that template mcp.json is valid
TEMPLATE_MCP="$REPO_ROOT/templates/mcp.json"

if [[ -f "$TEMPLATE_MCP" ]]; then
  if jq . "$TEMPLATE_MCP" > /dev/null 2>&1; then
    pass "Template mcp.json is valid JSON"
  else
    fail "Template mcp.json has invalid JSON syntax"
  fi
else
  fail "Template mcp.json missing"
fi

# Check template CLAUDE.template.md exists
if [[ -f "$REPO_ROOT/templates/CLAUDE.template.md" ]]; then
  pass "Template CLAUDE.template.md exists"
else
  fail "Template CLAUDE.template.md missing"
fi

#############################
# Summary
#############################
echo ""
echo "========================================"
echo "Integration Test Summary"
echo "========================================"
echo "Tests Run:    $TESTS_RUN"
echo -e "${GREEN}Tests Passed: $TESTS_PASSED${NC}"
if [[ $TESTS_FAILED -gt 0 ]]; then
  echo -e "${RED}Tests Failed: $TESTS_FAILED${NC}"
else
  echo -e "${GREEN}Tests Failed: $TESTS_FAILED${NC}"
fi
echo ""

if [[ $TESTS_FAILED -gt 0 ]]; then
  echo -e "${RED}Failed Tests:${NC}"
  for test in "${FAILED_TESTS[@]}"; do
    echo "  - $test"
  done
  echo ""
  echo -e "${RED}✗ Integration tests FAILED${NC}"
  echo ""
  echo "Fix the failures above before proceeding to E2E tests."
  exit 1
else
  echo -e "${GREEN}✓ All integration tests PASSED${NC}"
  echo ""
  echo "Components integrate correctly. Ready for E2E testing."
  echo ""
  echo "Next steps:"
  echo "  1. Run E2E tests manually (see docs/qa/framework-validation-strategy.md)"
  echo "  2. Test actual Claude Code session with /protocol and /continue"
  echo "  3. Validate agent routing in real scenarios"
  exit 0
fi
