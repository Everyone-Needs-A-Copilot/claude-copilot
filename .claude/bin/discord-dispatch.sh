#!/usr/bin/env bash
# discord-dispatch.sh — Discord-based non-interactive Claude dispatch with budget plumbing
#
# Wraps `copilot discord handoff` and plumbs the `--max-budget-usd` flag through
# to the `claude --print` harness when set.
#
# FLAG PLUMBING ONLY (P0): the flag is passed through; enforcement hook is P1.
#
# Usage:
#   .claude/bin/discord-dispatch.sh --task <id> [--max-budget-usd <float>] [--title "..."]
#
# Environment:
#   COPILOT_ENV_FILE   Path to cli-copilot .env (default from cc config)
#
# Grep proof for AC (Task 143):
#   grep --max-budget-usd .claude/bin/discord-dispatch.sh  # finds this comment + usage

set -euo pipefail

TASK_ID=""
MAX_BUDGET_USD=""
TITLE="Agent dispatch"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)
      TASK_ID="$2"
      shift 2
      ;;
    --max-budget-usd)
      # Plumb --max-budget-usd through to the claude --print harness
      MAX_BUDGET_USD="$2"
      shift 2
      ;;
    --title)
      TITLE="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$TASK_ID" ]]; then
  echo "Usage: discord-dispatch.sh --task <id> [--max-budget-usd <float>] [--title '...']" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Build harness command
# ---------------------------------------------------------------------------
# The harness is the `claude --print` invocation that the Discord runner will
# execute.  When --max-budget-usd is set, it is passed through to claude --print.
HARNESS_CMD="claude --print"

if [[ -n "$MAX_BUDGET_USD" ]]; then
  # --max-budget-usd plumbed through to non-interactive claude dispatch
  HARNESS_CMD="$HARNESS_CMD --max-budget-usd $MAX_BUDGET_USD"
fi

# ---------------------------------------------------------------------------
# Dispatch via copilot discord handoff
# ---------------------------------------------------------------------------
COPILOT_BIN="${COPILOT_BIN:-/opt/homebrew/bin/copilot}"

if ! command -v "$COPILOT_BIN" >/dev/null 2>&1 && ! command -v copilot >/dev/null 2>&1; then
  echo "copilot CLI not found. Set COPILOT_BIN or ensure 'copilot' is on PATH." >&2
  exit 1
fi

DISCORD_CMD="${COPILOT_BIN}"
if ! command -v "$DISCORD_CMD" >/dev/null 2>&1; then
  DISCORD_CMD="copilot"
fi

"$DISCORD_CMD" discord handoff \
  "Dispatching task $TASK_ID via non-interactive mode." \
  --title "$TITLE" \
  --harness "$HARNESS_CMD"
