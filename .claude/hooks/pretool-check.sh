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
#   Set COPILOT_EXTENSIONS_GATE=off to bypass the extension-resolution gate.
#   Journey dispatch verification has no bypass: an active journey is a
#   security/evidence boundary, not an optional workflow preference.
#
# INPUT (stdin):
#   JSON object with fields:
#     session_id  — unique session identifier
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
#      Task: 17 (P4.2).
#   2. qa-gate — deny all tool calls except Agent(qa) and safe tc Bash calls
#      while any task is in pending-qa state for this session.
#      Task: 16 (P4.1). Bypass: COPILOT_QA_GATE=off
#   3. extension-resolution — on a direct @agent-X dispatch (Agent tool,
#      main session, no /protocol in between), actually run `cc extensions
#      resolve --agent <id> --json` and deny if it comes back
#      `fallback_fail` (required skills missing, fallbackBehavior: fail) —
#      the one outcome every wired agent's own instructions already
#      document as a hard stop but had no enforced consumer for
#      (EFFECTIVENESS E-6: a mention in agent/command markdown is not a
#      consumer). Bypass: COPILOT_EXTENSIONS_GATE=off
#   4. journey-dispatch — after the QA gate, verify an active journey's
#      single-use invocation marker and exact Agent/Knowledge prompt digests.
#      No active journey is an explicit no-op; indeterminate active state
#      fails closed.

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
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" \
  || { echo "[pretool-check] could not resolve SCRIPT_DIR" >&2; exit 0; }
STATE_DIR="${COPILOT_HOOK_STATE_DIR:-${SCRIPT_DIR}/state}"
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
#
# LAZY LOADING: this jq call (plus the @agent-X list formatting) only runs
# on invocations that actually need it — a subagent's own tool call (any
# non-empty agent_type, to validate the exemption) or a deny message that
# lists valid agents. The common case (main-session call, nothing denied)
# never touches the manifest at all. See _ensure_manifest_loaded below.
# ---------------------------------------------------------------------------
_load_manifest_agents() {
  if [[ -f "$MANIFEST_FILE" ]]; then
    "$JQ" -r '[.agents | to_entries[] | select(.value.role == "framework") | .key] | sort | join(" ")' \
      "$MANIFEST_FILE" 2>/dev/null
  fi
}

# Format agents as @agent-X list for deny messages
_format_agent_list() {
  local result=""
  for a in $MANIFEST_AGENTS; do
    result="${result}@agent-${a}, "
  done
  echo "${result%, }"
}

# MANIFEST_AGENTS is a space-separated list of framework agent names from the
# manifest. Populated on first use by _ensure_manifest_loaded (idempotent —
# safe to call from multiple sites).
export MANIFEST_FILE
MANIFEST_AGENTS=""
VALID_AGENT_LIST=""
_MANIFEST_LOADED=0
_ensure_manifest_loaded() {
  [[ "$_MANIFEST_LOADED" -eq 1 ]] && return 0
  _MANIFEST_LOADED=1
  MANIFEST_AGENTS="$(_load_manifest_agents 2>/dev/null || echo "")"
  # Fallback when manifest unavailable
  if [[ -z "$MANIFEST_AGENTS" ]]; then
    MANIFEST_AGENTS="cco cpa cs cw do doc ind me qa sd sec ta uid uids uxd"
  fi
  VALID_AGENT_LIST="$(_format_agent_list)"
}

# Claude Code's own built-in generic subagent types. protocol-injection.md
# Rule 4 and commands/protocol.md explicitly document these three as real,
# reachable subagent_type values that Claude Code itself can dispatch (the
# framework tells the model not to prefer them, but does not — and cannot,
# from inside a hook — prevent the harness from actually running one). A
# subagent running under one of these still needs the same livelock
# exemption as a named framework agent: it has no Agent/Task tool of its
# own either, so denying its Read/Edit/Bash calls is equally unsatisfiable.
BUILTIN_AGENT_TYPES="general-purpose Explore Plan"

# Validate a candidate agent_type against the known-good set: MANIFEST_AGENTS
# (this framework's own named agents) plus BUILTIN_AGENT_TYPES (Claude
# Code's generic subagent types). An unrecognized non-empty value — anything
# outside both sets — must NOT be granted the subagent exemption (that would
# be an unconditional enforcement bypass — any caller could set agent_type to
# arbitrary text and escape both rule_force_delegate and rule_qa_gate). The
# safe direction on an unknown value is "not exempt", i.e. treat the call as
# main-session.
_is_known_agent() {
  _ensure_manifest_loaded
  local candidate="$1"
  local _a
  for _a in $MANIFEST_AGENTS $BUILTIN_AGENT_TYPES; do
    if [[ "$candidate" == "$_a" ]]; then
      return 0
    fi
  done
  return 1
}

# ---------------------------------------------------------------------------
# Read hook payload from stdin
# ---------------------------------------------------------------------------
PAYLOAD="$(cat)"

if [[ -z "$PAYLOAD" ]]; then
  exit 0
fi

# Single jq call extracts the three top-level identifier fields together.
# Each separate jq invocation costs ~2-3ms of fork/exec overhead; parsing
# the same PAYLOAD three times used to dominate the hook's <50ms performance
# budget. session_id/tool_name/agent_type are harness-generated tokens (never
# free-form text), so @tsv's escaping of tabs/newlines/backslashes is a safe
# no-op for them.
#
# AGENT_TYPE non-empty means this PreToolUse call originated inside a
# subagent (sidechain), even though it shares SESSION_ID with the main
# session that spawned it. Claude Code reuses the same session_id for a main
# session and any subagent it spawns via the Agent tool — sidechain tool
# calls are NOT a distinct session, distinguished only by agent_type/agent_id
# being non-empty. Without this, a subagent's own Read/Edit/Write/Bash calls
# would silently trip (and be denied by) the parent session's force-delegate
# streak or QA-gate state, with no escape — framework agents don't carry the
# Agent/Task tool, so "delegate to a framework agent instead" is
# unsatisfiable from inside a subagent. See rule_force_delegate and
# rule_qa_gate below for where this is consumed.
_PAYLOAD_FIELDS="$("$JQ" -r \
  '[.session_id // "", .tool_name // "", .agent_type // ""] | @tsv' \
  <<< "$PAYLOAD" 2>/dev/null)" \
  || { echo "[pretool-check] jq parse failed reading payload fields" >&2; exit 0; }
IFS=$'\t' read -r SESSION_ID TOOL_NAME AGENT_TYPE <<< "$_PAYLOAD_FIELDS"

if [[ -z "$SESSION_ID" || -z "$TOOL_NAME" ]]; then
  # Malformed payload — allow and let Claude handle it
  exit 0
fi

# TOOL_COMMAND (.tool_input.command) is arbitrary free-form shell text — NOT
# run through @tsv (which would mangle embedded backslashes/tabs/newlines) —
# extracted once here with plain -r raw output and shared by
# rule_force_delegate, rule_destructive_command, and rule_path_scope below,
# which previously each parsed it independently. Only Bash tool calls carry
# .tool_input.command, so this is skipped entirely for Read/Edit/Agent/etc.
TOOL_COMMAND=""
if [[ "$TOOL_NAME" == "Bash" ]]; then
  TOOL_COMMAND="$("$JQ" -r '.tool_input.command // ""' <<< "$PAYLOAD" 2>/dev/null)" \
    || TOOL_COMMAND=""
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

# Sets globals _STREAK_LAST_TOOL and _STREAK_COUNT rather than echoing JSON
# for the caller to re-parse. When STATE_FILE doesn't exist (the common case
# — first call of a session, or right after a streak reset) this makes zero
# subprocess calls at all; when it does exist, one jq call reads updatedAt,
# lastTool, and streak together instead of the state file being parsed
# multiple times (once for staleness, again per field).
read_streak() {
  _STREAK_LAST_TOOL=""
  _STREAK_COUNT=0
  if [[ ! -f "$STATE_FILE" ]]; then
    return
  fi
  local raw updated_at
  raw="$("$JQ" -r '[.updatedAt // "", .lastTool // "", (.streak // 0 | tostring)] | @tsv' \
    "$STATE_FILE" 2>/dev/null)" \
    || { echo "[pretool-check] jq parse failed reading streak state from $STATE_FILE" >&2; return; }
  IFS=$'\t' read -r updated_at _STREAK_LAST_TOOL _STREAK_COUNT <<< "$raw"
  _STREAK_COUNT="${_STREAK_COUNT:-0}"

  if [[ -n "$updated_at" ]]; then
    local now_epoch file_epoch
    printf -v now_epoch '%(%s)T' -1
    # date -j -f "%Y-%m-%dT%H:%M:%SZ" on macOS; fallback on Linux
    if [[ "$(uname)" == "Darwin" ]]; then
      file_epoch="$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "${updated_at}" +%s 2>/dev/null || echo 0)"
    else
      file_epoch="$(date -d "${updated_at}" +%s 2>/dev/null || echo 0)"
    fi
    local age=$(( now_epoch - file_epoch ))
    if [[ "$age" -gt "$STALENESS_SECONDS" ]]; then
      # Stale — treat as fresh
      _STREAK_LAST_TOOL=""
      _STREAK_COUNT=0
    fi
  fi
}

write_streak() {
  local last_tool="$1"
  local streak="$2"
  local now
  # Bash builtin strftime — no subprocess (was: date -u +%Y-%m-%dT%H:%M:%SZ).
  # TZ=UTC0 is required: bash's %()T uses the local zone by default, which
  # would silently mislabel a local-time value with the "Z" (UTC) suffix.
  TZ=UTC0 printf -v now '%(%Y-%m-%dT%H:%M:%SZ)T' -1
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

  # Subagent/sidechain tool calls are exempt — they ARE the delegation this
  # rule exists to force. Claude Code shares SESSION_ID between a main
  # session and its subagents, so without this check a subagent's own
  # Read/Edit/Bash calls would silently continue (and trip) the main
  # session's streak counter. Denying them is a livelock: framework agents
  # do not carry the Agent/Task tool, so "delegate to a framework agent
  # instead" has no satisfiable next step from inside a subagent. This must
  # come before the tool-name case below so it also exempts subagent Bash
  # calls, not just Read/Edit.
  #
  # The exemption only applies to a RECOGNIZED agent_type (validated against
  # MANIFEST_AGENTS). An unrecognized non-empty value is surfaced to stderr
  # and falls through to normal main-session handling rather than being
  # silently granted the exemption — see _is_known_agent above.
  if [[ -n "$AGENT_TYPE" ]]; then
    if _is_known_agent "$AGENT_TYPE"; then
      return 0
    fi
    echo "[pretool-check] unrecognized agent_type '${AGENT_TYPE}' (not in MANIFEST_AGENTS) — not exempting from force-delegate" >&2
  fi

  # Only track Bash, Read, Edit — not Agent or other tools. A main-session
  # Agent dispatch (reached here only because AGENT_TYPE was empty, i.e. this
  # IS the main session delegating, not a subagent's own call) is the exact
  # corrective action this rule exists to force, so it must reset any
  # pre-delegation streak. Otherwise stale streak state survives untouched
  # through the whole subagent invocation (subagent calls are exempt above
  # and never write to it) and the main session's first tool call after a
  # LEGITIMATE delegation gets falsely denied against the old count.
  case "$TOOL_NAME" in
    Bash|Read|Edit) ;;
    Agent)
      acquire_lock
      trap 'release_lock' EXIT
      write_streak "" 0
      release_lock
      trap - EXIT
      return 0
      ;;
    *) return 0 ;;
  esac

  # For Bash calls: check command-string escape hatch and safe-prefix allowlist.
  # TOOL_COMMAND was parsed once at the top of the script (shared with
  # rule_destructive_command and rule_path_scope below).
  if [[ "$TOOL_NAME" == "Bash" ]]; then
    local cmd="$TOOL_COMMAND"

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

  local last_tool streak
  read_streak; last_tool="$_STREAK_LAST_TOOL"; streak="$_STREAK_COUNT"

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
    _ensure_manifest_loaded
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

  # Once a subagent is running (agent_type non-empty), its own
  # Bash/Read/Edit/Write calls are exempt from the gate. The gate's job is to
  # stop the MAIN session from moving past pending QA work; it is not meant
  # to block the @agent-qa subagent's own investigation once dispatch has
  # already been allowed below. Without this, @agent-qa could Read/Edit its
  # way into the same "deny with no satisfiable next step" livelock that
  # rule_force_delegate has. TOOL_NAME=="Agent" is deliberately excluded so
  # that Agent-tool dispatch — by anyone, main session or a nested subagent
  # attempting to delegate further — stays fully subject to the allow/deny
  # logic below.
  #
  # As with rule_force_delegate, the exemption only applies to a RECOGNIZED
  # agent_type (validated against MANIFEST_AGENTS). An unrecognized value is
  # surfaced to stderr and falls through to the gate's normal deny logic.
  if [[ -n "$AGENT_TYPE" && "$TOOL_NAME" != "Agent" ]]; then
    if _is_known_agent "$AGENT_TYPE"; then
      return 0
    fi
    echo "[pretool-check] unrecognized agent_type '${AGENT_TYPE}' (not in MANIFEST_AGENTS) — not exempting from qa-gate" >&2
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
    _ensure_manifest_loaded
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
# Rule: journey-dispatch
#
# Witnesses only decisions already made by /protocol and prepared by
# `cc journey prepare`. It does not classify prompts, select specialists, or
# resolve Knowledge. For every direct main-session framework Agent call it
# asks the journey authority whether this session has an active run. When a
# run is active, the prompt must begin with exactly one structural envelope:
#
#   CC-JOURNEY-INVOCATION: <48 lowercase hex>
#   CC-JOURNEY-KNOWLEDGE-BEGIN
#   <exact prepared Knowledge bytes>
#   CC-JOURNEY-KNOWLEDGE-END
#
# Only digests and the opaque marker cross into cc. The raw Agent prompt and
# Knowledge bytes never appear in command arguments, hook state, or errors.
# PreToolUse can prove only that dispatch was observed and authorized. It does
# not prove that the specialist ran successfully or completed its work.
# ---------------------------------------------------------------------------
rule_journey_dispatch() {
  [[ "$TOOL_NAME" != "Agent" ]] && return 0
  # Nested/sidechain Agent traffic is not a main-session protocol dispatch.
  [[ -n "$AGENT_TYPE" ]] && return 0

  local subagent_type
  subagent_type="$("$JQ" -r '.tool_input.subagent_type // ""' <<< "$PAYLOAD" 2>/dev/null)" \
    || subagent_type=""
  [[ -z "$subagent_type" ]] && return 0

  # Only framework agents participate. Built-in/generic Agent calls remain
  # unchanged and can never manufacture journey evidence.
  _ensure_manifest_loaded
  local candidate is_framework=0
  for candidate in $MANIFEST_AGENTS; do
    if [[ "$candidate" == "$subagent_type" ]]; then
      is_framework=1
      break
    fi
  done
  [[ "$is_framework" -eq 0 ]] && return 0

  local cc_bin="${COPILOT_CC_BIN:-}"
  if [[ -z "$cc_bin" ]]; then
    cc_bin="$(command -v cc 2>/dev/null || true)"
  fi
  if [[ -z "$cc_bin" || ! -x "$cc_bin" ]]; then
    # Preserve legacy behavior when no structural journey marker is present.
    # An anchored marker proves this call belongs to a prepared journey and
    # therefore must fail closed if its verifier disappeared mid-session.
    if "$JQ" -e '(.tool_input.prompt // "") | test("\\ACC-JOURNEY-INVOCATION: [0-9a-f]{48}\\n")' \
        <<< "$PAYLOAD" &>/dev/null; then
      deny "Journey dispatch state is indeterminate (verifier-unavailable). Restore cc, then inspect the active journey before retrying."
    fi
    return 0
  fi

  local sha_bin="${COPILOT_SHA256_BIN:-/usr/bin/shasum}"
  if [[ ! -x "$sha_bin" ]]; then
    deny "Journey dispatch state is indeterminate (digest-verifier-unavailable). Restore the SHA-256 verifier before retrying."
  fi

  local prompt_sha256
  prompt_sha256="$("$JQ" -j '.tool_input.prompt // ""' <<< "$PAYLOAD" 2>/dev/null \
    | "$sha_bin" -a 256 2>/dev/null | awk '{print $1}')"
  if [[ ! "$prompt_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    deny "Journey dispatch state is indeterminate (prompt-digest-failed). Inspect the active journey before retrying."
  fi

  # jq operates on the decoded JSON string, preserving its exact Unicode and
  # newline structure. A marker is accepted only at byte/character zero, and
  # only with one immediately-following Knowledge frame. Duplicate structural
  # lines are malformed even if one copy looks valid.
  local frame_data marker knowledge_sha256 frame_valid
  frame_data="$("$JQ" -r '
    (.tool_input.prompt // "") as $p |
    ([ $p | scan("(?m)^CC-JOURNEY-INVOCATION: [0-9a-f]{48}$") ] | length) as $headers |
    ([ $p | scan("(?m)^CC-JOURNEY-KNOWLEDGE-BEGIN$") ] | length) as $begins |
    ([ $p | scan("(?m)^CC-JOURNEY-KNOWLEDGE-END$") ] | length) as $ends |
    if ($headers == 1 and $begins == 1 and $ends == 1 and
        ($p | test("\\ACC-JOURNEY-INVOCATION: [0-9a-f]{48}\\nCC-JOURNEY-KNOWLEDGE-BEGIN\\n[\\s\\S]*\\nCC-JOURNEY-KNOWLEDGE-END(?:\\n|\\z)")))
    then ($p | capture("\\ACC-JOURNEY-INVOCATION: (?<marker>[0-9a-f]{48})\\nCC-JOURNEY-KNOWLEDGE-BEGIN\\n(?<knowledge>[\\s\\S]*)\\nCC-JOURNEY-KNOWLEDGE-END(?:\\n[\\s\\S]*)?\\z") |
          ["valid", .marker, (.knowledge | @base64)] | @tsv)
    elif ($headers + $begins + $ends) == 0
    then ["absent", "", ""] | @tsv
    else ["malformed", "", ""] | @tsv
    end
  ' <<< "$PAYLOAD" 2>/dev/null)" || frame_data=$'malformed\t\t'
  IFS=$'\t' read -r frame_valid marker knowledge_b64 <<< "$frame_data"
  marker="${marker:-}"
  knowledge_sha256=""

  if [[ "$frame_valid" == "valid" ]]; then
    knowledge_sha256="$(printf '%s' "${knowledge_b64:-}" | /usr/bin/base64 --decode 2>/dev/null \
      | "$sha_bin" -a 256 2>/dev/null | awk '{print $1}')"
    if [[ ! "$knowledge_sha256" =~ ^[0-9a-f]{64}$ ]]; then
      frame_valid="malformed"
      marker=""
      knowledge_sha256=""
    fi
  fi

  # Never offer a malformed marker to the consuming verifier. An empty marker
  # performs the non-consuming active-run lookup. Thus malformed framing is a
  # deny only when the session is actually active; no-active legacy calls stay
  # unchanged.
  local verify_marker="$marker" verify_knowledge="$knowledge_sha256"
  if [[ "$frame_valid" == "malformed" ]]; then
    verify_marker=""
    verify_knowledge=""
  fi

  local verification verify_exit
  if verification="$("$cc_bin" journey verify-dispatch \
      --session "$SESSION_ID" \
      --subagent "$subagent_type" \
      --marker "$verify_marker" \
      --prompt-sha256 "$prompt_sha256" \
      --knowledge-sha256 "$verify_knowledge" \
      --json 2>/dev/null)"; then
    verify_exit=0
  else
    verify_exit=$?
  fi

  local schema state reason
  schema="$("$JQ" -r '.schema_version // ""' <<< "$verification" 2>/dev/null)" || schema=""
  state="$("$JQ" -r '.state // ""' <<< "$verification" 2>/dev/null)" || state=""
  reason="$("$JQ" -r '.reason // "journey-dispatch-denied"' <<< "$verification" 2>/dev/null)" \
    || reason="journey-dispatch-denied"

  if [[ "$schema" != "2.0" ]]; then
    deny "Journey dispatch state is indeterminate (malformed-verifier-response). Inspect the active journey before retrying."
  fi
  if [[ "$state" == "no_active" && "$verify_exit" -eq 0 ]]; then
    return 0
  fi
  if [[ "$state" == "dispatch_authorized" && "$verify_exit" -eq 0 && "$frame_valid" == "valid" ]]; then
    return 0
  fi
  if [[ "$frame_valid" == "malformed" && "$state" != "no_active" ]]; then
    deny "Journey dispatch denied (malformed-invocation-envelope). Run cc journey inspect for recovery details."
  fi
  if [[ "$state" == "denied" && "$verify_exit" -eq 2 && "$reason" =~ ^[a-z0-9][a-z0-9._-]{0,127}$ ]]; then
    deny "Journey dispatch denied (${reason}). Run cc journey inspect for recovery details."
  fi
  deny "Journey dispatch state is indeterminate (verifier-failed). Inspect the active journey before retrying."
}

# ---------------------------------------------------------------------------
# Rule: extension-resolution
# On a direct main-session @agent-X dispatch, run `cc extensions resolve
# --agent <id> --json` for real and deny only on `fallback_fail` — every
# wired agent's own file already documents this as "stop, explain warning,
# do not proceed", but that was prose an LLM could choose not to follow
# (EFFECTIVENESS E-6). Every other action (no_extension / apply /
# fallback_use_base / fallback_use_base_with_warning) is a pass-through:
# resolving here only ENFORCES the one failure mode; composing the
# extension into the agent's own instructions is still each wired agent's
# own Workflow step (a PreToolUse hook has no channel to rewrite the
# subagent's system prompt, only to allow/deny the dispatch).
#
# EXTENSION_GATE_AGENTS is deliberately a small, named roster — the exact
# agents a real org/personal knowledge-manifest.json declares (or could
# plausibly declare) an extension for today (sd/cw/do/ind/uxd, plus
# uids/cco which are wired even with no current declaration — see their
# own agent files), never "every framework agent". `cc extensions
# resolve` is a real subprocess (this hook's own PERFORMANCE TARGET is
# <50ms; a cold Python start is 100-300ms per this file's own
# _load_manifest_agents comment) — paying that cost on EVERY @agent-X
# dispatch, including the ~half of the roster (me/qa/ta/doc/sec/cs/cpa/
# uid) that will only ever resolve to `no_extension`, would tax the
# framework's single most frequent operation for zero behavioral value.
# Bypass: COPILOT_EXTENSIONS_GATE=off
# ---------------------------------------------------------------------------
EXTENSION_GATE_AGENTS="sd cw do ind uxd uids cco"

rule_extension_resolution() {
  if [[ "${COPILOT_EXTENSIONS_GATE:-}" == "off" ]]; then
    return 0
  fi

  [[ "$TOOL_NAME" != "Agent" ]] && return 0
  # A subagent's OWN nested Agent call (non-empty AGENT_TYPE) is not this
  # rule's concern — only the main session's direct dispatch is what
  # /protocol's algorithm and each wired agent's own Workflow step 3
  # otherwise resolve for themselves with no enforced consumer.
  [[ -n "$AGENT_TYPE" ]] && return 0
  command -v cc &>/dev/null || return 0

  local subagent_type
  subagent_type="$("$JQ" -r '.tool_input.subagent_type // ""' <<< "$PAYLOAD" 2>/dev/null)" \
    || return 0
  [[ -z "$subagent_type" ]] && return 0

  local candidate matched=0
  for candidate in $EXTENSION_GATE_AGENTS; do
    if [[ "$candidate" == "$subagent_type" ]]; then
      matched=1
      break
    fi
  done
  [[ "$matched" -eq 0 ]] && return 0

  local resolution action warning
  resolution="$(cc extensions resolve --agent "$subagent_type" --json 2>/dev/null)" || return 0
  [[ -z "$resolution" ]] && return 0
  action="$("$JQ" -r '.action // ""' <<< "$resolution" 2>/dev/null)" || return 0

  if [[ "$action" == "fallback_fail" ]]; then
    warning="$("$JQ" -r '.warning // "required skills unavailable"' <<< "$resolution" 2>/dev/null)"
    deny "Extension resolution for @agent-${subagent_type}: ${warning:-required skills unavailable} — fallbackBehavior is 'fail', so neither the base agent nor its extension may proceed. Resolve the missing skill(s), or have the declaring manifest set a different fallbackBehavior. Bypass: COPILOT_EXTENSIONS_GATE=off"
  fi

  return 0
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

  local cmd="$TOOL_COMMAND"
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
      local cmd="$TOOL_COMMAND"
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
rule_journey_dispatch
rule_extension_resolution
rule_destructive_command
rule_path_scope

exit 0
