#!/usr/bin/env bash
# copilot-hook.sh — presence-check shim, vendored per-project.
#
# ARCHITECTURE ("vendor a shim, rules stay global"):
#   This is the ONLY hook file that is copied into a consuming project's
#   .claude/hooks/. It carries zero rule content — no force-delegate streak
#   logic, no /freeze path-scope logic, no security-rules.json, nothing
#   that decides "allow" vs "deny". Its one job is to locate the global
#   framework install and delegate to it. Every rule, and every FIX to a
#   rule, lives in exactly one place (the global install this shim
#   resolves), so fixing a guardrail fixes it in every project that
#   carries this shim, without touching that project's lock file.
#
# INVOCATION (registered by `cc settings-hook add`, see
#   core/ecosystem/mutations.py's DEFAULT_HOOK_ENTRIES):
#   bash "$CLAUDE_PROJECT_DIR/.claude/hooks/copilot-hook.sh" <event-name>
#   <event-name> is one of: session-start | pretool-check | subagent-stop
#                            | user-prompt-submit
#   stdin (the harness's JSON payload) is passed through untouched on the
#   happy path — this script never buffers or reparses it unless the
#   global install cannot be reached (see below).
#
# RESOLUTION ORDER (first hit wins):
#   1. $COPILOT_HOOKS_ROOT                              — explicit override
#   2. `cc config get paths.claude_copilot_root --raw`  — the machine-
#      stable install pointer (a symlink, e.g. ~/.claude/copilot), NOT a
#      raw repo path, so no project's settings.json ever bakes in one
#      machine's directory layout.
#   3. $HOME/.claude/copilot/.claude/hooks              — same path,
#      reachable without `cc` on PATH.
#   4. Give up (see FAIL-OPEN / FAIL-CLOSED below).
#
# FAIL-OPEN / FAIL-CLOSED, PER RULE CLASS (not one blanket policy):
#   The only hook whose exit code can ever BLOCK a tool call is
#   pretool-check.sh (PreToolUse). Of its four rules, only
#   rule_destructive_command (/careful) exists purely to stop a dangerous
#   shell command, and it only ever inspects the Bash tool. This shim
#   cannot itself evaluate security-rules.json — doing that would
#   re-vendor the rules it exists to keep global — so it approximates the
#   split using the one signal it can see before ever reaching the rules,
#   the tool name:
#     - tool_name == "Bash" AND the global install is unreachable
#       -> FAIL CLOSED (deny). A missing framework must never silently
#          wave through the one tool class its safety guard exists to
#          check.
#     - every other event/tool (SessionStart, SubagentStop,
#       UserPromptSubmit, and PreToolUse for Read/Edit/Write/Agent —
#       force-delegate, the QA gate's Agent arm, and /freeze's Edit/Write
#       arm — workflow discipline, not destructive-action safety)
#       -> FAIL OPEN. A missing framework must never brick editing or
#          session startup.
#   Neither branch is ever silent: a stderr diagnostic is always emitted,
#   and events that carry a systemMessage envelope (SessionStart,
#   UserPromptSubmit) get one too, so absence is visible in the session
#   transcript, not only on a stream nobody reads.
#   `.claude/copilot-required` (a project-local, zero-byte, NOT
#   framework-owned marker file) escalates EVERY event to fail closed
#   regardless of tool name — a project that wants zero tolerance for "no
#   enforcement running" opts into that explicitly.
#   `COPILOT_HOOKS_FAIL_OPEN=1` downgrades the Bash-closed default back to
#   open for one shell session (e.g. a laptop briefly off the framework
#   mount) — the same posture as every other escape hatch in this hook
#   suite (COPILOT_SAFETY=off, COPILOT_FREEZE=off, ...) — and it is
#   refused outright when .claude/copilot-required is present.
#
# VERSION SKEW:
#   SHIM_PROTOCOL_MIN/MAX below are THIS vendored shim's own declared
#   compatibility range for the one narrow contract it actually depends
#   on: "<event>.sh <event-name>" dispatch plus one env var
#   (COPILOT_HOOK_STATE_DIR). A global install publishes its current
#   protocol number at .claude/hooks/PROTOCOL_VERSION. Skew outside
#   [MIN,MAX] is a WARN, not a block — the shim still delegates, because
#   the calling convention it depends on is deliberately tiny and rarely
#   the part that changes, and a project pinned to an old shim must keep
#   running rather than break the moment the global install ships a
#   feature release. A global install may additionally publish
#   .claude/hooks/PROTOCOL_HARD_MIN to force shims below that floor to
#   stop delegating (treated exactly like "no compatible install
#   found") — the one lever a genuinely breaking change gets, and it is
#   opt-in and explicit on the framework side, never silent, and it is
#   how a breaking change is SIGNALED: bump PROTOCOL_HARD_MIN in the
#   global install and every project still carrying an old shim starts
#   reporting itself as unenforced (via this same fail-open/fail-closed
#   path) until `cc update --project` / `cc reconcile apply` refreshes
#   its vendored shim to one whose SHIM_PROTOCOL_MAX covers the new
#   floor.
#
# STATE:
#   Delegates with COPILOT_HOOK_STATE_DIR set to THIS project's own
#   .claude/hooks/state, so /freeze and force-delegate streaks are
#   per-project even though the rule scripts themselves are global (a
#   single shared .freeze file would otherwise let a freeze in one
#   project block edits in every other project on the machine).

set -uo pipefail

SHIM_PROTOCOL_MIN=1
SHIM_PROTOCOL_MAX=1

EVENT="${1:-}"
if [[ -z "$EVENT" ]]; then
  echo "[copilot-hook] usage: copilot-hook.sh <event-name>" >&2
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || SCRIPT_DIR=""
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(dirname "$(dirname "$SCRIPT_DIR")")}"
REQUIRED_MARKER="${PROJECT_DIR}/.claude/copilot-required"

_deny() {
  local reason="$1"
  local escaped="${reason//\"/\\\"}"
  # Also echo to stderr (in addition to the stdout permissionDecision JSON
  # the harness reads to render the deny). This exit path is non-zero, and
  # pretool-check.sh's own deny() documents that the harness only promotes
  # hook stderr into the visible transcript on a non-zero exit ("hook error:
  # [path]: [stderr content]"; a silent hook shows "No stderr output") — so
  # a deny with no stderr line risks looking like an unexplained crash
  # rather than an intentional, diagnosable policy block.
  echo "[copilot-hook] deny: ${reason}" >&2
  printf '{"permissionDecision":"deny","reason":"%s"}\n' "$escaped"
  exit 2
}

_exit_open() {
  local reason="$1"
  echo "[copilot-hook] $reason" >&2
  case "$EVENT" in
    session-start | user-prompt-submit)
      local escaped="${reason//\"/\\\"}"
      printf '{"systemMessage":"[copilot-hook] %s"}\n' "$escaped"
      ;;
  esac
  exit 0
}

# Only reached when the global install could not be resolved or used.
# Buffers stdin (rare/error path only — never on the happy delegate path)
# so a Bash tool_input.tool_name can be detected without a hard python3
# dependency; best-effort, and deliberately biased toward "assume Bash"
# on ambiguity (see NOTE below) rather than the reverse, because an
# undetected Bash call bypassing the destructive-command guard is the
# worse failure of the two.
_unreachable() {
  local reason="$1"
  local advice="Resolution order tried: \$COPILOT_HOOKS_ROOT, \`cc config get paths.claude_copilot_root\`, \$HOME/.claude/copilot/.claude/hooks. Run 'cc doctor' or install/refresh the framework. Escape hatch (Bash only, refused under .claude/copilot-required): COPILOT_HOOKS_FAIL_OPEN=1."
  local full="Copilot framework enforcement is unavailable: ${reason}. ${advice}"

  if [[ -f "$REQUIRED_MARKER" ]]; then
    _deny "${full} (blocked: .claude/copilot-required is present)"
  fi

  if [[ "$EVENT" != "pretool-check" ]]; then
    _exit_open "$full"
  fi

  # PreToolUse: read the payload once, live-in-the-failure-path only.
  local payload tool_name=""
  payload="$(cat 2>/dev/null || true)"
  if command -v python3 &>/dev/null; then
    # Emit "" (never a sentinel string) for every ambiguous case: unparseable
    # JSON, a non-object top level (e.g. a bare array), or a tool_name value
    # that isn't a string (e.g. {"tool_name":123}). A prior version of this
    # script printed the literal "__unknown__" from the except branch, which
    # is non-empty and so never matched the `[[ -z "$tool_name" ]]` check
    # below — that let ambiguous/malformed payloads fall through to
    # fail-open, exactly the case this function exists to fail closed on.
    # Whatever comes out of this python3 call MUST be empty on any ambiguity
    # so the single `-z` check below is the one place that decides.
    tool_name="$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    name = data.get("tool_name", "") if isinstance(data, dict) else ""
    print(name if isinstance(name, str) else "")
except Exception:
    print("")
' 2>/dev/null)"
  fi
  if [[ -z "$tool_name" ]]; then
    # No python3, unparseable payload, non-object JSON, or a non-string/empty
    # tool_name — cannot rule out Bash, so treat it as Bash for the
    # fail-closed decision (biased toward the safer outcome on ambiguity).
    tool_name="Bash"
  fi

  if [[ "$tool_name" == "Bash" && "${COPILOT_HOOKS_FAIL_OPEN:-}" != "1" ]]; then
    _deny "${full} (destructive-command guard cannot be evaluated for this Bash call; set COPILOT_HOOKS_FAIL_OPEN=1 to proceed without it for this session)"
  fi

  _exit_open "$full"
}

# ---------------------------------------------------------------------------
# 1. Resolve the hooks root.
# ---------------------------------------------------------------------------
# NOTE: an explicit $COPILOT_HOOKS_ROOT is honored strictly — if it is set
# but wrong, that is a misconfiguration to surface via _unreachable(), NOT
# a cue to silently fall through to step 2/3 of the ladder. Steps 2 and 3
# only run when $COPILOT_HOOKS_ROOT was never set at all.
HOOKS_ROOT=""
if [[ -n "${COPILOT_HOOKS_ROOT:-}" ]]; then
  HOOKS_ROOT="$COPILOT_HOOKS_ROOT"
else
  if command -v cc &>/dev/null; then
    configured="$(cc config get paths.claude_copilot_root --raw 2>/dev/null || true)"
    if [[ -n "$configured" ]]; then
      HOOKS_ROOT="${configured%/}/.claude/hooks"
    fi
  fi
  if [[ -z "$HOOKS_ROOT" || ! -d "$HOOKS_ROOT" ]] && [[ -d "$HOME/.claude/copilot/.claude/hooks" ]]; then
    HOOKS_ROOT="$HOME/.claude/copilot/.claude/hooks"
  fi
fi

if [[ -z "$HOOKS_ROOT" || ! -d "$HOOKS_ROOT" ]]; then
  _unreachable "no global framework install found"
fi

TARGET="$HOOKS_ROOT/${EVENT}.sh"
if [[ ! -x "$TARGET" ]]; then
  _unreachable "$TARGET is missing or not executable"
fi

# ---------------------------------------------------------------------------
# 2. Version-skew check. PROTOCOL_HARD_MIN can escalate to unreachable;
#    ordinary skew is advisory only (see header).
# ---------------------------------------------------------------------------
GLOBAL_HARD_MIN="$(cat "$HOOKS_ROOT/PROTOCOL_HARD_MIN" 2>/dev/null || echo "0")"
if [[ "$GLOBAL_HARD_MIN" =~ ^[0-9]+$ ]] && [[ "$SHIM_PROTOCOL_MAX" -lt "$GLOBAL_HARD_MIN" ]]; then
  _unreachable "this project's vendored shim (protocol <= $SHIM_PROTOCOL_MAX) is older than the global install's minimum ($GLOBAL_HARD_MIN); run 'cc update --project' or 'cc reconcile apply' to refresh it"
fi

GLOBAL_PROTOCOL="$(cat "$HOOKS_ROOT/PROTOCOL_VERSION" 2>/dev/null || echo "1")"
if [[ "$GLOBAL_PROTOCOL" =~ ^[0-9]+$ ]] && { [[ "$GLOBAL_PROTOCOL" -lt "$SHIM_PROTOCOL_MIN" ]] || [[ "$GLOBAL_PROTOCOL" -gt "$SHIM_PROTOCOL_MAX" ]]; }; then
  echo "[copilot-hook] version skew: this project's shim declares protocol [$SHIM_PROTOCOL_MIN,$SHIM_PROTOCOL_MAX], global install is at $GLOBAL_PROTOCOL — delegating anyway (advisory only); run 'cc update --project' to refresh the shim." >&2
fi

# ---------------------------------------------------------------------------
# 3. Delegate. stdin flows through `exec` untouched — no buffering, no
#    added latency on the happy path (PERFORMANCE TARGET <50ms).
# ---------------------------------------------------------------------------
export COPILOT_HOOK_STATE_DIR="${PROJECT_DIR}/.claude/hooks/state"
mkdir -p "$COPILOT_HOOK_STATE_DIR" 2>/dev/null || true

exec bash "$TARGET" "$@"
