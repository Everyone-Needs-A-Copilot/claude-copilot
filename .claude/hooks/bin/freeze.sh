#!/usr/bin/env bash
# freeze.sh — Manage the /freeze path-scope lock for Claude Copilot
#
# The freeze lock restricts Edit, Write, and Bash redirects to a single
# directory. This prevents accidental out-of-scope edits when working on
# a focused sub-tree (Karpathy "orthogonal edits" failure mode).
#
# Usage:
#   freeze.sh on <directory>   Lock edits to <directory> (absolute path resolved)
#   freeze.sh off              Remove the freeze lock
#   freeze.sh status           Show current freeze state
#
# Escape hatch:
#   export COPILOT_FREEZE=off  Bypass the freeze rule for this shell session
#   export COPILOT_SAFETY=off  Bypass ALL safety rules (/careful + /freeze)
#
# State file: .claude/hooks/state/.freeze (gitignored, one absolute path per line)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" \
  || { echo "[freeze] could not resolve SCRIPT_DIR" >&2; exit 1; }
STATE_DIR="$(dirname "$SCRIPT_DIR")/state"
FREEZE_FILE="${STATE_DIR}/.freeze"

case "${1:-}" in
  on)
    dir="${2:-}"
    if [[ -z "$dir" ]]; then
      echo "Usage: freeze.sh on <directory>" >&2
      exit 1
    fi
    # Resolve to absolute path
    dir="$(cd "$dir" 2>/dev/null && pwd)" \
      || { echo "[freeze] directory not found: ${2}" >&2; exit 1; }
    printf '%s\n' "$dir" > "$FREEZE_FILE"
    echo "Freeze ON: edits locked to ${dir}"
    echo "  Bypass: export COPILOT_FREEZE=off"
    echo "  Remove: .claude/hooks/bin/freeze.sh off"
    ;;
  off)
    rm -f "$FREEZE_FILE"
    echo "Freeze OFF: edits are now unrestricted"
    ;;
  status)
    if [[ ! -f "$FREEZE_FILE" ]]; then
      echo "Freeze: OFF (no lock active)"
    else
      local_dir=""
      read -r local_dir < "$FREEZE_FILE" 2>/dev/null || local_dir=""
      if [[ -z "$local_dir" ]]; then
        echo "Freeze: OFF (empty state file)"
      else
        echo "Freeze: ON — locked to ${local_dir}"
        echo "  Remove: .claude/hooks/bin/freeze.sh off"
        echo "  Bypass: export COPILOT_FREEZE=off"
      fi
    fi
    ;;
  *)
    echo "Usage: freeze.sh on <directory> | off | status" >&2
    echo ""
    echo "  on <dir>   Lock edits to <dir> (and its subdirectories)"
    echo "  off        Remove the freeze lock"
    echo "  status     Show current freeze state"
    echo ""
    echo "Environment overrides:"
    echo "  COPILOT_FREEZE=off   Bypass for this shell session"
    echo "  COPILOT_SAFETY=off   Bypass all safety rules"
    exit 1
    ;;
esac
