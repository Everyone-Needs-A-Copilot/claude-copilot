#!/usr/bin/env bash
# fitness-check.sh — Claude Copilot Framework Fitness Functions
#
# Validates that a project's agents and commands are healthy after setup or update.
# Runs 5 fitness functions (FF1–FF5) and reports pass/fail per check.
#
# Usage:
#   bash .claude/fitness-check.sh [--agents-dir DIR] [--commands-dir DIR] [--copilot-path PATH]
#
# Arguments:
#   --agents-dir DIR      Path to agents directory (default: .claude/agents)
#   --commands-dir DIR    Path to commands directory (default: .claude/commands)
#   --copilot-path PATH   Path to copilot source (default: ~/.claude/copilot)
#
# Exit codes:
#   0 = all checks passed
#   1 = one or more checks failed

set -uo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
AGENTS_DIR=".claude/agents"
COMMANDS_DIR=".claude/commands"
COPILOT_PATH="${HOME}/.claude/copilot"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agents-dir)   AGENTS_DIR="$2";    shift 2 ;;
    --commands-dir) COMMANDS_DIR="$2";  shift 2 ;;
    --copilot-path) COPILOT_PATH="$2";  shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
PASS_COUNT=0
FAIL_COUNT=0
FAILURES=()

pass() { echo "  [PASS] $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "  [FAIL] $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); FAILURES+=("$1"); }
section() { echo; echo "=== $1 ==="; }

# ---------------------------------------------------------------------------
# Read roster from VERSION.json
# ---------------------------------------------------------------------------
VERSION_FILE="${COPILOT_PATH}/VERSION.json"
if [ -f "$VERSION_FILE" ]; then
  ROSTER=$(python3 -c "
import json, sys
with open('$VERSION_FILE') as f:
    v = json.load(f)
agents = v['components']['agents']['frameworkAgents']
print(' '.join(agents))
" 2>/dev/null) || ROSTER=""
  RETIRED=$(python3 -c "
import json, sys
with open('$VERSION_FILE') as f:
    v = json.load(f)
retired = v['components']['agents'].get('retired', [])
print(' '.join(retired))
" 2>/dev/null) || RETIRED=""
else
  echo "WARNING: VERSION.json not found at $VERSION_FILE — using hardcoded defaults" >&2
  ROSTER="cco cpa cs cw do doc ind kc me qa sd sec ta uid uids uxd"
  RETIRED="design"
fi

# ---------------------------------------------------------------------------
# FF1: No orphan routes — every @agent-X referenced in agents/ and commands/
#      resolves to a real agent file in agents/
# ---------------------------------------------------------------------------
section "FF1: No Orphan Routes"

# Scan agents/ (excluding _archive/) and commands/ for @agent-X references
REFERENCED_AGENTS=$(grep -rh '@agent-[a-z][a-z]*' \
  --exclude-dir=_archive \
  "${AGENTS_DIR}/" "${COMMANDS_DIR}/" 2>/dev/null \
  | grep -oE '@agent-[a-z]+' \
  | sed 's/@agent-//' \
  | sort -u)

# sec is allowlisted — it routes externally but is a valid agent
# kc is a setup agent, not routed to during normal work
ALLOWLIST="sec kc"

for ref in $REFERENCED_AGENTS; do
  # Skip allowlisted agents
  is_allowed=0
  for allowed in $ALLOWLIST; do
    [ "$ref" = "$allowed" ] && is_allowed=1 && break
  done

  if [ -f "${AGENTS_DIR}/${ref}.md" ]; then
    pass "@agent-${ref} resolves to ${AGENTS_DIR}/${ref}.md"
  elif [ $is_allowed -eq 1 ]; then
    pass "@agent-${ref} (allowlisted — external or setup agent)"
  else
    fail "@agent-${ref} referenced but ${AGENTS_DIR}/${ref}.md does not exist"
  fi
done

# ---------------------------------------------------------------------------
# FF2: Roster invocation parity — every agent in the manifest has a .md file
# ---------------------------------------------------------------------------
section "FF2: Roster Parity (all manifest agents present)"

for agent in $ROSTER; do
  if [ -f "${AGENTS_DIR}/${agent}.md" ]; then
    pass "${agent}.md present"
  else
    fail "${agent}.md MISSING (in VERSION.json roster but not in ${AGENTS_DIR}/)"
  fi
done

# ---------------------------------------------------------------------------
# FF3: No retired agents remain — retired agents must not exist in agents/
# ---------------------------------------------------------------------------
section "FF3: No Retired Agents Present"

if [ -z "$RETIRED" ]; then
  pass "No retired agents defined in VERSION.json"
else
  for agent in $RETIRED; do
    if [ -f "${AGENTS_DIR}/${agent}.md" ]; then
      fail "${agent}.md still present but is listed as retired in VERSION.json — remove it"
    else
      pass "Retired agent ${agent}.md correctly absent"
    fi
  done
fi

# ---------------------------------------------------------------------------
# FF4: Specialist distinctness — each specialist has required sections
# ---------------------------------------------------------------------------
section "FF4: Specialist Distinctness (required sections)"

REQUIRED_SECTIONS=("Core Behaviors" "Route To Other Agent")
SPECIALIST_AGENTS="uxd uids uid ind cco cw sec cs cpa"

for agent in $SPECIALIST_AGENTS; do
  agent_file="${AGENTS_DIR}/${agent}.md"
  if [ ! -f "$agent_file" ]; then
    fail "${agent}.md missing — skipping section check"
    continue
  fi
  for section_name in "${REQUIRED_SECTIONS[@]}"; do
    if grep -q "## ${section_name}" "$agent_file" 2>/dev/null; then
      pass "${agent}.md has '${section_name}' section"
    else
      fail "${agent}.md missing '${section_name}' section"
    fi
  done
done

# ---------------------------------------------------------------------------
# FF5: No orphan agent routes in agent files (agents only route to known agents)
# ---------------------------------------------------------------------------
section "FF5: No Orphan Agent-to-Agent Routes"

KNOWN_AGENTS="$ROSTER $ALLOWLIST"

for agent_file in "${AGENTS_DIR}"/*.md; do
  agent_name=$(basename "$agent_file" .md)
  # Find all @agent-X references in this file
  refs=$(grep -oE '@agent-[a-z]+' "$agent_file" 2>/dev/null | sed 's/@agent-//' | sort -u)
  for ref in $refs; do
    # Check if ref is in known agents (roster + allowlist)
    is_known=0
    for known in $KNOWN_AGENTS; do
      [ "$ref" = "$known" ] && is_known=1 && break
    done
    if [ $is_known -eq 1 ]; then
      pass "${agent_name}.md → @agent-${ref} (known)"
    else
      fail "${agent_name}.md → @agent-${ref} (UNKNOWN — not in roster or allowlist)"
    fi
  done
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "========================================"
echo "Fitness Check Results"
echo "========================================"
echo "  Passed: $PASS_COUNT"
echo "  Failed: $FAIL_COUNT"
echo

if [ $FAIL_COUNT -gt 0 ]; then
  echo "FAILURES:"
  for f in "${FAILURES[@]}"; do
    echo "  - $f"
  done
  echo
  echo "FITNESS CHECK FAILED ($FAIL_COUNT failures)"
  echo
  echo "Restore guidance:"
  echo "  - Missing agents: Copy from ${COPILOT_PATH}/.claude/agents/"
  echo "  - Orphan routes: Update Route To Other Agent table in offending agent file"
  echo "  - Retired agents: rm ${AGENTS_DIR}/<retired>.md"
  echo
  exit 1
else
  echo "FITNESS CHECK PASSED"
  exit 0
fi
