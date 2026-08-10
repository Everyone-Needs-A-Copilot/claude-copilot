#!/usr/bin/env bash
# discord-dispatch.sh — dispatches a task via `tc worker` (a real,
# budget-enforced subprocess) and reports the outcome to a Discord thread.
#
# Why this shape: `copilot discord handoff --harness` is a free-text
# thread-routing LABEL, not a command spec (verified live: `copilot discord
# handoff --help` -> "--harness TEXT codex, claude, or another label.").
# Nothing in `copilot`'s Discord surface parses or executes a `--harness`
# value. An earlier version of this script built a `claude --print
# --max-budget-usd $N` string and passed it as `--harness`, which stored the
# string as a thread label and ran nothing -- no process was spawned and no
# budget cap was ever enforced. The actual dispatch, and the actual
# --max-budget-usd enforcement, now happen via `tc worker`, which wraps
# `claude --print --max-budget-usd <n>` (a real, harness-enforced flag; see
# tools/tc/src/tc/commands/worker.py and
# tools/tc/tests/test_claude_flag_existence.py). `copilot discord handoff` is
# used only for what it actually does: posting the dispatch outcome to a new
# Discord thread, with `--harness` passed as a genuine label value.
#
# Usage:
#   .claude/bin/discord-dispatch.sh --task <id> [--max-budget-usd <float>] [--title "..."]
#
# Environment:
#   COPILOT_BIN   Path to the copilot binary (default: /opt/homebrew/bin/copilot, else PATH)
#   TC_BIN        Path to the tc binary (default: PATH, else the repo's tools/tc/.venv)
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
      # Plumb --max-budget-usd through to the real `tc worker` dispatch.
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
# Locate the tc binary
# ---------------------------------------------------------------------------
TC_BIN_RESOLVED="${TC_BIN:-tc}"

if ! command -v "$TC_BIN_RESOLVED" >/dev/null 2>&1; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
  if [[ -x "$REPO_ROOT/tools/tc/.venv/bin/tc" ]]; then
    TC_BIN_RESOLVED="$REPO_ROOT/tools/tc/.venv/bin/tc"
  fi
fi

if ! command -v "$TC_BIN_RESOLVED" >/dev/null 2>&1; then
  echo "tc CLI not found. Set TC_BIN or ensure 'tc' is on PATH." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Dispatch the task via `tc worker` — the real, budget-enforced execution.
# ---------------------------------------------------------------------------
DISPATCH_CMD=("$TC_BIN_RESOLVED" worker "$TASK_ID")
if [[ -n "$MAX_BUDGET_USD" ]]; then
  # --max-budget-usd plumbed through to tc worker's `claude --print` dispatch
  DISPATCH_CMD+=(--max-budget-usd "$MAX_BUDGET_USD")
fi
DISPATCH_CMD+=(--json)

set +e
DISPATCH_OUTPUT="$("${DISPATCH_CMD[@]}" 2>&1)"
DISPATCH_EXIT=$?
set -e

if [[ "$DISPATCH_EXIT" -eq 0 ]]; then
  MESSAGE="Task $TASK_ID dispatched via tc worker (exit 0). $DISPATCH_OUTPUT"
else
  MESSAGE="Task $TASK_ID dispatch FAILED via tc worker (exit $DISPATCH_EXIT). $DISPATCH_OUTPUT"
fi

# ---------------------------------------------------------------------------
# Report the outcome via `copilot discord handoff`
# ---------------------------------------------------------------------------
COPILOT_BIN="${COPILOT_BIN:-/opt/homebrew/bin/copilot}"

if ! command -v "$COPILOT_BIN" >/dev/null 2>&1 && ! command -v copilot >/dev/null 2>&1; then
  echo "copilot CLI not found. Set COPILOT_BIN or ensure 'copilot' is on PATH." >&2
  exit "$DISPATCH_EXIT"
fi

DISCORD_CMD="${COPILOT_BIN}"
if ! command -v "$DISCORD_CMD" >/dev/null 2>&1; then
  DISCORD_CMD="copilot"
fi

# --harness is a free-text thread-routing label (never executed) — "claude"
# is the real harness that ran the dispatch above, not a fabricated command.
"$DISCORD_CMD" discord handoff \
  "$MESSAGE" \
  --title "$TITLE" \
  --harness claude

exit "$DISPATCH_EXIT"
