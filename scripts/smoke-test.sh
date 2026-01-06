#!/bin/bash
# Claude Copilot Framework Smoke Test
# Validates core components work in isolation
# Run this before committing framework changes

# Note: We don't use set -e because we want to collect all test results
# Individual test failures are tracked, script exits at end based on TESTS_FAILED count

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMP_DIR="/tmp/claude-copilot-smoke-test-$$"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Test result tracking
FAILED_TESTS=()

echo "========================================"
echo "Claude Copilot Framework Smoke Test"
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
  echo "--- $1 ---"
}

cleanup() {
  if [[ -d "$TEMP_DIR" ]]; then
    rm -rf "$TEMP_DIR"
  fi
}

# Cleanup on exit
trap cleanup EXIT

# Create temp directory
mkdir -p "$TEMP_DIR"

#############################
# ST-01: File Structure
#############################
section "ST-01: File Structure"

# Check MCP servers
if [[ -f "$REPO_ROOT/mcp-servers/copilot-memory/package.json" ]]; then
  pass "Memory Copilot package.json exists"
else
  fail "Memory Copilot package.json missing"
fi

if [[ -f "$REPO_ROOT/mcp-servers/skills-copilot/package.json" ]]; then
  pass "Skills Copilot package.json exists"
else
  fail "Skills Copilot package.json missing"
fi

# Check agents
AGENT_COUNT=$(find "$REPO_ROOT/.claude/agents" -name "*.md" -type f | wc -l | tr -d ' ')
if [[ "$AGENT_COUNT" -eq 13 ]]; then
  pass "All 13 agents present"
else
  fail "Agent count mismatch: expected 13, found $AGENT_COUNT"
fi

# Check commands
REQUIRED_COMMANDS=("protocol.md" "continue.md" "setup-project.md" "update-project.md" "update-copilot.md" "knowledge-copilot.md")
for cmd in "${REQUIRED_COMMANDS[@]}"; do
  if [[ -f "$REPO_ROOT/.claude/commands/$cmd" ]]; then
    pass "Command exists: $cmd"
  else
    fail "Command missing: $cmd"
  fi
done

#############################
# ST-02: Agent File Validity
#############################
section "ST-02: Agent File Validity"

for agent_file in "$REPO_ROOT/.claude/agents"/*.md; do
  agent_name=$(basename "$agent_file")

  # Check frontmatter exists (YAML block between --- markers)
  if grep -q "^---$" "$agent_file"; then
    pass "$agent_name has frontmatter"
  else
    fail "$agent_name missing frontmatter"
  fi

  # Check required sections
  if grep -q "## Core Behaviors" "$agent_file"; then
    pass "$agent_name has Core Behaviors section"
  else
    fail "$agent_name missing Core Behaviors section"
  fi

  if grep -q "## Route To Other Agent" "$agent_file"; then
    pass "$agent_name has routing section"
  else
    fail "$agent_name missing routing section"
  fi

  if grep -q "## Task Copilot Integration" "$agent_file"; then
    pass "$agent_name has Task Copilot Integration section"
  else
    fail "$agent_name missing Task Copilot Integration section"
  fi
done

#############################
# ST-03: MCP Config Validity
#############################
section "ST-03: MCP Configuration"

# Skip .mcp.json checks in CI environments (file is gitignored)
if [[ -n "$CI" ]]; then
  info ".mcp.json check skipped (CI environment, file is gitignored)"
elif [[ -f "$REPO_ROOT/.mcp.json" ]]; then
  pass ".mcp.json exists"

  # Validate JSON syntax
  if jq . "$REPO_ROOT/.mcp.json" > /dev/null 2>&1; then
    pass ".mcp.json is valid JSON"

    # Check for required servers
    if jq -e '.mcpServers."copilot-memory"' "$REPO_ROOT/.mcp.json" > /dev/null 2>&1; then
      pass "copilot-memory server configured"
    else
      fail "copilot-memory server not configured"
    fi

    if jq -e '.mcpServers."skills-copilot"' "$REPO_ROOT/.mcp.json" > /dev/null 2>&1; then
      pass "skills-copilot server configured"
    else
      fail "skills-copilot server not configured"
    fi
  else
    fail ".mcp.json has invalid JSON syntax"
  fi
else
  info ".mcp.json not found (run /setup-project to create)"
fi

#############################
# ST-04: Memory Copilot Build
#############################
section "ST-04: Memory Copilot MCP Server"

cd "$REPO_ROOT/mcp-servers/copilot-memory"

# Check dependencies installed
if [[ -d "node_modules" ]]; then
  pass "Memory Copilot dependencies installed"
else
  info "Installing Memory Copilot dependencies..."
  npm install > /dev/null 2>&1
  if [[ $? -eq 0 ]]; then
    pass "Memory Copilot dependencies installed"
  else
    fail "Memory Copilot npm install failed"
  fi
fi

# Check TypeScript build
info "Building Memory Copilot..."
npm run build > /dev/null 2>&1
if [[ $? -eq 0 ]]; then
  pass "Memory Copilot builds successfully"
else
  fail "Memory Copilot build failed"
fi

# Check dist output
if [[ -f "dist/index.js" ]]; then
  pass "Memory Copilot dist/index.js generated"
else
  fail "Memory Copilot dist/index.js missing"
fi

# Check dist output has required tools
if grep -q "memory_store" "dist/index.js"; then
  pass "memory_store tool present"
else
  fail "memory_store tool missing from build"
fi

if grep -q "initiative_start" "dist/index.js"; then
  pass "initiative_start tool present"
else
  fail "initiative_start tool missing from build"
fi

#############################
# ST-05: Skills Copilot Build
#############################
section "ST-05: Skills Copilot MCP Server"

cd "$REPO_ROOT/mcp-servers/skills-copilot"

# Check dependencies installed
if [[ -d "node_modules" ]]; then
  pass "Skills Copilot dependencies installed"
else
  info "Installing Skills Copilot dependencies..."
  npm install > /dev/null 2>&1
  if [[ $? -eq 0 ]]; then
    pass "Skills Copilot dependencies installed"
  else
    fail "Skills Copilot npm install failed"
  fi
fi

# Check TypeScript build
info "Building Skills Copilot..."
npm run build > /dev/null 2>&1
if [[ $? -eq 0 ]]; then
  pass "Skills Copilot builds successfully"
else
  fail "Skills Copilot build failed"
fi

# Check dist output
if [[ -f "dist/index.js" ]]; then
  pass "Skills Copilot dist/index.js generated"
else
  fail "Skills Copilot dist/index.js missing"
fi

# Check dist output has required tools
if grep -q "skill_get" "dist/index.js"; then
  pass "skill_get tool present"
else
  fail "skill_get tool missing from build"
fi

if grep -q "knowledge_search" "dist/index.js"; then
  pass "knowledge_search tool present"
else
  fail "knowledge_search tool missing from build"
fi

if grep -q "extension_get" "dist/index.js"; then
  pass "extension_get tool present"
else
  fail "extension_get tool missing from build"
fi

#############################
# ST-06: Documentation
#############################
section "ST-06: Documentation"

cd "$REPO_ROOT"

# Check core docs
if [[ -f "README.md" ]]; then
  pass "README.md exists"
else
  fail "README.md missing"
fi

if [[ -f "CLAUDE.md" ]]; then
  pass "CLAUDE.md exists"
else
  fail "CLAUDE.md missing"
fi

if [[ -f "SETUP.md" ]]; then
  pass "SETUP.md exists"
else
  fail "SETUP.md missing"
fi

if [[ -f "docs/EXTENSION-SPEC.md" ]]; then
  pass "EXTENSION-SPEC.md exists"
else
  fail "EXTENSION-SPEC.md missing"
fi

# Check no broken links in CLAUDE.md
if grep -q "See \[.*\](.*)" "CLAUDE.md"; then
  # Extract all markdown links and check if files exist
  # This is a simplified check - could be expanded
  pass "CLAUDE.md has markdown links (manual verification recommended)"
fi

#############################
# ST-07: No Time Estimates
#############################
section "ST-07: Time Estimate Policy Compliance"

# Check if audit script exists
if [[ -f "$REPO_ROOT/scripts/audit-time-language.sh" ]]; then
  pass "Time estimate audit script exists"

  # Run audit (only on agent files for smoke test)
  info "Running time estimate audit on agent files..."
  AUDIT_OUTPUT=$("$REPO_ROOT/scripts/audit-time-language.sh" 2>&1 || true)

  # Check for violations ONLY in .claude/agents/ files
  # Filter to only count violations from agent files (not docs, commands, or templates)
  AGENT_VIOLATIONS=$(echo "$AUDIT_OUTPUT" | grep -B 1 "VIOLATION" | grep "File: .claude/agents/" || true)
  VIOLATION_COUNT=$(echo "$AGENT_VIOLATIONS" | grep -c "File: .claude/agents/" || true)

  if [[ "$VIOLATION_COUNT" -eq 0 ]]; then
    pass "No time estimate violations in agent files"
  else
    fail "Found $VIOLATION_COUNT time estimate violations in agent files"
  fi
else
  info "Time estimate audit script not found (skipping)"
fi

#############################
# ST-08: Template Files
#############################
section "ST-08: Template Files"

if [[ -d "$REPO_ROOT/templates" ]]; then
  pass "Templates directory exists"

  # Check for key templates
  TEMPLATE_COUNT=$(find "$REPO_ROOT/templates" -type f | wc -l | tr -d ' ')
  if [[ "$TEMPLATE_COUNT" -gt 0 ]]; then
    pass "Template files present ($TEMPLATE_COUNT files)"
  else
    fail "Templates directory empty"
  fi
else
  fail "Templates directory missing"
fi

#############################
# Summary
#############################
echo ""
echo "========================================"
echo "Smoke Test Summary"
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
  echo -e "${RED}✗ Smoke tests FAILED${NC}"
  exit 1
else
  echo -e "${GREEN}✓ All smoke tests PASSED${NC}"
  echo ""
  echo "Framework is ready for use. Run integration tests next:"
  echo "  (Integration test script to be created)"
  exit 0
fi
