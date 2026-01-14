#!/bin/bash

# Test Runner: Agent and Skill Framework Tests
#
# Runs all tests related to agent invocation, skill loading, and orchestration workflows.
# Excludes legacy tests and codebase mapping tests.
#
# Usage:
#   ./run-agent-tests.sh           # Run all agent/skill tests
#   ./run-agent-tests.sh --unit    # Run unit tests only
#   ./run-agent-tests.sh --int     # Run integration tests only

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
TOTAL=0
PASSED=0
FAILED=0

# Functions
run_test() {
  local test_file=$1
  local test_name=$(basename "$test_file" .test.ts)

  echo -e "${BLUE}Running: ${test_name}${NC}"
  TOTAL=$((TOTAL + 1))

  if npx tsx "$test_file"; then
    PASSED=$((PASSED + 1))
    echo -e "${GREEN}✅ ${test_name} PASSED${NC}\n"
  else
    FAILED=$((FAILED + 1))
    echo -e "${RED}❌ ${test_name} FAILED${NC}\n"
  fi
}

print_summary() {
  echo ""
  echo "========================================================================"
  echo "  TEST SUMMARY"
  echo "========================================================================"
  echo -e "Total:  ${TOTAL}"
  echo -e "Passed: ${GREEN}${PASSED}${NC}"
  echo -e "Failed: ${RED}${FAILED}${NC}"
  echo "========================================================================"

  if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ ALL TESTS PASSED${NC}"
    exit 0
  else
    echo -e "${RED}❌ ${FAILED} TEST(S) FAILED${NC}"
    exit 1
  fi
}

# Parse arguments
RUN_UNIT=true
RUN_INT=true

if [ "$1" == "--unit" ]; then
  RUN_INT=false
elif [ "$1" == "--int" ]; then
  RUN_UNIT=false
fi

# Header
echo "========================================================================"
echo "  CLAUDE COPILOT: AGENT & SKILL FRAMEWORK TESTS"
echo "========================================================================"
echo ""

# Change to tests directory
cd "$(dirname "$0")"

# Run unit tests
if [ "$RUN_UNIT" == "true" ]; then
  echo -e "${YELLOW}📦 UNIT TESTS${NC}"
  echo "------------------------------------------------------------------------"

  run_test "unit/agent-assignment.test.ts"
  run_test "unit/skill-loading.test.ts"

  echo ""
fi

# Run integration tests
if [ "$RUN_INT" == "true" ]; then
  echo -e "${YELLOW}🔗 INTEGRATION TESTS${NC}"
  echo "------------------------------------------------------------------------"

  run_test "integration/agent-skill-orchestration.test.ts"
  run_test "integration/hooks-evaluation-corrections.test.ts"
  run_test "integration/lean-agents-skills.test.ts"
  run_test "integration/orchestration-lifecycle.test.ts"
  run_test "integration/memory-copilot.test.ts"
  run_test "integration/task-copilot.test.ts"
  run_test "integration/cross-system.test.ts"
  run_test "integration/knowledge-sync.test.ts"

  echo ""
fi

# Print summary
print_summary
