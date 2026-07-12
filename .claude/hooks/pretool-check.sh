#!/usr/bin/env bash
# pretool-check.sh — PreToolUse hook entrypoint for Claude Copilot
#
# ARCHITECTURE:
#   This is the single PreToolUse hook dispatcher. All PreToolUse rule sets
#   (force-delegate, QA-gate, etc.) are implemented here or sourced from
#   sibling files. To add a new rule set (e.g., task 16's QA gate):
#     1. Add a function rule_<name>() below
#     2. Call it in the dispatch section near the bottom
#     3. Each rule returns 0 (allow) or writes a deny JSON to stdout and exits 2
#
# ESCAPE HATCH:
#   Set COPILOT_FORCE_DELEGATE=off to bypass all force-delegate checks.
#   Set COPILOT_QA_GATE=off to bypass all QA gate checks.
#   Set CC_HOOK_ENFORCE=off to bypass EVERY rule set below (global kill switch).
#
# INPUT (stdin):
#   JSON object with fields:
#     session_id  — unique session identifier. IMPORTANT (TASK-106/C-6): Claude
#                   Code reuses the SAME session_id for a main session and any
#                   subagent it spawns via the Agent/Task tool — sidechain
#                   tool calls are NOT a distinct session. The only signal that
#                   distinguishes "this call originated inside a subagent" is
#                   agent_type/agent_id being non-empty. Confirmed empirically
#                   2026-07-12 by replaying real PreToolUse payloads from a
#                   throwaway `claude -p` session (main-session Read calls
#                   carry no agent_type; the same session_id's subsequent
#                   Task-spawned subagent Read calls carry
#                   agent_type:"general-purpose", agent_id:"<task-id>"). See
#                   docs/10-architecture/06-hook-deadlock-root-cause-2026-07.md.
#     agent_type  — non-empty when this call originated inside a subagent
#                   (e.g. "me", "qa", "general-purpose"); absent/empty for
#                   calls made directly by the main session.
#     agent_id    — non-empty alongside agent_type; the subagent instance id.
#     tool_name   — e.g. "Bash", "Read", "Edit", "Agent"
#     tool_input  — tool-specific parameters (object)
#
# OUTPUT:
#   Exit 0 + empty stdout  → allow
#   Exit 2 + JSON stdout   → deny with reason
#   JSON shape: { "permissionDecision": "deny", "reason": "..." }
#
# PERFORMANCE TARGET: <50ms per invocation
#
# STATE FILES:
#   .claude/hooks/state/streak-<session_id>.json
#   Shape: { "session_id": "...", "lastTool": "Bash", "streak": 3, "updatedAt": "<ISO>" }
#
#   .claude/hooks/state/qa-gate.json
#   Shape: { "<session_id>": { "pending_tasks": ["TASK-5"], "retries": { "TASK-5": 1 },
#             "history": [{ "taskId": "TASK-5", "event": "me_completed", "ts": "<ISO>" }],
#             "lastSeen": "<ISO>" } }
#
# RULE SETS:
#   1. force-delegate — deny after 5 consecutive same-tool calls (Bash|Read|Edit)
#      made directly by the main session. Subagent (sidechain) calls are exempt
#      — see the session_id/agent_type note above. Task: 17 (P4.2), TASK-106 (C-6).
#   2. qa-gate — deny all main-session tool calls except Agent(qa) and safe tc
#      Bash calls while any task is in pending-qa state for this session.
#      Once dispatched, the @agent-qa subagent's own tool calls are exempt
#      (see agent_type note above). Task: 16 (P4.1), TASK-106 (C-6).
#      Bypass: COPILOT_QA_GATE=off
#
# MATCHER (settings.json):
#   PreToolUse matcher is "Bash|Read|Edit|Agent" (widened TASK-106/C-6, was
#   Bash-only since 23c02c0 on 2026-04-22). Read/Edit/Agent are safe to match
#   again now that (a) the script fails open on any script error (ERR/PIPE
#   traps below, absolute SCRIPT_DIR resolution — the original crash-on-block
#   cause) and (b) subagent calls are exempt from force-delegate/qa-gate (the
#   shared-session_id livelock — see docs/10-architecture/
#   06-hook-deadlock-root-cause-2026-07.md for the full root-cause writeup).

set -uEo pipefail
# -u  : nounset — error on unbound variables
# -E  : errtrace — ERR trap propagates into functions (ensures no silent crashes)
# -o pipefail : pipeline exit code is rightmost non-zero command

# Emit a diagnostic and exit 0 (fail-open) on any unexpected ERR so that
# hook failures never silently block legitimate tool calls.
# With -E, this trap now also fires inside functions, not just the top level.
trap 'echo "[pretool-check] unexpected error at line $LINENO (exit $?)" >&2; exit 0' ERR

# Catch SIGPIPE: if stdout is unexpectedly closed (e.g., harness pipe break
# or race with the hosting process), the default SIGPIPE action kills the
# process silently. By catching it we ensure a stderr diagnostic is emitted
# and the hook fails open rather than dying with no output.
trap 'echo "[pretool-check] SIGPIPE at line $LINENO — stdout pipe broken, failing open" >&2; exit 0' PIPE

# ---------------------------------------------------------------------------
# Global kill switch (TASK-106 / C-6): bypasses EVERY rule set below, present
# and future. This repo's settings.json is live for the owner's real
# sessions — this is the single override to reach for if the widened
# Bash|Read|Edit matcher ever misbehaves, without needing to know which
# per-rule escape hatch applies.
#   export CC_HOOK_ENFORCE=off
# Exits before touching stdin/state on purpose: fastest possible path, and it
# must work even if state files or jq are unavailable.
# ---------------------------------------------------------------------------
if [[ "${CC_HOOK_ENFORCE:-}" == "off" ]]; then
  exit 0
fi

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" \
  || { echo "[pretool-check] could not resolve SCRIPT_DIR" >&2; exit 0; }
STATE_DIR="${SCRIPT_DIR}/state"
MANIFEST_FILE="${SCRIPT_DIR}/../agents/manifest.json"
SECURITY_RULES_FILE="${SCRIPT_DIR}/security-rules.json"
FREEZE_STATE_FILE="${STATE_DIR}/.freeze"
JQ="/usr/bin/jq"

# ---------------------------------------------------------------------------
# Load valid agent names from manifest.json (TASK-114 / ADR-002)
# Used to build helpful deny messages and validate subagent_type values.
# Falls back to a hardcoded minimal set when manifest is absent (safe degradation).
#
# PERFORMANCE NOTE: Originally used python3 (20ms warm, 100-300ms cold).
# Now uses jq (already required, 3-4ms). This is the primary fix for the
# intermittent "No stderr output" hook error caused by the hook exceeding
# the harness timeout when python3 is cold-cached.
# ---------------------------------------------------------------------------
_load_manifest_agents() {
  if [[ -f "$MANIFEST_FILE" ]]; then
    "$JQ" -r '[.agents | to_entries[] | select(.value.role == "framework") | .key] | sort | join(" ")' \
      "$MANIFEST_FILE" 2>/dev/null
  fi
}

# MANIFEST_AGENTS is a space-separated list of framework agent names from the manifest.
export MANIFEST_FILE
MANIFEST_AGENTS="$(_load_manifest_agents 2>/dev/null || echo "")"
# Fallback when manifest unavailable
if [[ -z "$MANIFEST_AGENTS" ]]; then
  MANIFEST_AGENTS="cco cpa cs cw do doc ind me qa sd sec ta uid uids uxd"
fi

# Format agents as @agent-X list for deny messages
_format_agent_list() {
  local result=""
  for a in $MANIFEST_AGENTS; do
    result="${result}@agent-${a}, "
  done
  echo "${result%, }"
}
VALID_AGENT_LIST="$(_format_agent_list)"

# ---------------------------------------------------------------------------
# Read hook payload from stdin
# ---------------------------------------------------------------------------
PAYLOAD="$(cat)"

if [[ -z "$PAYLOAD" ]]; then
  exit 0
fi

SESSION_ID="$("$JQ" -r '.session_id // ""' <<< "$PAYLOAD" 2>/dev/null)" \
  || { echo "[pretool-check] jq parse failed reading session_id" >&2; exit 0; }
TOOL_NAME="$("$JQ" -r '.tool_name // ""' <<< "$PAYLOAD" 2>/dev/null)" \
  || { echo "[pretool-check] jq parse failed reading tool_name" >&2; exit 0; }
# AGENT_TYPE non-empty means this PreToolUse call originated inside a
# subagent (sidechain), even though it shares SESSION_ID with the main
# session that spawned it. See INPUT doc comment at the top of this file —
# this is the TASK-106/C-6 fix for the April 2026 force-delegate livelock.
AGENT_TYPE="$("$JQ" -r '.agent_type // ""' <<< "$PAYLOAD" 2>/dev/null)" \
  || AGENT_TYPE=""

if [[ -z "$SESSION_ID" || -z "$TOOL_NAME" ]]; then
  # Malformed payload — allow and let Claude handle it
  exit 0
fi

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------
STATE_FILE="${STATE_DIR}/streak-${SESSION_ID}.json"
LOCK_FILE="${STATE_DIR}/streak-${SESSION_ID}.lock"
STALENESS_SECONDS=86400  # 24 hours

# Acquire a simple lock to prevent concurrent corruption
# Uses mkdir atomicity (POSIX-guaranteed).
acquire_lock() {
  local i=0
  while ! mkdir "$LOCK_FILE" 2>/dev/null; do
    sleep 0.02
    i=$((i + 1))
    if [[ $i -ge 10 ]]; then
      # Could not acquire lock in ~200ms — allow and bail
      exit 0
    fi
  done
}

release_lock() {
  rmdir "$LOCK_FILE" 2>/dev/null || true
}

read_streak() {
  if [[ ! -f "$STATE_FILE" ]]; then
    echo '{"lastTool":"","streak":0}'
    return
  fi
  local updated_at
  updated_at="$("$JQ" -r '.updatedAt // ""' "$STATE_FILE" 2>/dev/null)" \
    || { echo "[pretool-check] jq parse failed reading updatedAt from $STATE_FILE" >&2
         echo '{"lastTool":"","streak":0}'; return; }
  if [[ -n "$updated_at" ]]; then
    local now_epoch file_epoch
    now_epoch="$(date -u +%s)"
    # date -j -f "%Y-%m-%dT%H:%M:%SZ" on macOS; fallback on Linux
    if [[ "$(uname)" == "Darwin" ]]; then
      file_epoch="$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "${updated_at}" +%s 2>/dev/null || echo 0)"
    else
      file_epoch="$(date -d "${updated_at}" +%s 2>/dev/null || echo 0)"
    fi
    local age=$(( now_epoch - file_epoch ))
    if [[ "$age" -gt "$STALENESS_SECONDS" ]]; then
      # Stale — treat as fresh
      echo '{"lastTool":"","streak":0}'
      return
    fi
  fi
  local result
  result="$("$JQ" '{lastTool: .lastTool, streak: .streak}' "$STATE_FILE" 2>/dev/null)" \
    || { echo "[pretool-check] jq parse failed reading streak from $STATE_FILE" >&2
         echo '{"lastTool":"","streak":0}'; return; }
  echo "$result"
}

write_streak() {
  local last_tool="$1"
  local streak="$2"
  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local tmp="${STATE_FILE}.tmp.$$"
  printf '{"session_id":"%s","lastTool":"%s","streak":%d,"updatedAt":"%s"}\n' \
    "$SESSION_ID" "$last_tool" "$streak" "$now" > "$tmp"
  mv "$tmp" "$STATE_FILE"
}

deny() {
  local reason="$1"
  # Escape for JSON using bash builtins only — no subprocess, no pipeline,
  # no pipefail interaction. Escapes backslashes first (order matters), then
  # double quotes. Our deny messages are hardcoded ASCII but this is robust.
  local escaped="${reason//\\/\\\\}"
  escaped="${escaped//\"/\\\"}"
  # Write reason to stderr SO the harness can surface it in the error message
  # (harness format: "hook error: [path]: [stderr content]"). Without this,
  # the harness shows "No stderr output" — which looks like an internal crash
  # rather than an intentional policy block.
  echo "[hook-deny] ${reason}" >&2
  printf '{"permissionDecision":"deny","reason":"%s"}\n' "$escaped"
  exit 2
}

# ---------------------------------------------------------------------------
# Safe Bash command prefixes that are always allowed in force-delegate rule.
# These are single-shot, non-looping operations that must not count toward the
# consecutive-tool streak.
# ---------------------------------------------------------------------------
FORCE_DELEGATE_SAFE_PREFIXES=(
  "git push"
  "git pull"
  "git fetch"
  "git status"
  "git log"
  "git diff"
  "git show"
  "git stash"
  "git tag"
  "git remote"
)

is_force_delegate_safe_bash() {
  local cmd="$1"
  local prefix
  for prefix in "${FORCE_DELEGATE_SAFE_PREFIXES[@]}"; do
    if [[ "$cmd" == "${prefix}"* ]]; then
      return 0
    fi
  done
  return 1
}

# ---------------------------------------------------------------------------
# Rule: force-delegate
# Deny when the same tool (Bash|Read|Edit) is called 5+ times consecutively.
# The Agent tool is never subject to this rule (delegation is always allowed).
# Bypass: COPILOT_FORCE_DELEGATE=off (env var or command prefix)
# ---------------------------------------------------------------------------
rule_force_delegate() {
  # Check escape hatch via environment variable
  if [[ "${COPILOT_FORCE_DELEGATE:-}" == "off" ]]; then
    return 0
  fi

  # TASK-106/C-6: subagent/sidechain tool calls are exempt — they ARE the
  # delegation this rule exists to force. Claude Code shares SESSION_ID
  # between a main session and its subagents, so without this check a
  # subagent's own Read/Edit/Bash calls would silently continue (and trip)
  # the main session's streak counter. Denying them is a livelock: framework
  # agents (see .claude/agents/*.md `tools:` lines) do not carry the
  # Agent/Task tool, so "delegate to a framework agent instead" has no
  # satisfiable next step from inside a subagent. This is the exact
  # mechanism that shipped in 20097d9 and was masked (not fixed) by
  # 23c02c0's Bash-only matcher four hours later.
  if [[ -n "$AGENT_TYPE" ]]; then
    return 0
  fi

  # Only track Bash, Read, Edit — not Agent or other tools
  case "$TOOL_NAME" in
    Bash|Read|Edit) ;;
    *) return 0 ;;
  esac

  # For Bash calls: check command-string escape hatch and safe-prefix allowlist
  if [[ "$TOOL_NAME" == "Bash" ]]; then
    local cmd
    cmd="$("$JQ" -r '.tool_input.command // ""' <<< "$PAYLOAD" 2>/dev/null)" \
      || { echo "[pretool-check] jq parse failed reading command in force-delegate" >&2; return 0; }

    # Command-string escape hatch: COPILOT_FORCE_DELEGATE=off as command prefix
    if [[ "$cmd" == COPILOT_FORCE_DELEGATE=off* ]]; then
      return 0
    fi

    # Safe single-shot git operations don't count toward the streak
    if is_force_delegate_safe_bash "$cmd"; then
      return 0
    fi
  fi

  acquire_lock
  trap 'release_lock' EXIT

  local state
  state="$(read_streak)"
  local last_tool streak
  last_tool="$("$JQ" -r '.lastTool // ""' <<< "$state" 2>/dev/null)" \
    || { echo "[pretool-check] jq parse failed reading lastTool from streak state" >&2
         release_lock; trap - EXIT; return 0; }
  streak="$("$JQ" -r '.streak // 0' <<< "$state" 2>/dev/null)" \
    || { echo "[pretool-check] jq parse failed reading streak from streak state" >&2
         release_lock; trap - EXIT; return 0; }
  # Defense in depth: a corrupted/hand-edited state file could put a
  # non-numeric value in "streak". Bash arithmetic ($((streak + 1))) treats
  # non-numeric operands as nested variable references, which under `set -u`
  # aborts the whole script with an unbound-variable error that bypasses the
  # ERR trap (confirmed empirically: this is a real fail-CLOSED hole found
  # while building TASK-106/C-6's replay tests). Coerce to a safe default
  # instead of trusting the file.
  if ! [[ "$streak" =~ ^[0-9]+$ ]]; then
    echo "[pretool-check] non-numeric streak '${streak}' in ${STATE_FILE} — resetting to 0" >&2
    streak=0
  fi

  if [[ "$TOOL_NAME" == "$last_tool" ]]; then
    streak=$((streak + 1))
  else
    streak=1
  fi

  if [[ "$streak" -ge 5 ]]; then
    # Reset streak on deny so the next call starts fresh
    write_streak "$TOOL_NAME" 0
    release_lock
    trap - EXIT
    deny "Main session has issued 5+ consecutive ${TOOL_NAME} calls. Delegate to a framework agent instead. Valid agents: ${VALID_AGENT_LIST}. This preserves context budget and matches the framework's core purpose."
  fi

  write_streak "$TOOL_NAME" "$streak"
  release_lock
  trap - EXIT
  return 0
}

# ---------------------------------------------------------------------------
# Rule: qa-gate
# Deny all tool calls while any task is in pending-qa state for this session,
# EXCEPT:
#   - Agent tool with subagent_type == "qa"
#   - Bash commands that match safe read-only tc introspection prefixes
# Bypass: COPILOT_QA_GATE=off
# State: .claude/hooks/state/qa-gate.json (written by subagent-stop.sh)
# ---------------------------------------------------------------------------

# Safe Bash prefixes allowed while QA gate is active
QA_GATE_SAFE_PREFIXES=(
  "tc task get"
  "tc task list"
  "tc task create"
  "tc task update"
  "tc wp get"
  "tc wp list"
  "tc wp store"
  "tc progress"
  "tc log"
  "tc handoff"
  "tc prd"
  "tc stream"
  "python3 -m pytest"
  "pytest"
)

is_safe_bash_command() {
  local cmd="$1"
  local prefix
  for prefix in "${QA_GATE_SAFE_PREFIXES[@]}"; do
    if [[ "$cmd" == "${prefix}"* ]]; then
      return 0
    fi
  done
  return 1
}

rule_qa_gate() {
  # Escape hatch
  if [[ "${COPILOT_QA_GATE:-}" == "off" ]]; then
    return 0
  fi

  local gate_file="${STATE_DIR}/qa-gate.json"

  # No gate file → no pending tasks → allow
  if [[ ! -f "$gate_file" ]]; then
    return 0
  fi

  # Read pending_tasks for this session
  local pending_json
  pending_json="$("$JQ" -r --arg sid "$SESSION_ID" \
    '.[$sid].pending_tasks // [] | @json' "$gate_file" 2>/dev/null)" \
    || { echo "[pretool-check] jq parse failed reading qa-gate pending_tasks" >&2; return 0; }
  pending_json="${pending_json:-[]}"

  local pending_count
  pending_count="$("$JQ" 'length' <<< "$pending_json" 2>/dev/null)" \
    || { echo "[pretool-check] jq parse failed counting pending_tasks" >&2; return 0; }
  pending_count="${pending_count:-0}"

  if [[ "$pending_count" -eq 0 ]]; then
    return 0
  fi

  # Build a readable list of blocking task IDs
  local blocking_ids
  blocking_ids="$("$JQ" -r 'join(", ")' <<< "$pending_json" 2>/dev/null)" \
    || blocking_ids="unknown"
  blocking_ids="${blocking_ids:-unknown}"

  # TASK-106/C-6: once a subagent is running (agent_type non-empty), its own
  # Bash/Read/Edit calls are exempt from the gate. The gate's job is to stop
  # the MAIN session from moving past pending QA work; it is not meant to
  # block the @agent-qa subagent's own investigation once dispatch has
  # already been allowed below. Without this, @agent-qa could Read/Edit its
  # way into the same "deny with no satisfiable next step" livelock that
  # rule_force_delegate has. The Agent-tool dispatch decision itself
  # (TOOL_NAME=="Agent") is a main-session action and is still gated by the
  # allow/deny logic below regardless of this exemption.
  if [[ -n "$AGENT_TYPE" && "$TOOL_NAME" != "Agent" ]]; then
    return 0
  fi

  # Allow: Agent tool with subagent_type == "qa"
  if [[ "$TOOL_NAME" == "Agent" ]]; then
    local subagent_type
    subagent_type="$("$JQ" -r '.tool_input.subagent_type // ""' <<< "$PAYLOAD" 2>/dev/null)" \
      || subagent_type=""
    if [[ "$subagent_type" == "qa" ]]; then
      return 0
    fi
    # Warn if subagent_type is not a known manifest agent
    local is_known=0
    for _a in $MANIFEST_AGENTS; do
      if [[ "$subagent_type" == "$_a" ]]; then
        is_known=1
        break
      fi
    done
    if [[ "$is_known" -eq 0 ]] && [[ -n "$subagent_type" ]]; then
      # Unknown agent — deny with guidance (may be a typo or retired agent)
      deny "QA gate active: ${blocking_ids} require @agent-qa verification. Unknown agent '${subagent_type}' — use @agent-qa to unblock. Valid agents: ${VALID_AGENT_LIST}."
    fi
    # All other known Agent calls are denied while gate is active
    deny "QA gate active: ${blocking_ids} require @agent-qa verification before further work. Invoke @agent-qa to unblock."
  fi

  # Allow: Bash with safe tc introspection command
  if [[ "$TOOL_NAME" == "Bash" ]]; then
    local cmd
    cmd="$("$JQ" -r '.tool_input.command // ""' <<< "$PAYLOAD" 2>/dev/null)" \
      || cmd=""
    if is_safe_bash_command "$cmd"; then
      return 0
    fi
  fi

  # Deny everything else
  deny "QA gate active: ${blocking_ids} require @agent-qa verification before further work. Only @agent-qa invocation and read-only tc commands (tc task get, tc wp get, etc.) are allowed until QA passes."
}

# ---------------------------------------------------------------------------
# Rule: destructive-command (/careful)
# Reads enabled rules from security-rules.json and tests the Bash command
# string against each rule's patterns (case-insensitive).
# - action "block" → deny (exit 2)
# - action "warn"  → emit warning to stderr, allow (exit 0)
# Only applies to the Bash tool. A single jq call processes all rules.
# Bypass: COPILOT_SAFETY=off or COPILOT_CAREFUL=off
# ---------------------------------------------------------------------------
rule_destructive_command() {
  if [[ "${COPILOT_SAFETY:-}" == "off" || "${COPILOT_CAREFUL:-}" == "off" ]]; then
    return 0
  fi

  # Only applies to Bash tool
  if [[ "$TOOL_NAME" != "Bash" ]]; then
    return 0
  fi

  local cmd
  cmd="$("$JQ" -r '.tool_input.command // ""' <<< "$PAYLOAD" 2>/dev/null)" \
    || { echo "[pretool-check] jq parse failed reading command in rule_destructive_command" >&2; return 0; }
  [[ -z "$cmd" ]] && return 0

  [[ ! -f "$SECURITY_RULES_FILE" ]] && return 0

  # Two jq calls: first checks "block" rules, then "warn" rules.
  # Using inline filters (no def) for maximal jq version compatibility.
  # IMPORTANT: patterns are captured via "as $pat" so test($pat;"i") uses the
  # pattern as regex; $cmd is the string being matched against each pattern.
  local block_name
  block_name="$("$JQ" -r --arg cmd "$cmd" '
    [.rules[] |
     select(.enabled == true and .action == "block") |
     . as $rule |
     $rule.patterns[] as $pat |
     select(($cmd | test($pat; "i")) == true) |
     $rule.name
    ][0] // ""
  ' "$SECURITY_RULES_FILE" 2>/dev/null)" \
    || { echo "[pretool-check] jq failed (block check) in rule_destructive_command" >&2; return 0; }

  if [[ -n "$block_name" ]]; then
    deny "Safety (/careful): '${block_name}' — command blocked to prevent irreversible damage. Set COPILOT_CAREFUL=off to bypass if intentional."
    return  # not reached; deny calls exit 2
  fi

  local warn_name
  warn_name="$("$JQ" -r --arg cmd "$cmd" '
    [.rules[] |
     select(.enabled == true and .action == "warn") |
     . as $rule |
     $rule.patterns[] as $pat |
     select(($cmd | test($pat; "i")) == true) |
     $rule.name
    ][0] // ""
  ' "$SECURITY_RULES_FILE" 2>/dev/null)" \
    || { echo "[pretool-check] jq failed (warn check) in rule_destructive_command" >&2; return 0; }

  if [[ -n "$warn_name" ]]; then
    echo "[safety-warn] /careful: '${warn_name}' — command matches a destructive pattern. Review before executing. Set COPILOT_CAREFUL=off to suppress this warning." >&2
  fi

  return 0
}

# ---------------------------------------------------------------------------
# Rule: path-scope (/freeze)
# When a freeze directory is configured in FREEZE_STATE_FILE, denies any
# Edit, Write, or Bash-redirect operation targeting a path outside that dir.
#
# State file: .claude/hooks/state/.freeze (plain text, one absolute path)
# Enable:  echo /your/project/dir > .claude/hooks/state/.freeze
#          (or use: .claude/hooks/bin/freeze.sh on /your/project/dir)
# Disable: rm .claude/hooks/state/.freeze
#          (or use: .claude/hooks/bin/freeze.sh off)
#
# For Edit/Write: checks file_path in tool_input (exact, reliable).
# For Bash: checks redirect targets (> path or >> path) outside freeze dir.
# Bypass: COPILOT_SAFETY=off or COPILOT_FREEZE=off
# ---------------------------------------------------------------------------
rule_path_scope() {
  if [[ "${COPILOT_SAFETY:-}" == "off" || "${COPILOT_FREEZE:-}" == "off" ]]; then
    return 0
  fi

  # Only applies to Edit, Write, Bash
  case "$TOOL_NAME" in
    Edit|Write|Bash) ;;
    *) return 0 ;;
  esac

  # Read freeze dir — if state file missing or empty, no freeze active
  [[ ! -f "$FREEZE_STATE_FILE" ]] && return 0
  local freeze_dir
  read -r freeze_dir < "$FREEZE_STATE_FILE" 2>/dev/null || freeze_dir=""
  freeze_dir="${freeze_dir%/}"  # strip trailing slash
  [[ -z "$freeze_dir" ]] && return 0

  case "$TOOL_NAME" in
    Edit|Write)
      local file_path
      file_path="$("$JQ" -r '.tool_input.file_path // ""' <<< "$PAYLOAD" 2>/dev/null)" \
        || { echo "[pretool-check] jq parse failed reading file_path in rule_path_scope" >&2; return 0; }
      [[ -z "$file_path" ]] && return 0
      file_path="${file_path%/}"  # normalize
      if [[ "$file_path" != "${freeze_dir}"* ]]; then
        deny "Freeze (/freeze): edits are locked to '${freeze_dir}'. '${file_path}' is outside the freeze boundary. Use COPILOT_FREEZE=off to bypass, or run: .claude/hooks/bin/freeze.sh off"
      fi
      ;;
    Bash)
      local cmd
      cmd="$("$JQ" -r '.tool_input.command // ""' <<< "$PAYLOAD" 2>/dev/null)" \
        || { echo "[pretool-check] jq parse failed reading command in rule_path_scope" >&2; return 0; }
      [[ -z "$cmd" ]] && return 0

      # Extract redirect targets (> path and >> path) from the command.
      # This is a best-effort check: it catches explicit file redirects.
      # Use grep to find paths after > or >> operators.
      local redirect_target
      redirect_target="$(printf '%s' "$cmd" | grep -oE '>{1,2}[[:space:]]*/[^[:space:]|;&]+' \
        2>/dev/null | grep -oE '/[^[:space:]|;&]+' | head -1 || true)"

      if [[ -n "$redirect_target" ]]; then
        redirect_target="${redirect_target%/}"
        if [[ "$redirect_target" != "${freeze_dir}"* ]]; then
          deny "Freeze (/freeze): writes are locked to '${freeze_dir}'. Redirect target '${redirect_target}' is outside the freeze boundary. Use COPILOT_FREEZE=off to bypass."
        fi
      fi
      ;;
  esac

  return 0
}

# ---------------------------------------------------------------------------
# Dispatch — rule sets run in order; first deny wins
# ---------------------------------------------------------------------------
rule_force_delegate
rule_qa_gate
rule_destructive_command
rule_path_scope

exit 0
