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
#     cwd         — the Bash tool's actual working directory for this call.
#                   Used only to resolve relative-path Bash targets in
#                   rule_force_delegate's size-aware charge (_bash_target_bytes)
#                   against the right directory instead of this hook
#                   process's own $PWD.
#
# OUTPUT:
#   Exit 0 + empty stdout  → allow
#   Exit 2 + JSON stdout   → deny with reason
#   JSON shape: { "permissionDecision": "deny", "reason": "..." }
#
# PERFORMANCE TARGET: <50ms per invocation
#
# STATE FILES:
#   .claude/hooks/state/budget-<session_id>.json
#   Shape: { "session_id": "...", "bytesCharged": 300, "filesTouched": [], "updatedAt": "<ISO>" }
#
#   .claude/hooks/state/qa-gate.json
#   Shape: { "<session_id>": { "pending_tasks": ["TASK-5"], "retries": { "TASK-5": 1 },
#             "history": [{ "taskId": "TASK-5", "event": "me_completed", "ts": "<ISO>" }],
#             "lastSeen": "<ISO>" } }
#
# RULE SETS:
#   1. force-delegate — estimated byte cost and distinct file budget (ADR-005).
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
#   4. journey-dispatch — as the final permitting gate, verify an active journey's
#      single-use invocation marker and exact Agent/Knowledge prompt digests.
#      No active journey is an explicit no-op; indeterminate active state
#      fails closed.

set -uEo pipefail
# -u  : nounset — error on unbound variables
# -E  : errtrace — ERR trap propagates into functions (ensures no silent crashes)
# -o pipefail : pipeline exit code is rightmost non-zero command

JOURNEY_FAIL_CLOSED_CANDIDATE=0
_unexpected_hook_failure() {
  local line="${1:-unknown}" status="${2:-1}" signal="${3:-ERR}"
  echo "[pretool-check] unexpected ${signal} at line ${line} (exit ${status})" >&2
  if [[ "$JOURNEY_FAIL_CLOSED_CANDIDATE" -eq 1 ]]; then
    echo "[hook-deny] Journey dispatch state is indeterminate after an earlier hook failure." >&2
    printf '%s\n' '{"permissionDecision":"deny","reason":"Journey dispatch state is indeterminate after an earlier hook failure. Restore the hook and inspect journey state before retrying."}'
    exit 2
  fi
  exit 0
}

# Legacy/non-Agent failures remain fail-open. Once a direct main-session Agent
# call is identified below, every unexpected failure is fail-closed so no
# earlier rule can bypass the final journey authority.
trap '_unexpected_hook_failure "$LINENO" "$?" ERR' ERR

# Catch SIGPIPE: if stdout is unexpectedly closed (e.g., harness pipe break
# or race with the hosting process), the default SIGPIPE action kills the
# process silently. By catching it we ensure a stderr diagnostic is emitted
# and the hook fails open rather than dying with no output.
trap '_unexpected_hook_failure "$LINENO" 141 PIPE' PIPE

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_PARENT="."
[[ "$SCRIPT_PATH" == */* ]] && SCRIPT_PARENT="${SCRIPT_PATH%/*}"
SCRIPT_DIR="$(cd "$SCRIPT_PARENT" 2>/dev/null && pwd)" \
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
PAYLOAD=""
IFS= read -r -d '' PAYLOAD || true

if [[ -z "$PAYLOAD" ]]; then
  exit 0
fi

# Single jq call extracts the four top-level identifier fields together.
# Each separate jq invocation costs ~2-3ms of fork/exec overhead; parsing
# the same PAYLOAD three times used to dominate the hook's <50ms performance
# budget. Joined with U+001F (ASCII unit separator), not a tab: bash `read`
# treats any run of IFS characters that are themselves shell blanks (space,
# tab, newline) as ONE delimiter and silently drops empty fields between
# them, so a tab-joined line with agent_type empty (the common case) and a
# non-empty field after it — .cwd, added below — shifts every field after
# the gap left by mistake. \x1f is not a shell blank, so empty fields are
# preserved positionally. session_id/tool_name/agent_type/cwd are harness-
# generated tokens (never free-form text needing escaping). PAYLOAD_CWD is
# consumed only by rule_force_delegate's Bash byte estimator
# (_bash_target_bytes) below; every other rule ignores it.
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
  '([.session_id // "", .tool_name // "", .agent_type // "", .cwd // ""] | join("")),
   (if .tool_name == "Bash" then (.tool_input.command // "") else "" end)' \
  <<< "$PAYLOAD" 2>/dev/null)" \
  || { echo "[pretool-check] jq parse failed reading payload fields" >&2; exit 0; }
IFS=$'\x1f' read -r SESSION_ID TOOL_NAME AGENT_TYPE PAYLOAD_CWD <<< "${_PAYLOAD_FIELDS%%$'\n'*}"

if [[ -z "$SESSION_ID" || -z "$TOOL_NAME" ]]; then
  # Malformed payload — allow and let Claude handle it
  exit 0
fi

if [[ "$TOOL_NAME" == "Agent" && -z "$AGENT_TYPE" ]]; then
  _DIRECT_SUBAGENT="$("$JQ" -r '.tool_input.subagent_type // ""' <<< "$PAYLOAD" 2>/dev/null)" \
    || _DIRECT_SUBAGENT=""
  if [[ -n "$_DIRECT_SUBAGENT" ]]; then
    JOURNEY_FAIL_CLOSED_CANDIDATE=1
  fi
fi

# TOOL_COMMAND (.tool_input.command) is arbitrary free-form shell text — NOT
# run through @tsv (which would mangle embedded backslashes/tabs/newlines) —
# extracted once here with plain -r raw output and shared by
# rule_force_delegate, rule_destructive_command, and rule_path_scope below,
# which previously each parsed it independently. Only Bash tool calls carry
# .tool_input.command, so this is skipped entirely for Read/Edit/Agent/etc.
TOOL_COMMAND=""
if [[ "$TOOL_NAME" == "Bash" ]]; then
  if [[ "$_PAYLOAD_FIELDS" == *$'\n'* ]]; then
    TOOL_COMMAND="${_PAYLOAD_FIELDS#*$'\n'}"
  fi
fi

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------
STATE_FILE="${STATE_DIR}/budget-${SESSION_ID}.json"
LOCK_FILE="${STATE_DIR}/budget-${SESSION_ID}.lock"
STALENESS_SECONDS=86400  # 24 hours

# ADR-005 floor exemption: a call whose own estimated cost is at or below
# this many bytes is never denied on the byte meter, even once the session
# total is already over budget — a tiny, scoped inspection call must not be
# starved by an earlier unrelated charge. Override without a code edit.
FORCE_DELEGATE_FLOOR_BYTES="${COPILOT_FORCE_DELEGATE_FLOOR_BYTES:-4096}"

# Acquire a simple lock to prevent concurrent corruption
# Uses mkdir atomicity (POSIX-guaranteed).
acquire_lock() {
  local i=0
  while ! mkdir "$LOCK_FILE" 2>/dev/null; do
    sleep 0.02
    i=$((i + 1))
    if [[ $i -ge 10 ]]; then
      # Streak bookkeeping is optional. A timeout skips only this rule; it
      # must never terminate the dispatcher before the journey gate.
      echo "[pretool-check] force-delegate budget lock timed out; skipping budget update" >&2
      return 1
    fi
  done
}

release_lock() {
  rmdir "$LOCK_FILE" 2>/dev/null || true
}

deny() {
  local reason="$1"
  local escaped="${reason//\\/\\\\}"
  escaped="${escaped//\"/\\\"}"
  echo "[hook-deny] ${reason}" >&2
  printf '{"permissionDecision":"deny","reason":"%s"}\n' "$escaped"
  exit 2
}

# Exact approvals bind policy content, meter, threshold and prospective total.
# Local entries await review; CI reads HEAD's ledger and ignores env overrides.
budget_override_allows() {
  local meter="$1" threshold="$2" actual="$3" baseline="$4"
  local ledger="${SCRIPT_DIR}/../force-delegate-budget-overrides.jsonl"
  local policy record reason requested="${COPILOT_FORCE_DELEGATE_BUDGET_OVERRIDE:-}"
  policy="$(shasum -a 256 "$baseline")"
  policy="${policy%% *}"
  if [[ -z "${CI:-}" && "$requested" == "${meter}:"* ]]; then
    reason="${requested#*:}"
    if [[ -n "${reason//[[:space:]]/}" ]]; then
      record="$("$JQ" -cn --arg meter "$meter" --argjson threshold "$threshold" \
        --argjson actual "$actual" --arg policy "$policy" --arg reason "$reason" \
        --arg session "$SESSION_ID" \
        '{meter:$meter,threshold:$threshold,actual:$actual,policy:$policy,
          reason:$reason,session_id:$session,createdAt:(now|todateiso8601)}')" || return 1
      printf '%s\n' "$record" >> "$ledger" || return 1
      echo "[force-delegate-budget-override] ${meter} ${actual}/${threshold}: ${reason}" >&2
      return 0
    fi
  fi
  if [[ -n "${CI:-}" ]]; then
    record="$(git -C "${SCRIPT_DIR}/../.." show HEAD:.claude/force-delegate-budget-overrides.jsonl 2>/dev/null)" || return 1
  elif [[ -f "$ledger" ]]; then
    record="$(<"$ledger")"
  else
    return 1
  fi
  "$JQ" -es --arg meter "$meter" --argjson threshold "$threshold" \
    --argjson actual "$actual" --arg policy "$policy" \
    'any(.[]; .meter == $meter and .threshold == $threshold and
      .actual == $actual and .policy == $policy and
      (.reason | type == "string" and test("\\S")))' <<< "$record" >/dev/null 2>&1
}

# Whole-file byte count, shared by rule_force_delegate's Read branch and its
# Bash target-resolution branch below, so there is one sizing implementation,
# not two.
_file_byte_size() {
  local size
  size="$(wc -c < "$1" 2>/dev/null)" || return 1
  printf '%s' "${size//[[:space:]]/}"
}

# Resolves a candidate Bash target against base_dir when it is a relative
# path, leaving absolute paths untouched. base_dir is normally the payload's
# .cwd (the Bash tool's actual working directory); when base_dir is empty,
# this returns the candidate unchanged, which is exactly the pre-cwd-
# threading behavior — a relative candidate then resolves via bash's own
# implicit `[[ -f "$c" ]]` test against this hook process's own $PWD.
_resolve_against_cwd() {
  local candidate="$1" base_dir="$2"
  if [[ "$candidate" == /* || -z "$base_dir" ]]; then
    printf '%s' "$candidate"
  else
    printf '%s' "${base_dir%/}/${candidate}"
  fi
}

# Resolves ONE simple, unchained cat/find/grep/rg invocation (no ; | && > <
# ` $( inside it — the caller already split those out) to its file
# target(s), relative to base_dir when a target itself is a relative path,
# and sums their byte sizes via _file_byte_size — mirroring how
# rule_force_delegate's Read branch stats a real file instead of guessing by
# command name. A target that does not resolve to an existing regular file
# prints nothing and returns non-zero, so the caller keeps the conservative
# unbounded charge for this segment. Being conservative when the target is
# unknowable is intentional.
_bash_single_segment_bytes() {
  local segment="$1" base_dir="$2"
  local -a tokens=()
  read -ra tokens <<< "$segment"
  [[ "${#tokens[@]}" -gt 0 ]] || return 1
  local cmd_name="" i
  for ((i = 0; i < ${#tokens[@]}; i++)); do
    case "${tokens[$i]}" in
      cat|find|rg|grep) cmd_name="${tokens[$i]}"; break ;;
      *=*) continue ;;  # leading VAR=val assignment before the command
      *) return 1 ;;
    esac
  done
  [[ -n "$cmd_name" ]] || return 1
  local -a candidates=()
  local skip_pattern=0 j tok
  [[ "$cmd_name" == "grep" || "$cmd_name" == "rg" ]] && skip_pattern=1
  for ((j = i + 1; j < ${#tokens[@]}; j++)); do
    tok="${tokens[$j]}"
    [[ "$tok" == -* ]] && continue
    if [[ "$skip_pattern" -eq 1 ]]; then
      skip_pattern=0  # first non-flag token is the pattern, not a target
      continue
    fi
    candidates+=("$tok")
  done
  [[ "${#candidates[@]}" -gt 0 ]] || return 1
  local total=0 size c resolved target
  local -a matches=()
  for c in "${candidates[@]}"; do
    resolved="$(_resolve_against_cwd "$c" "$base_dir")"
    if [[ -f "$resolved" ]]; then
      matches=("$resolved")
    else
      # compgen expands a pattern as data, never as shell code. Preserve
      # the fallback for unmatched globs, directories and quoted patterns
      # this deliberately narrow word splitter cannot resolve.
      matches=()
      mapfile -t matches < <(compgen -G "$resolved")
      [[ "${#matches[@]}" -gt 0 ]] || return 1
    fi
    for target in "${matches[@]}"; do
      [[ -f "$target" ]] || return 1
      size="$(_file_byte_size "$target")" || return 1
      total=$((total + size))
    done
  done
  printf '%s' "$total"
}

# Resolves a Bash command's file target(s) to real paths and sums their byte
# sizes, instead of a flat charge by command-name match alone. Two things
# beyond a single simple command are supported here, both deliberately
# narrow:
#
#   1. A relative target resolves against payload_cwd — the harness's .cwd
#      for this Bash call — not this hook process's own $PWD, which is
#      whatever directory happened to spawn copilot-hook.sh and is
#      frequently a different directory. Absolute targets are unaffected.
#      When payload_cwd is absent, empty, or not a real directory, this
#      falls back to the pre-cwd-threading behavior (see
#      _resolve_against_cwd) rather than erroring.
#   2. A single leading `cd <dir> &&` or `cd <dir>;` is peeled off, and
#      everything after it resolves against <dir> instead (itself resolved
#      against payload_cwd when <dir> is relative). This is the shape the
#      main session actually issues ahead of a `grep`/`cat` pair. Only a cd
#      at the very start counts; a cd anywhere else, or any other chaining
#      (pipes, redirection, command substitution, backticks) alongside it,
#      is not tracked — those command shapes return non-zero here so the
#      caller keeps the conservative unbounded charge, which is the correct
#      answer when the target is genuinely unknowable.
#
# What remains after step 2 (one command, or several simple commands
# separated by `;`) is split on `;` and each segment resolved independently
# via _bash_single_segment_bytes, so a mixed command like
# `grep -c "x" a.md; cat b.json` sums both real file sizes. A segment that
# cannot be resolved contributes unbounded_charge on its own rather than
# forcing the whole call back to a single flat charge, so one unresolvable
# segment never hides the real, known size of the segments next to it.
_bash_target_bytes() {
  local command="$1" payload_cwd="${2:-}" unbounded_charge="${3:-8000}"
  [[ "$unbounded_charge" =~ ^[0-9]+$ ]] || unbounded_charge=8000

  local base_dir=""
  [[ -n "$payload_cwd" && -d "$payload_cwd" ]] && base_dir="$payload_cwd"

  local body="$command"
  if [[ "$command" == cd\ * ]]; then
    local after="${command#cd }" cd_target="" cd_rest=""
    if [[ "$after" == *' && '* ]]; then
      cd_target="${after%% && *}"
      cd_rest="${after#* && }"
    elif [[ "$after" == *';'* ]]; then
      cd_target="${after%%;*}"
      cd_rest="${after#*;}"
    else
      return 1  # `cd` with nothing recognizable after it — not this shape
    fi
    case "$cd_target" in
      *'|'*|*'&&'*|*';'*|*'>'*|*'<'*|*'`'*|*'$('*) return 1 ;;
    esac
    read -r cd_target <<< "$cd_target"
    [[ -n "$cd_target" ]] || return 1
    base_dir="$(_resolve_against_cwd "$cd_target" "$base_dir")"
    body="$cd_rest"
  fi

  # Beyond a leading cd, only `;`-separated simple segments are supported.
  # Pipes, redirection, command substitution, and backticks anywhere in the
  # remainder make the target ambiguous, same as before cwd threading.
  case "$body" in
    *'|'*|*'&&'*|*'>'*|*'<'*|*'`'*|*'$('*) return 1 ;;
  esac

  local -a segments=()
  IFS=';' read -ra segments <<< "$body"
  [[ "${#segments[@]}" -gt 0 ]] || return 1

  local total=0 seg seg_bytes processed=0
  for seg in "${segments[@]}"; do
    [[ -z "${seg//[[:space:]]/}" ]] && continue  # blank segment, e.g. trailing `;`
    processed=$((processed + 1))
    if seg_bytes="$(_bash_single_segment_bytes "$seg" "$base_dir")"; then
      total=$((total + seg_bytes))
    else
      total=$((total + unbounded_charge))
    fi
  done
  [[ "$processed" -gt 0 ]] || return 1
  printf '%s' "$total"
}

# ADR-005 estimates cost before execution; it is not a tokenizer/shell parser.
# Only Read/Edit/Write file targets count. Bash gets an output-cost estimate.
# Dispatch/alternation never refund spend. Denied attempts never consume it.
rule_force_delegate() {
  [[ "${COPILOT_FORCE_DELEGATE:-}" == "off" ]] && return 0
  if [[ -n "$AGENT_TYPE" ]]; then
    if _is_known_agent "$AGENT_TYPE"; then return 0; fi
    echo "[pretool-check] unrecognized agent_type '${AGENT_TYPE}' — not exempting from force-delegate" >&2
  fi
  case "$TOOL_NAME" in
    Bash|Read|Edit|Write) ;;
    *) return 0 ;;
  esac
  if [[ "$TOOL_NAME" == "Bash" &&
        "$TOOL_COMMAND" =~ ^COPILOT_FORCE_DELEGATE=off([[:space:]]|$) ]]; then
    return 0
  fi

  local baseline="" candidate
  local -a baselines=()
  for candidate in "${SCRIPT_DIR}"/../force-delegate-budget-baseline-v*.json; do
    [[ -f "$candidate" ]] && baselines+=("$candidate")
  done
  if [[ "${#baselines[@]}" -eq 0 ]]; then
    echo "[pretool-check] force-delegate budget baseline missing; budget unavailable" >&2
    return 0
  fi
  baseline="${baselines[0]}"
  if [[ "${#baselines[@]}" -gt 1 ]]; then
    baseline="$(printf '%s\n' "${baselines[@]}" | sort -V | tail -1)"
  fi

  local file_path="" charge=0 offset=0 limit="" read_fields
  if [[ "$TOOL_NAME" == "Read" ]]; then
    # Never evaluate input as shell. Count line slices in bytes, not characters.
    read_fields="$("$JQ" -r '.tool_input | (.file_path // ""), (.offset // 0), (.limit // "")' <<< "$PAYLOAD")" || return 0
    local -a fields=()
    mapfile -t fields <<< "$read_fields"
    file_path="${fields[0]:-}"
    offset="${fields[1]:-0}"
    limit="${fields[2]:-}"
    if [[ -f "$file_path" ]]; then
      if [[ "$offset" =~ ^[0-9]+$ && "$limit" =~ ^[0-9]+$ ]]; then
        charge="$(LC_ALL=C awk -v start="$offset" -v count="$limit" \
          'BEGIN { if (start < 1) start=1; stop=start+count }
           NR >= stop { exit } NR >= start { bytes += length($0)+1 }
           END { print bytes+0 }' "$file_path")"
      elif [[ "$offset" =~ ^[0-9]+$ && "$offset" -gt 1 ]]; then
        charge="$(LC_ALL=C awk -v start="$offset" 'NR >= start {bytes+=length($0)+1} END {print bytes+0}' "$file_path")"
      else
        charge="$(_file_byte_size "$file_path")"
      fi
    fi
  fi

  # Size-aware Bash charge (ADR-005 follow-up): resolve cat/find/grep/rg
  # targets to real paths and sum their byte sizes the way Read does above,
  # instead of a flat charge by command-name match alone. Relative targets
  # resolve against the payload's .cwd (PAYLOAD_CWD), not this hook
  # process's own $PWD — see _bash_target_bytes. $bash_target is empty when
  # the target cannot be resolved at all; jq then keeps the existing flat
  # unbounded fallback, which stays correct for a bare `find /`, a
  # piped/chained command, or a grep reading stdin.
  #
  # The `case` below is a cheap, deliberately loose pre-filter (plain glob,
  # no fork, no regex engine): it only gates whether it's worth paying for
  # resolution at all. It is a superset of jq's own word-boundary match
  # below (any command containing cat/find/grep/rg as a whole word also
  # contains it as a substring), so it can only ever over-match, never
  # under-match — a command jq would classify as unbounded is never skipped
  # here. Most Bash calls (`git status`, `tc task get`, `ls`, ...) contain
  # none of these substrings and skip this block entirely, which is also
  # why bash_unbounded_charge is fetched lazily inside the case rather than
  # unconditionally for every Bash call — that fetch is a real jq fork, and
  # a majority of Bash calls never need the value it produces.
  local bash_target="" bash_pipeline_json="null" pipeline_cost=""
  if [[ "$TOOL_NAME" == "Bash" ]]; then
    # Recognize terminal head limits and help/version stdin filters before
    # whole-file sizing. Tokenize only; never execute the proposed command.
    # Unsupported syntax or a missing helper retains the conservative cost.
    case "$TOOL_COMMAND" in
      *'|'*head*|*--help*'|'*|*--version*'|'*)
        if pipeline_cost="$(printf '%s' "$TOOL_COMMAND" | python3 "${SCRIPT_DIR}/lib/bash_pipeline_cost.py" 2>/dev/null)"; then
          if [[ "$pipeline_cost" =~ ^[0-9]+$ ]]; then
            bash_pipeline_json="$pipeline_cost"
          elif [[ "$pipeline_cost" == bounded ]]; then
            bash_pipeline_json='"bounded"'
          fi
        fi
        ;;
    esac
    if [[ "$bash_pipeline_json" == null ]]; then
      case "$TOOL_COMMAND" in
        *cat*|*find*|*grep*|*rg*)
          local bash_unbounded_charge
          bash_unbounded_charge="$("$JQ" -r '.thresholds.bash_unbounded_charge_bytes // 8000' "$baseline" 2>/dev/null)"
          [[ "$bash_unbounded_charge" =~ ^[0-9]+$ ]] || bash_unbounded_charge=8000
          bash_target="$(_bash_target_bytes "$TOOL_COMMAND" "$PAYLOAD_CWD" "$bash_unbounded_charge")" || bash_target=""
          ;;
      esac
    fi
  fi
  local bash_target_json="null"
  [[ "$bash_target" =~ ^[0-9]+$ ]] && bash_target_json="$bash_target"

  [[ -d "$STATE_DIR" ]] || mkdir -p "$STATE_DIR"
  if ! acquire_lock; then return 0; fi
  trap 'release_lock' EXIT
  local previous=/dev/null result
  [[ -f "$STATE_FILE" ]] && previous="$STATE_FILE"
  # Validate policy and compute prospective state in one jq call. State older
  # than 24h expires; old streak files are intentionally never imported.
  result="$("$JQ" -r --slurpfile policies "$baseline" --slurpfile previous "$previous" \
    --arg tool "$TOOL_NAME" --arg session "$SESSION_ID" --arg file "$file_path" \
    --arg command "$TOOL_COMMAND" --argjson readCharge "$charge" \
    --argjson bashTargetBytes "$bash_target_json" \
    --argjson bashPipelineBytes "$bash_pipeline_json" \
    --argjson stale "$STALENESS_SECONDS" '
    $policies[0] as $policy | $policy.thresholds as $t |
    if ([$t.byte_budget_bytes,$t.files_budget_count,$t.bash_bounded_charge_bytes,
         $t.bash_unbounded_charge_bytes] | all(type == "number" and . > 0 and floor == .)) and
       ($t.warning_ratio > 0 and $t.warning_ratio < 1) and $policy.byte_to_token_ratio > 0
    then . else error("invalid budget policy") end |
    (.tool_input // {}) as $input |
    ($previous[0] // {}) as $old |
    (if $old.session_id == $session and
        ((try ($old.updatedAt|fromdateiso8601) catch 0) > (now-$stale))
     then $old else {} end) as $state |
    (if $tool == "Read" then $file
     elif $tool == "Edit" or $tool == "Write" then ($input.file_path // "")
     else "" end) as $target |
    (if $tool == "Read" then $readCharge
     elif $tool == "Edit" then ($input.new_string // "" | utf8bytelength)
     elif $tool == "Write" then ($input.content // "" | utf8bytelength)
     elif $bashPipelineBytes == "bounded" then $t.bash_bounded_charge_bytes
     elif $bashPipelineBytes != null then $bashPipelineBytes
     elif ($command | test("(^|[;&|\\n]\\s*|\\s)(cat|find)(\\s|$)")) or
          (($command | test("(^|[;&|\\n]\\s*|\\s)(rg|grep)(\\s|$)")) and
           ($command | test("(^|\\s)(-m\\s*\\d+|--max-count[= ]\\d+)(\\s|$)") | not))
     then ($bashTargetBytes // $t.bash_unbounded_charge_bytes)
     else $t.bash_bounded_charge_bytes end) as $cost |
    (($state.bytesCharged // 0) + $cost) as $bytes |
    (($state.filesTouched // []) + (if $target == "" then [] else [$target] end) | unique) as $files |
    {session_id:$session,bytesCharged:$bytes,filesTouched:$files,
     updatedAt:(now|todateiso8601)} as $next |
    ([$bytes,($files|length),$t.byte_budget_bytes,$t.files_budget_count,
     (($bytes >= $t.byte_budget_bytes*$t.warning_ratio) or
      (($files|length) >= $t.files_budget_count*$t.warning_ratio)),
     ($bytes/$policy.byte_to_token_ratio|ceil),$cost] | @tsv),
    ($next|tojson)
    ' <<< "$PAYLOAD")" || {
      echo "[pretool-check] force-delegate budget state/policy invalid; budget unavailable" >&2
      release_lock; trap - EXIT; return 0;
    }

  local header="${result%%$'\n'*}" state="${result#*$'\n'}"
  local bytes files byte_budget file_budget warn tokens cost
  IFS=$'\t' read -r bytes files byte_budget file_budget warn tokens cost <<< "$header"
  local exceeded=""
  if [[ "$bytes" -gt "$byte_budget" ]] &&
     [[ "$cost" -gt "$FORCE_DELEGATE_FLOOR_BYTES" ]] &&
     ! budget_override_allows bytes "$byte_budget" "$bytes" "$baseline"; then
    exceeded="bytes"
  fi
  if [[ "$files" -gt "$file_budget" ]] &&
     ! budget_override_allows files "$file_budget" "$files" "$baseline"; then
    exceeded="${exceeded:+${exceeded} and }files"
  fi
  if [[ -n "$exceeded" ]]; then
    release_lock; trap - EXIT
    _ensure_manifest_loaded
    deny "Main session cost budget exceeded (${exceeded}): ${bytes}/${byte_budget} estimated bytes (~${tokens} tokens), ${files}/${file_budget} distinct file targets. This call: ${cost} estimated bytes. Narrow the call or delegate. Valid agents: ${VALID_AGENT_LIST}. COPILOT_FORCE_DELEGATE=off is the explicit bypass."
  fi
  printf '%s\n' "$state" > "${STATE_FILE}.tmp.$$"
  mv "${STATE_FILE}.tmp.$$" "$STATE_FILE"
  release_lock; trap - EXIT
  if [[ "$warn" == "true" ]]; then
    echo "[force-delegate-budget-warn] ${bytes}/${byte_budget} estimated bytes; ${files}/${file_budget} distinct file targets" >&2
  fi
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
  "tc task check-qa"
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
    # A direct framework Agent call is allowed only after the authority proves
    # either no_active or an exact prepared dispatch.  Without cc the hook
    # cannot distinguish a legacy call from an active marker bypass, so it
    # must not guess.
    deny "Journey dispatch state is indeterminate (verifier-unavailable). Restore cc, then inspect the journey state before retrying."
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
  # performs the non-consuming authoritative no-active lookup. Thus malformed
  # framing is a deny only when the session is actually active; a proven
  # no-active legacy call stays unchanged.
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

  if [[ "$schema" != "2.1" ]]; then
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
rule_extension_resolution
rule_destructive_command
rule_path_scope
rule_journey_dispatch

exit 0
