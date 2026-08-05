#!/bin/bash
# audit-time-language.sh
# Scans codebase for time estimate violations in agent templates and documentation

set -e

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Configuration
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIOLATIONS_FOUND=0
REPORT_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --report)
      REPORT_MODE=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--report]"
      exit 1
      ;;
  esac
done

echo "========================================="
echo "Time Estimate Language Audit"
echo "========================================="
echo ""

# Function to check file for violations
check_file() {
  local file=$1
  local pattern=$2
  local description=$3
  local exclude_pattern=$4

  if [ -f "$file" ]; then
    if [ -z "$exclude_pattern" ]; then
      matches=$(grep -nE "$pattern" "$file" 2>/dev/null || true)
    else
      matches=$(grep -nE "$pattern" "$file" 2>/dev/null | grep -vE "$exclude_pattern" || true)
    fi

    if [ ! -z "$matches" ]; then
      VIOLATIONS_FOUND=$((VIOLATIONS_FOUND + 1))
      echo -e "${RED}VIOLATION:${NC} $description"
      echo "File: $file"
      echo "$matches"
      echo ""
    fi
  fi
}

# Function to scan directory
scan_directory() {
  local dir=$1
  local pattern=$2
  local description=$3
  local exclude_pattern=$4

  echo "Scanning $dir for: $description"

  find "$dir" -type f -name "*.md" ! -path "*/node_modules/*" | while read -r file; do
    check_file "$file" "$pattern" "$description" "$exclude_pattern"
  done
}

cd "$REPO_ROOT"

echo "1. CRITICAL: Agent Templates - Direct Time References"
echo "------------------------------------------------------"
scan_directory ".claude/agents" '\b(hours?|days?|weeks?|months?|years?|minutes?)\b' \
  "Direct time units" \
  'TTL|cache|testing|fast|slow|millisecond'

echo "2. CRITICAL: Agent Templates - Planning Language"
echo "-------------------------------------------------"
scan_directory ".claude/agents" '\b(timeline|schedule|deadline|due\s+date|ETA|delivery\s+date)\b' \
  "Time-based planning terms" \
  ''

echo "3. CRITICAL: Agent Templates - Phase-Based Time"
echo "------------------------------------------------"
scan_directory ".claude/agents" 'Phase\s+\d+.*\((Week|Month|Q\d)\s*\d*\)' \
  "Phases with time durations" \
  ''

echo "4. MEDIUM: Command Templates - Time References"
echo "-----------------------------------------------"
scan_directory ".claude/commands" '\b(hours?|days?|weeks?|months?|timeline|schedule)\b' \
  "Time references in commands" \
  'TTL|cache|testing'

echo "5. MEDIUM: Output Templates - Severity/Time Tables"
echo "---------------------------------------------------"
# Special check for tables with time commitments
find ".claude/agents" -type f -name "*.md" | while read -r file; do
  matches=$(grep -nE '(Response\s+Time|Completion\s+Time|Duration|Timeframe)\s*\|' "$file" 2>/dev/null || true)
  if [ ! -z "$matches" ]; then
    VIOLATIONS_FOUND=$((VIOLATIONS_FOUND + 1))
    echo -e "${RED}VIOLATION:${NC} Table with time commitment column"
    echo "File: $file"
    echo "$matches"
    echo ""
  fi
done

echo "6. MEDIUM: Template Files - Time References"
echo "--------------------------------------------"
if [ -d "templates" ]; then
  scan_directory "templates" '\b(hours?|days?|weeks?|months?|timeline|schedule)\b' \
    "Time references in templates" \
    'TTL|cache|testing|estimate'
fi

echo "7. INFO: Planning Documents - Time References"
echo "----------------------------------------------"
if [ -d "docs" ]; then
  # Exclude certain files that are allowed to have time references
  find "docs" -type f -name "*.md" \
    ! -name "SECURITY.md" \
    ! -name "CONFIGURATION.md" \
    ! -name "README.md" \
    ! -path "*/node_modules/*" | while read -r file; do
    check_file "$file" 'Phase\s+\d+.*\((Week|Month)\s+\d+' \
      "Phase with time duration" \
      ''
  done
fi

echo "8. INFO: Relative Time Language"
echo "--------------------------------"
scan_directory ".claude/agents" '\b(soon|asap|urgent|immediately)\b' \
  "Relative urgency terms" \
  ''

echo ""
echo "========================================="
echo "Audit Summary"
echo "========================================="

if [ $VIOLATIONS_FOUND -eq 0 ]; then
  echo -e "${GREEN}✓ No violations found${NC}"
  exit 0
else
  echo -e "${RED}✗ Found $VIOLATIONS_FOUND violation(s)${NC}"
  echo ""
  echo "See full report at: docs/qa/time-estimate-audit-report.md"
  echo ""
  echo "Common fixes:"
  echo "  - Replace 'timeline' with 'sequence' or 'dependencies'"
  echo "  - Replace 'Response Time' with 'Priority' or 'Severity'"
  echo "  - Replace phase durations with dependency-based ordering"
  echo "  - Remove time units from planning templates"

  if [ "$REPORT_MODE" = true ]; then
    echo ""
    echo "Run without --report to fail on violations"
    exit 0
  else
    exit 1
  fi
fi
