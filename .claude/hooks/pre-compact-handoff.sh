#!/usr/bin/env bash
# pre-compact-handoff.sh — PreCompact hook for Claude Copilot (gap plan A9)
#
# PURPOSE:
#   Writes a handoff file from the current task BEFORE Claude Code compacts
#   the context, while full detail is still available:
#     <cwd>/.copilot/handoffs/<YYYYMMDD-HHMMSS>-<session8>.md
#   Shape (work-lifecycle.md "Pause or handoff"): Kickoff line, Outcome being
#   pursued, Verified, Governing decisions, Remaining, Evidence, plus the
#   owner's last three messages from the transcript.
#
# TASK SELECTION:
#   Among in-progress tasks, the one whose newest agent_log entry carries this
#   session id ("session" in the details JSON that tc stamps); else the most
#   recently updated in-progress task; else none (the file is still written
#   with the owner messages and the transcript path).
#
# INPUT (stdin): PreCompact JSON — session_id, transcript_path, cwd,
#   hook_event_name, trigger ("manual"|"auto"), custom_instructions.
#
# OUTPUT: exit 0 ALWAYS (never blocks compaction). One note on stderr naming
#   the file. When a task exists, the file is also stored as a `handoff`
#   work product (`tc wp store`).
#
# ESCAPE HATCH: COPILOT_PRE_COMPACT=off — skip entirely.

set -uo pipefail
trap 'exit 0' EXIT

[[ "${COPILOT_PRE_COMPACT:-}" == "off" ]] && exit 0
[[ -t 0 ]] && exit 0

JQ=/usr/bin/jq
[[ -x "$JQ" ]] || JQ="$(command -v jq || true)"
[[ -n "$JQ" ]] || { echo "[pre-compact-handoff] jq not found; no handoff written" >&2; exit 0; }

PAYLOAD="$(cat 2>/dev/null || true)"
[[ -n "$PAYLOAD" ]] || exit 0

SESSION="$("$JQ" -r '.session_id // empty' <<< "$PAYLOAD" 2>/dev/null || true)"
TRANSCRIPT="$("$JQ" -r '.transcript_path // empty' <<< "$PAYLOAD" 2>/dev/null || true)"
CWD="$("$JQ" -r '.cwd // empty' <<< "$PAYLOAD" 2>/dev/null || true)"
[[ -n "$CWD" ]] || CWD="${CLAUDE_PROJECT_DIR:-}"
[[ -n "$CWD" && -d "$CWD" ]] || { echo "[pre-compact-handoff] no usable cwd; no handoff written" >&2; exit 0; }
cd "$CWD" 2>/dev/null || exit 0

STAMP="$(date +%Y%m%d-%H%M%S)"
SESSION8="$(printf '%s' "${SESSION:-nosession}" | tr -c 'A-Za-z0-9' '_' | cut -c1-8)"
OUT_DIR="$CWD/.copilot/handoffs"
OUT="$OUT_DIR/${STAMP}-${SESSION8}.md"
mkdir -p "$OUT_DIR" 2>/dev/null || exit 0

# ---------------------------------------------------------------------------
# Task discovery (tc CLI only; every call fails soft).
# ---------------------------------------------------------------------------
TASK_ID=""
TASK_JSON=""
if command -v tc &>/dev/null && [[ -f "$CWD/.copilot/tasks.db" ]]; then
  INPROG="$(tc task list --status in_progress --json 2>/dev/null || true)"
  if "$JQ" -e 'type == "array" and length > 0' <<< "$INPROG" &>/dev/null; then
    if [[ -n "$SESSION" ]]; then
      LOG="$(tc log --limit 1000 --json 2>/dev/null || echo '[]')"
      TASK_ID="$("$JQ" -rn --arg s "$SESSION" --argjson prog "$INPROG" --argjson log "${LOG:-[]}" '
        ($prog | map(.id)) as $ids
        | [$log[] | select(.task_id as $t | $ids | index($t))]
        | group_by(.task_id) | map(max_by(.id))
        | map(select(((.details // "{}") | (try fromjson catch {})) | (.session? // "") == $s))
        | sort_by(.id) | last | .task_id // empty' 2>/dev/null || true)"
    fi
    if [[ -z "$TASK_ID" ]]; then
      TASK_ID="$("$JQ" -r 'sort_by(.updated_at, .id) | last | .id' <<< "$INPROG" 2>/dev/null || true)"
    fi
  fi
  if [[ "$TASK_ID" =~ ^[0-9]+$ ]]; then
    TASK_JSON="$(tc task get "$TASK_ID" --json 2>/dev/null || true)"
    "$JQ" -e 'type == "object"' <<< "$TASK_JSON" &>/dev/null || { TASK_ID=""; TASK_JSON=""; }
  else
    TASK_ID=""
  fi
fi

# ---------------------------------------------------------------------------
# Section builders. Each prints plain lines; prose is never hard-wrapped.
# ---------------------------------------------------------------------------
oneline() { tr '\n' ' ' | sed 's/  */ /g;s/^ //;s/ $//'; }

OUTCOME=""; VERIFIED="nothing recorded as verified"; DECISIONS="none recorded"
REMAINING=""; EVIDENCE_WP=""; EXEC_DIR=""

if [[ -n "$TASK_ID" ]]; then
  TITLE="$("$JQ" -r '.title // ""' <<< "$TASK_JSON")"
  DESC1="$("$JQ" -r '(.description // "") | split("\n\n")[0]' <<< "$TASK_JSON" | oneline)"
  PRD_ID="$("$JQ" -r '.prd_id // empty' <<< "$TASK_JSON")"
  PRD_TITLE=""
  if [[ -n "$PRD_ID" ]]; then
    PRD_TITLE="$(tc prd get "$PRD_ID" --json 2>/dev/null | "$JQ" -r '.title // empty' 2>/dev/null || true)"
  fi
  OUTCOME="TASK-${TASK_ID}: ${TITLE}"
  [[ -n "$DESC1" ]] && OUTCOME+=". ${DESC1}"
  [[ -n "$PRD_TITLE" ]] && OUTCOME+=" (PRD-${PRD_ID}: ${PRD_TITLE})"

  CONTRACT="$("$JQ" -c '(.metadata // "{}") | (try fromjson catch {}) | .acceptanceContract // {}' <<< "$TASK_JSON" 2>/dev/null || echo '{}')"
  WPS="$(tc wp list --task "$TASK_ID" --json 2>/dev/null || echo '[]')"
  "$JQ" -e 'type == "array"' <<< "$WPS" &>/dev/null || WPS='[]'

  # Newest work product carrying a QA packet (CRITERION or VERDICT lines).
  QA_TEXT="$("$JQ" -r '[.[] | select(((.content // "") | test("(^|\n)(CRITERION|VERDICT):")) or (.file_path != null and (.type | test("qa|verification|test"))))] | sort_by(.id) | last | if . == null then "" elif .content != null then .content else (.file_path // "") end' <<< "$WPS" 2>/dev/null || true)"
  if [[ -n "$QA_TEXT" && "$QA_TEXT" != *CRITERION:* && -f "$QA_TEXT" ]]; then QA_TEXT="$(cat "$QA_TEXT" 2>/dev/null || true)"; fi
  [[ -n "$QA_TEXT" && "$QA_TEXT" != *CRITERION:* && -f "$CWD/.copilot/$QA_TEXT" ]] && QA_TEXT="$(cat "$CWD/.copilot/$QA_TEXT" 2>/dev/null || true)"

  APPROVED_LINES=""
  if [[ -n "$QA_TEXT" ]]; then
    CRIT_LINES="$(grep -E '^(CRITERION|VERDICT):' <<< "$QA_TEXT" || true)"
    ARTIFACT_LINE="$(grep -E '^ARTIFACT:' <<< "$QA_TEXT" | tail -n 1 || true)"
    if [[ -n "$CRIT_LINES" ]]; then
      VERIFIED="$(oneline <<< "$(sed 's/$/ ;/' <<< "$CRIT_LINES")" | sed 's/ ;$//')"
      [[ -n "$ARTIFACT_LINE" ]] && VERIFIED+=" ; ${ARTIFACT_LINE}"
      # Criteria count as covered only when the packet's verdict approves.
      if grep -qE '^VERDICT:[[:space:]]*APPROVED' <<< "$QA_TEXT"; then
        APPROVED_LINES="$(grep -E '^CRITERION:' <<< "$QA_TEXT" || true)"
      fi
    fi
  fi

  D="$("$JQ" -r '
      [ (.doneBlock // empty | "Done block: " + (if type == "string" then . else tojson end)),
        (.excluded // empty | "Excluded: " + (if type == "array" then map(tostring) | join("; ") else tostring end)),
        (.assumptions // empty | "Assumptions: " + (if type == "array" then map(tostring) | join("; ") else tostring end)) ]
      | join(". ")' <<< "$CONTRACT" 2>/dev/null || true)"
  LOGD="$(tc log --task "$TASK_ID" --limit 200 --json 2>/dev/null | "$JQ" -r '[.[]? | select(.action | test("decision"; "i")) | "[" + .created_at + "] " + .action + (if .details then ": " + .details else "" end)] | reverse | join(" ; ")' 2>/dev/null || true)"
  [[ -n "$D" ]] && DECISIONS="$D"
  if [[ -n "$LOGD" ]]; then
    if [[ "$DECISIONS" == "none recorded" ]]; then DECISIONS="Logged: $LOGD"; else DECISIONS+=". Logged: $LOGD"; fi
  fi

  # Remaining: contract criteria with no approved CRITERION line, then open dependents.
  N=0
  while IFS=$'\t' read -r CID CEXP; do
    [[ -n "$CID" ]] || continue
    if [[ -n "$APPROVED_LINES" ]] && grep -qwF -- "$CID" <<< "$APPROVED_LINES"; then continue; fi
    N=$((N + 1)); REMAINING+="(${N}) criterion ${CID} not yet approved: ${CEXP} "
  done < <("$JQ" -r '.criteria[]? | [(.id // ""), ((.expected // "") | gsub("[\t\n]"; " "))] | @tsv' <<< "$CONTRACT" 2>/dev/null || true)
  if command -v sqlite3 &>/dev/null; then
    while IFS='|' read -r DID DTITLE DSTATUS; do
      [[ -n "$DID" ]] || continue
      N=$((N + 1)); REMAINING+="(${N}) open dependent TASK-${DID} (${DSTATUS}): ${DTITLE} "
    done < <(sqlite3 "$CWD/.copilot/tasks.db" "PRAGMA query_only=1; SELECT t.id, replace(t.title, char(10), ' '), t.status FROM task_dependencies d JOIN tasks t ON t.id = d.task_id WHERE d.depends_on = ${TASK_ID} AND t.status NOT IN ('completed','done','cancelled') ORDER BY t.id;" 2>/dev/null || true)
  fi
  REMAINING="$(oneline <<< "$REMAINING")"
  [[ -n "$REMAINING" ]] || REMAINING="no unapproved criteria or open dependents recorded; confirm against the task before closing"

  EVIDENCE_WP="$("$JQ" -r 'map("WP-" + (.id | tostring)) | join(", ")' <<< "$WPS" 2>/dev/null || true)"
  [[ -d "$CWD/.copilot/execution/$TASK_ID" ]] && EXEC_DIR=".copilot/execution/$TASK_ID"
  [[ -z "$EXEC_DIR" && -d "$CWD/.copilot/execution/TASK-$TASK_ID" ]] && EXEC_DIR=".copilot/execution/TASK-$TASK_ID"
else
  OUTCOME="no in-progress task found for this session; reconstruct the outcome from the owner messages below"
  REMAINING="no task recorded; start from the owner's most recent message below"
fi

OWNER=""
if [[ -n "$TRANSCRIPT" && -f "$TRANSCRIPT" ]]; then
  OWNER="$("$JQ" -Rr 'fromjson? | select(type == "object" and .type == "user")
      | (.message.content // .content) | select(type == "string" and length > 0)
      | gsub("[\r\n]+"; " ") | .[0:300]' "$TRANSCRIPT" 2>/dev/null | tail -n 3 || true)"
fi

# ---------------------------------------------------------------------------
# Write the file.
# ---------------------------------------------------------------------------
{
  echo '**Kickoff:** Read this file, then continue from "Remaining" item 1. Do not re-verify items under "Verified".'
  echo
  echo "**Outcome being pursued:** ${OUTCOME}"
  echo
  echo "**Verified:** ${VERIFIED}"
  echo
  echo "**Governing decisions:** ${DECISIONS}"
  echo
  echo "**Remaining:** ${REMAINING}"
  echo
  EV="transcript ${TRANSCRIPT:-unavailable}"
  [[ -n "$EVIDENCE_WP" ]] && EV+="; work products ${EVIDENCE_WP}"
  [[ -n "$EXEC_DIR" ]] && EV+="; ${EXEC_DIR}"
  echo "**Evidence:** ${EV}; this file."
  echo
  echo "**Last owner messages:**"
  if [[ -n "$OWNER" ]]; then
    while IFS= read -r LINE; do echo "- ${LINE}"; done <<< "$OWNER"
  else
    echo "- none found in the transcript"
  fi
} > "$OUT" 2>/dev/null || { echo "[pre-compact-handoff] could not write $OUT" >&2; exit 0; }

if [[ -n "$TASK_ID" ]]; then
  tc wp store --task "$TASK_ID" --type handoff --title "Pre-compaction handoff ${STAMP}" --file "$OUT" --agent pre-compact-hook --json >/dev/null 2>&1 \
    || echo "[pre-compact-handoff] could not store handoff work product for TASK-${TASK_ID}" >&2
fi

echo "[pre-compact-handoff] handoff written: ${OUT}" >&2
exit 0
