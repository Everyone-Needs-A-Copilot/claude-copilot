#!/usr/bin/env bash
# user-prompt-submit.sh — UserPromptSubmit hook for Claude Copilot
#
# PURPOSE:
#   Tracks the number of user prompts per session. When a session exceeds
#   ~500 turns, surfaces an advisory suggesting /pause + fresh /continue
#   to prevent context bloat and prompt-cache thrash (the "22-hour session" pattern).
#
# INPUT (stdin):
#   JSON object with fields from Claude Code:
#     session_id  — unique session identifier
#     prompt      — the user's prompt text
#     (other fields ignored)
#
# OUTPUT:
#   Exit 0 (always — this hook is advisory only, never blocks)
#   When advisory threshold reached: JSON with systemMessage field
#
# STATE FILE:
#   .claude/hooks/state/session-turns.json
#   Shape: { "<session_id>": { "turns": N, "firstSeen": "<ISO>", "lastSeen": "<ISO>", "warned": false, "warnedStrong": false } }
#
# ESCAPE HATCH:
#   Set COPILOT_SESSION_CAP=off to disable all advisories for a shell session.
#
# THRESHOLDS:
#   500 turns → first advisory (soft warning)
#   750 turns → stronger advisory (context likely severely degraded)
#
# STALE CLEANUP:
#   Sessions with lastSeen > 72 hours ago are pruned on each state write.

set -uo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${SCRIPT_DIR}/state"
STATE_FILE="${STATE_DIR}/session-turns.json"
LOCK_FILE="${STATE_DIR}/session-turns.lock"
JQ="/usr/bin/jq"

THRESHOLD_SOFT=500
THRESHOLD_STRONG=750
STALE_SECONDS=259200  # 72 hours

# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------
if [[ "${COPILOT_SESSION_CAP:-}" == "off" ]]; then
  exit 0
fi

# ---------------------------------------------------------------------------
# Read hook payload from stdin
# ---------------------------------------------------------------------------
PAYLOAD="$(cat)"

if [[ -z "$PAYLOAD" ]]; then
  exit 0
fi

SESSION_ID="$(printf '%s' "$PAYLOAD" | "$JQ" -r '.session_id // ""' 2>/dev/null || echo "")"

if [[ -z "$SESSION_ID" ]]; then
  # Malformed payload — exit cleanly
  exit 0
fi

# ---------------------------------------------------------------------------
# Lock helpers (mkdir atomicity, POSIX-guaranteed)
# ---------------------------------------------------------------------------
acquire_lock() {
  local i=0
  while ! mkdir "$LOCK_FILE" 2>/dev/null; do
    sleep 0.02
    i=$((i + 1))
    if [[ $i -ge 15 ]]; then
      # Could not acquire in ~300ms — allow and bail (never block user)
      exit 0
    fi
  done
}

release_lock() {
  rmdir "$LOCK_FILE" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# ISO timestamp helpers
# ---------------------------------------------------------------------------
now_iso() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

# ---------------------------------------------------------------------------
# State read/write
# ---------------------------------------------------------------------------
read_state() {
  if [[ ! -f "$STATE_FILE" ]]; then
    echo '{}'
    return
  fi
  # cat is sufficient — state file is always written by us as valid JSON
  cat "$STATE_FILE" 2>/dev/null || echo '{}'
}

# write_state <full_json>
write_state() {
  local json="$1"
  local tmp="${STATE_FILE}.tmp.$$"
  printf '%s\n' "$json" > "$tmp"
  mv "$tmp" "$STATE_FILE"
}

# ---------------------------------------------------------------------------
# Advisory emitter
# ---------------------------------------------------------------------------
emit_advisory() {
  local level="$1"  # "soft" or "strong"
  local turns="$2"

  local msg
  if [[ "$level" == "strong" ]]; then
    msg="Session length: ${turns}+ turns — context is severely degraded.\n\nThe Copilot diagnostic showed sessions past 750 turns exhibit heavy prompt-cache thrashing. The force-delegate hook and QA gate may receive incomplete context.\n\nStrong recommendation:\n1. Run /pause NOW to save a handoff work product\n2. Start a fresh session: /continue will reload just the essentials\n3. If you must continue, delegate ALL tasks to framework agents — do not work inline"
  else
    msg="Session length: ${turns}+ turns. The Copilot diagnostic showed sessions past this threshold correlate with prompt-cache thrashing and context bloat.\n\nConsider:\n1. Run /pause to save a handoff work product\n2. Start fresh: /continue will reload just the essentials\n3. If you must continue, be aware that further work will consume tokens at reduced efficiency"
  fi

  # systemMessage is the correct field per claude-code-guide UserPromptSubmit spec
  printf '{"systemMessage":"%s"}\n' \
    "$(printf '%s' "$msg" | sed 's/"/\\"/g; s/$/\\n/g' | tr -d '\n' | sed 's/\\n$//')"
}

# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------
acquire_lock
trap 'release_lock' EXIT

NOW="$(now_iso)"
NOW_EPOCH="$(date -u +%s)"

# Read current state
FULL_STATE="$(read_state)"

# Get this session's data — batch all field extractions into one jq call
# jq outputs 4 newline-separated values read into indexed vars (bash 3.2 compatible)
_i=0
while IFS= read -r _line; do
  case $_i in
    0) TURNS="$_line" ;;
    1) FIRST_SEEN="$_line" ;;
    2) WARNED="$_line" ;;
    3) WARNED_STRONG="$_line" ;;
  esac
  _i=$(( _i + 1 ))
done < <(printf '%s' "$FULL_STATE" | "$JQ" -r --arg sid "$SESSION_ID" '
  (.[$sid] // {}) as $s |
  ($s.turns // 0 | tostring),
  ($s.firstSeen // ""),
  ($s.warned // false | tostring),
  ($s.warnedStrong // false | tostring)
' 2>/dev/null)

TURNS="${TURNS:-0}"
WARNED="${WARNED:-false}"
WARNED_STRONG="${WARNED_STRONG:-false}"

# Increment turn counter
TURNS=$(( TURNS + 1 ))

# Set firstSeen if new session
if [[ -z "$FIRST_SEEN" ]]; then
  FIRST_SEEN="$NOW"
fi

# Determine advisory to emit (before writing state)
EMIT_LEVEL=""
if [[ "$TURNS" -ge "$THRESHOLD_STRONG" && "$WARNED_STRONG" == "false" ]]; then
  EMIT_LEVEL="strong"
  WARNED_STRONG="true"
  WARNED="true"
elif [[ "$TURNS" -ge "$THRESHOLD_SOFT" && "$WARNED" == "false" ]]; then
  EMIT_LEVEL="soft"
  WARNED="true"
fi

# Build updated session entry
UPDATED_SESSION="$(printf '{"turns":%d,"firstSeen":"%s","lastSeen":"%s","warned":%s,"warnedStrong":%s}' \
  "$TURNS" "$FIRST_SEEN" "$NOW" "$WARNED" "$WARNED_STRONG")"

# Merge session back into full state and prune stale — single jq call
PRUNED="$(printf '%s' "$FULL_STATE" | "$JQ" \
  --arg sid "$SESSION_ID" \
  --argjson entry "$UPDATED_SESSION" \
  --argjson cutoff "$(( NOW_EPOCH - STALE_SECONDS ))" \
  '.[$sid] = $entry |
   to_entries
   | map(select(
       (.value.lastSeen // "") != "" and
       (.value.lastSeen | gsub("T"; " ") | gsub("Z"; "") | strptime("%Y-%m-%d %H:%M:%S") | mktime) >= $cutoff
     ))
   | from_entries' 2>/dev/null || echo "$FULL_STATE")"

# Write atomically
write_state "$PRUNED"

release_lock
trap - EXIT

# ---------------------------------------------------------------------------
# On the first turn of a new session: inject Known References block
# ---------------------------------------------------------------------------
if [[ "$TURNS" -eq 1 ]] && command -v cc &>/dev/null; then
  _REFS=""

  # Standard path keys from cc config
  _SHARED_DOCS="$(cc config get paths.shared_docs --raw 2>/dev/null || true)"
  _KNOWLEDGE_REPO="$(cc config get paths.knowledge_repo --raw 2>/dev/null || true)"
  [[ -n "$_SHARED_DOCS" ]]    && _REFS="${_REFS}- shared_docs: ${_SHARED_DOCS}\n"
  [[ -n "$_KNOWLEDGE_REPO" ]] && _REFS="${_REFS}- knowledge_repo: ${_KNOWLEDGE_REPO}\n"

  # Arbitrary refs.* keys from cc config export
  while IFS='=' read -r _key _value; do
    # Trim all spaces from keys (keys are identifiers, never contain spaces).
    # Preserve internal spaces in values — only strip leading/trailing whitespace
    # so paths like "/Users/x/Google Drive/Shared Docs" survive intact.
    _key="${_key// /}"
    _value="${_value#"${_value%%[![:space:]]*}"}"  # ltrim
    _value="${_value%"${_value##*[![:space:]]}"}"  # rtrim
    if [[ "$_key" == refs.* ]] && [[ -n "$_value" ]]; then
      _ref_name="${_key#refs.}"
      _REFS="${_REFS}- ${_ref_name}: ${_value}\n"
    fi
  done < <(cc config export 2>/dev/null || true)

  # reference-type memory entries (show first 5, truncated)
  if command -v jq &>/dev/null; then
    _MEM_REFS="$(cc memory list --type reference --json 2>/dev/null | jq -r '.[0:5] | .[] | "- [memory] " + ((.content // "") | gsub("\n";" ") | .[0:100])' 2>/dev/null || true)"
    [[ -n "$_MEM_REFS" ]] && _REFS="${_REFS}${_MEM_REFS}\n"
  fi

  if [[ -n "$_REFS" ]]; then
    _MSG="Known references (this session):\n${_REFS}\nRegister a reference: cc config set refs.<name> <value>"
    printf '{"systemMessage":"%s"}\n' \
      "$(printf '%s' "$_MSG" | sed 's/"/\\"/g; s/$/\\n/g' | tr -d '\n' | sed 's/\\n$//')"
    exit 0
  fi
fi

# Emit advisory if needed (after lock released — output goes to Claude)
if [[ -n "$EMIT_LEVEL" ]]; then
  emit_advisory "$EMIT_LEVEL" "$TURNS"
fi

exit 0
