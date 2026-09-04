#!/usr/bin/env bash
# framework-pin-status.sh — report whether the pinned runtime snapshot is
# still current with the live framework checkout it was cut from.
#
# The hooks that actually execute run from an immutable, commit-addressed
# snapshot under ~/.copilot/framework-snapshots/, resolved via
# `cc config get paths.claude_copilot_root` and recorded by
# `source_commit` in ~/.copilot/framework-runtime.json. That pin is only
# ever updated by scripts/install-framework-snapshot.py (see
# .claude/commands/update-copilot.md); it does not move on its own when
# the live checkout at ~/.claude/copilot advances. A stale pin is
# otherwise only discovered by symptom (a fix landed upstream has no
# effect) — this makes the gap directly reportable.
#
# Usage:
#   .claude/hooks/bin/framework-pin-status.sh
#
# Exit codes: 0 = in sync or unknown (informational only, never blocks),
# 1 = drift detected (pinned commit is behind the live checkout HEAD).

set -uo pipefail

RUNTIME_JSON="${COPILOT_FRAMEWORK_RUNTIME_JSON:-$HOME/.copilot/framework-runtime.json}"
LIVE_ROOT="${COPILOT_SOURCE_ROOT:-$HOME/.claude/copilot}"
JQ="${JQ_BIN:-/usr/bin/jq}"

if [[ ! -f "$RUNTIME_JSON" ]]; then
  echo "framework-pin-status: no runtime pin found at ${RUNTIME_JSON} (framework never installed here)."
  exit 0
fi

PINNED_COMMIT="$("$JQ" -r '.source_commit // empty' "$RUNTIME_JSON" 2>/dev/null)"
if [[ -z "$PINNED_COMMIT" ]]; then
  echo "framework-pin-status: ${RUNTIME_JSON} has no source_commit — cannot check drift."
  exit 0
fi

if [[ ! -d "$LIVE_ROOT/.git" ]] && [[ ! -f "$LIVE_ROOT/.git" ]]; then
  echo "framework-pin-status: pinned=${PINNED_COMMIT}; live checkout not found at ${LIVE_ROOT} — cannot compare."
  exit 0
fi

LIVE_COMMIT="$(git -C "$LIVE_ROOT" rev-parse HEAD 2>/dev/null || echo "")"
if [[ -z "$LIVE_COMMIT" ]]; then
  echo "framework-pin-status: pinned=${PINNED_COMMIT}; could not resolve HEAD of ${LIVE_ROOT} — cannot compare."
  exit 0
fi

if [[ "$PINNED_COMMIT" == "$LIVE_COMMIT" ]]; then
  echo "framework-pin-status: in sync (pinned=${PINNED_COMMIT})."
  exit 0
fi

if git -C "$LIVE_ROOT" merge-base --is-ancestor "$PINNED_COMMIT" "$LIVE_COMMIT" 2>/dev/null; then
  AHEAD="$(git -C "$LIVE_ROOT" rev-list --count "${PINNED_COMMIT}..${LIVE_COMMIT}" 2>/dev/null || echo "?")"
  echo "framework-pin-status: DRIFT — executing snapshot is ${AHEAD} commit(s) behind the live checkout."
  echo "  pinned (executing): ${PINNED_COMMIT}"
  echo "  live (${LIVE_ROOT}): ${LIVE_COMMIT}"
  echo "  repair: re-run the update-copilot snapshot-install flow to re-pin (see .claude/commands/update-copilot.md)."
  exit 1
fi

echo "framework-pin-status: pinned commit ${PINNED_COMMIT} is not an ancestor of live HEAD ${LIVE_COMMIT} (diverged, not simply behind) — inspect manually."
exit 1
