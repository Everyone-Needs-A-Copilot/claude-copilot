#!/usr/bin/env bash
# adversarial-pass.sh — Availability-gated cross-model adversarial QA pass
#
# PURPOSE:
#   When a second-model CLI is available (via env config or PATH probe), runs an
#   adversarial "try to break this diff" pass and emits an ARTIFACT line to stdout.
#
#   When no CLI is found → clean NO-OP, exit 0, emits nothing, never blocks the gate.
#   When CLI errors, times out, or diff is empty → same clean NO-OP.
#
# DETECTION (in priority order):
#   1. COPILOT_ADVERSARIAL_CMD env var — explicit command (may include flags/path)
#   2. PATH probe: codex, llm, mods (first found wins)
#   3. Nothing found → no-op
#
# OUTPUT (when a CLI is found and succeeds):
#   Printed to stdout — include this line verbatim in your QA verdict:
#     ARTIFACT: adversarial-run|<cmd> <findings-excerpt> exit=<code>
#
#   When no CLI is found or any error occurs: no output, exit 0.
#
# CONFIGURATION:
#   COPILOT_ADVERSARIAL_CMD      — explicit CLI to use (overrides PATH probe)
#   COPILOT_ADVERSARIAL_TIMEOUT  — timeout in seconds (default: 30)
#   COPILOT_ADVERSARIAL=off      — disable entirely (clean no-op regardless)
#
# INVOCATION CONVENTION:
#   The adversarial prompt and diff are combined and piped to the configured
#   command via stdin.  For CLIs that require a separate argument (e.g. a
#   system prompt flag), set COPILOT_ADVERSARIAL_CMD to a wrapper script.
#
# USAGE (by @agent-qa):
#   artifact="$(.claude/hooks/bin/adversarial-pass.sh)"
#   # If non-empty, include $artifact in the final verdict message.
#   # It is a bonus: gate still passes on test-run alone.
#
#   # Or pipe an explicit diff:
#   artifact="$(git diff HEAD~1 | .claude/hooks/bin/adversarial-pass.sh)"
#
# ARTIFACT TYPE:
#   adversarial-run — optional / bonus; recognized by subagent-stop.sh parser
#   alongside test-run, file-check, diff-check. It NEVER becomes a gate blocker:
#   the QA gate still unblocks on any single recognized artifact type.
#
# ESCAPE HATCH:
#   export COPILOT_ADVERSARIAL=off   — disable for this shell session

set -uo pipefail

# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------
if [[ "${COPILOT_ADVERSARIAL:-}" == "off" ]]; then
  exit 0
fi

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
readonly TIMEOUT="${COPILOT_ADVERSARIAL_TIMEOUT:-30}"
readonly PROBE_ALLOWLIST=("codex" "llm" "mods")
readonly ADVERSARIAL_PROMPT="You are an adversarial code reviewer. A code diff is piped below. Find specific bugs, security flaws, edge-case failures, or correctness issues introduced by this change. Be concise. Start your reply with FINDINGS: followed by a single-line summary (or: FINDINGS: none found)."

# ---------------------------------------------------------------------------
# CLI detection
# Returns the command string on stdout; exits 1 if nothing found.
# ---------------------------------------------------------------------------
detect_cmd() {
  # 1. Explicit env var takes priority
  if [[ -n "${COPILOT_ADVERSARIAL_CMD:-}" ]]; then
    local base_cmd
    base_cmd="$(printf '%s' "$COPILOT_ADVERSARIAL_CMD" | awk '{print $1}')"
    if command -v "$base_cmd" >/dev/null 2>&1; then
      printf '%s' "$COPILOT_ADVERSARIAL_CMD"
      return 0
    fi
    # Configured but base command not found on PATH → no-op (silent)
    return 1
  fi

  # 2. Probe allowlist — first found wins
  for candidate in "${PROBE_ALLOWLIST[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return 0
    fi
  done

  # 3. Nothing found
  return 1
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  # Detect CLI — if none found, clean no-op
  local cmd=""
  if ! cmd="$(detect_cmd 2>/dev/null)" || [[ -z "$cmd" ]]; then
    exit 0
  fi

  # Read diff: from stdin if piped, otherwise from git diff
  local diff_input=""
  if [[ ! -t 0 ]]; then
    diff_input="$(cat)"
  else
    diff_input="$(git diff 2>/dev/null || true)"
  fi

  # Empty diff → nothing to review, no-op
  if [[ -z "$(printf '%s' "$diff_input" | tr -d '[:space:]')" ]]; then
    exit 0
  fi

  # Combine prompt + diff for stdin-based invocation
  local combined_input
  combined_input="$(printf '%s\n\nDIFF:\n%s\n' "$ADVERSARIAL_PROMPT" "$diff_input")"

  # Temp file for capturing output
  local tmpout
  tmpout="$(mktemp 2>/dev/null)" || exit 0

  # Run with timeout (macOS-compatible: background process + watchdog subshell)
  printf '%s' "$combined_input" | eval "$cmd" > "$tmpout" 2>&1 &
  local bg_pid=$!

  # Watchdog: kill background process after timeout
  (
    sleep "$TIMEOUT" 2>/dev/null
    kill "$bg_pid" 2>/dev/null || true
  ) &
  local watchdog_pid=$!

  # Wait for the model to finish
  wait "$bg_pid" 2>/dev/null
  local exit_code=$?

  # Clean up watchdog
  kill "$watchdog_pid" 2>/dev/null || true
  wait "$watchdog_pid" 2>/dev/null || true

  # Read output
  local raw_output=""
  raw_output="$(cat "$tmpout" 2>/dev/null || true)"
  rm -f "$tmpout"

  # Degrade to no-op on non-zero exit (includes timeout: SIGTERM=143, SIGKILL=137)
  if [[ $exit_code -ne 0 ]]; then
    exit 0
  fi

  # Extract findings: prefer FINDINGS: line, else first non-empty line
  local findings=""
  findings="$(printf '%s' "$raw_output" | grep -m1 -iE '^[[:space:]]*FINDINGS:' | head -c 200 || true)"
  if [[ -z "$findings" ]]; then
    findings="$(printf '%s' "$raw_output" | grep -m1 '[^[:space:]]' | head -c 120 || true)"
  fi
  if [[ -z "$findings" ]]; then
    findings="no output"
  fi

  # Sanitize: collapse to single line, remove pipe chars (ARTIFACT delimiter)
  local findings_clean
  findings_clean="$(printf '%s' "$findings" \
    | tr '\n\r\t' '   ' \
    | tr -s ' ' \
    | sed 's/[|]/-/g' \
    | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

  # Command name for artifact label (base name only)
  local cmd_name
  cmd_name="$(printf '%s' "$cmd" | awk '{print $1}' | xargs basename 2>/dev/null \
    || printf '%s' "$cmd" | awk '{print $1}')"

  # Emit ARTIFACT line to stdout
  printf 'ARTIFACT: adversarial-run|%s %s exit=%d\n' \
    "$cmd_name" "$findings_clean" "$exit_code"
}

main "$@"
