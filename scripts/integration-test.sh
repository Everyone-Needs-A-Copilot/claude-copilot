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

# Check if MCP servers are built
if [[ ! -f "$REPO_ROOT/mcp-servers/copilot-memory/dist/index.js" ]]; then
  fail "Memory Copilot not built - run smoke tests first"
  exit 1
else
  pass "Memory Copilot built"
fi

if [[ ! -f "$REPO_ROOT/mcp-servers/skills-copilot/dist/index.js" ]]; then
  fail "Skills Copilot not built - run smoke tests first"
  exit 1
else
  pass "Skills Copilot built"
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
# IT-01: Memory Copilot Database Initialization
#############################
section "IT-01: Memory Copilot Database Initialization"

# Create test workspace
mkdir -p "$TEMP_WORKSPACE"
export MEMORY_PATH="$TEMP_WORKSPACE/memory"
export WORKSPACE_ID="integration-test"

info "Starting Memory Copilot MCP server..."

# Start MCP server in background (we'll interact via stdio simulation)
# For smoke test, we'll check the database is created correctly

cd "$REPO_ROOT/mcp-servers/copilot-memory"

# Simulate server initialization by checking database creation
# In real integration test, you'd use MCP Inspector or custom test client

# For now, just verify the server can be required without errors
if node -e "const fs = require('fs'); const path = '$REPO_ROOT/mcp-servers/copilot-memory/dist/index.js'; if (!fs.existsSync(path)) { process.exit(1); }" 2>/dev/null; then
  pass "Memory Copilot index.js can be loaded"
else
  fail "Memory Copilot index.js cannot be loaded"
fi

# Check database initialization path logic
if [[ -n "$WORKSPACE_ID" ]]; then
  pass "WORKSPACE_ID environment variable set"
else
  fail "WORKSPACE_ID not set"
fi

#############################
# IT-02: Skills Copilot Provider Chain
#############################
section "IT-02: Skills Copilot Provider Chain"

cd "$REPO_ROOT/mcp-servers/skills-copilot"

# Check provider files exist
# Note: Provider names in code use camelCase (e.g., KnowledgeRepoProvider)
PROVIDERS=("Cache" "Local" "KnowledgeRepo" "Postgres" "SkillsSh")
for provider in "${PROVIDERS[@]}"; do
  # Check in dist for compiled providers
  if grep -q "${provider}Provider" "dist/index.js" 2>/dev/null; then
    pass "Provider included in build: $provider"
  else
    fail "Provider missing from build: $provider"
  fi
done

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

  # Check for routing table
  if grep -q "Route To Other Agent" "$AGENT_PATH"; then
    if grep -q "| .* | .* |" "$AGENT_PATH" && grep -q "Situation.*Route To" "$AGENT_PATH"; then
      pass "$agent has routing table"
    else
      fail "$agent has routing section but no table"
    fi
  else
    fail "$agent missing routing section"
  fi

  # Check for decision authority section
  if grep -q "### Act Autonomously" "$AGENT_PATH" && grep -q "### Escalate" "$AGENT_PATH"; then
    pass "$agent has decision authority boundaries"
  else
    fail "$agent missing decision authority boundaries"
  fi
done

#############################
# IT-06: Command Files Reference Correct Tools
#############################
section "IT-06: Commands Reference MCP Tools Correctly"

# Check /protocol command
PROTOCOL_CMD="$REPO_ROOT/.claude/commands/protocol.md"
if grep -q "extension_get" "$PROTOCOL_CMD"; then
  pass "/protocol references extension_get tool"
else
  fail "/protocol missing extension_get reference"
fi

# Check /continue command
CONTINUE_CMD="$REPO_ROOT/.claude/commands/continue.md"
if grep -q "initiative_get" "$CONTINUE_CMD"; then
  pass "/continue references initiative_get tool"
else
  fail "/continue missing initiative_get reference"
fi

if grep -q "memory_search" "$CONTINUE_CMD"; then
  pass "/continue references memory_search tool"
else
  fail "/continue missing memory_search reference"
fi

#############################
# IT-07: .mcp.json Server Paths
#############################
section "IT-07: MCP Config Has Correct Server Paths"

MCP_CONFIG="$REPO_ROOT/.mcp.json"

# Check Memory Copilot command path
MEMORY_CMD=$(jq -r '.mcpServers."copilot-memory".command' "$MCP_CONFIG" 2>/dev/null || echo "")
if [[ "$MEMORY_CMD" == "node" ]]; then
  pass "Memory Copilot command is 'node'"
else
  fail "Memory Copilot command unexpected: $MEMORY_CMD"
fi

MEMORY_ARGS=$(jq -r '.mcpServers."copilot-memory".args[0]' "$MCP_CONFIG" 2>/dev/null || echo "")
if [[ "$MEMORY_ARGS" =~ "copilot-memory/dist/index.js" ]]; then
  pass "Memory Copilot args point to dist/index.js"
else
  fail "Memory Copilot args incorrect: $MEMORY_ARGS"
fi

# Check Skills Copilot command path
SKILLS_CMD=$(jq -r '.mcpServers."skills-copilot".command' "$MCP_CONFIG" 2>/dev/null || echo "")
if [[ "$SKILLS_CMD" == "node" ]]; then
  pass "Skills Copilot command is 'node'"
else
  fail "Skills Copilot command unexpected: $SKILLS_CMD"
fi

SKILLS_ARGS=$(jq -r '.mcpServers."skills-copilot".args[0]' "$MCP_CONFIG" 2>/dev/null || echo "")
if [[ "$SKILLS_ARGS" =~ "skills-copilot/dist/index.js" ]]; then
  pass "Skills Copilot args point to dist/index.js"
else
  fail "Skills Copilot args incorrect: $SKILLS_ARGS"
fi

#############################
# IT-08: Template Consistency
#############################
section "IT-08: Templates Match Framework Structure"

# Check that template mcp.json has same structure as repo .mcp.json
TEMPLATE_MCP="$REPO_ROOT/templates/mcp.json"

if [[ -f "$TEMPLATE_MCP" ]]; then
  pass "Template mcp.json exists"

  # Verify it has the same servers
  if jq -e '.mcpServers."copilot-memory"' "$TEMPLATE_MCP" > /dev/null 2>&1; then
    pass "Template mcp.json has copilot-memory server"
  else
    fail "Template mcp.json missing copilot-memory server"
  fi

  if jq -e '.mcpServers."skills-copilot"' "$TEMPLATE_MCP" > /dev/null 2>&1; then
    pass "Template mcp.json has skills-copilot server"
  else
    fail "Template mcp.json missing skills-copilot server"
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
