#!/usr/bin/env bash
# subagent-stop.sh — SubagentStop hook for Claude Copilot QA gate
#
# PURPOSE:
#   Manages QA-gate state in .claude/hooks/state/qa-gate.json.
#
#   When @agent-me completes: extracts a task_id from the agent's structured
#     "Task: TASK-N" header (see extract_task_id below), VALIDATES it against
#     THIS project's tc database (see task_id_valid_in_project), and only
#     then adds it to pending_tasks[session_id]. An ID that doesn't parse or
#     doesn't resolve locally never arms the gate (see fail-safe note in
#     handle_me_completion) — this is the RC-2 fix: a gate must never arm
#     against a task ID that only exists in a DIFFERENT project's database.
#   When @agent-qa completes: parses verdict, removes task from pending_tasks
#     on pass, increments retry counter on fail. After 3 failures, auto-unblocks
#     and emits an advisory systemMessage.
#
# INPUT (stdin):
#   JSON payload from Claude Code SubagentStop event. Expected fields:
#     session_id          — parent session identifier
#     agent_type          — subagent type (e.g. "me", "qa", "ta")
#     last_assistant_message — the subagent's final output text
#   (other fields ignored)
#
# TASK ID SOURCE OF TRUST (RC-2):
#   Task IDs are read from the agent's structured "Task: TASK-N | WP: WP-N"
#   header line (a contract-mandated field, not narrative prose — see
#   .claude/agents/_shared/output-contract.md and each agent's Output Format
#   section), then validated against the CURRENT project's tc database
#   (`tc task get <N> --json`, resolved via $CLAUDE_PROJECT_DIR). Both steps
#   are required: anchoring alone cannot rule out a well-formed header that
#   references the wrong project's task graph. See task_id_valid_in_project().
#
# ARM-PATH STRUCTURAL CROSS-CHECK (TASK-129-followup CHANGE 2):
#   Existence in this project's tc database (above) is necessary but, as of
#   a fourth review round, no longer treated as sufficient. handle_me_
#   completion() also requires task_status_arm_eligible(id) — the task's own
#   tc status must not be terminal (completed/cancelled) — before arming.
#   This is a guardrail-B-EQUIVALENT-IN-SPIRIT for the arm path (cross-check
#   against state the parser does not control, not just "did it parse"), but
#   an HONESTLY WEAKER one: see task_status_arm_eligible()'s own comment for
#   why "must be in_progress" (checked, and empirically unusable against
#   this project's real data) was rejected in favor of "must not be
#   terminal", and for what class of false match this does and does not
#   close.
#
# OUTPUT:
#   Exit 0 always (this hook is non-blocking for SubagentStop).
#   On 3rd consecutive QA failure: emits JSON with systemMessage advisory.
#
# STATE FILE:
#   .claude/hooks/state/qa-gate.json
#   Shape: {
#     "<session_id>": {
#       "pending_tasks": ["TASK-5", "TASK-12"],
#       "retries": { "TASK-5": 1 },
#       "armed_at": { "TASK-5": "<ISO>" },
#       "last_parse": { "TASK-5": "REJECTED — header parsed: TASK-5" },
#       "history": [{ "taskId": "TASK-5", "event": "me_completed", "ts": "<ISO>" }],
#       "lastSeen": "<ISO>"
#     }
#   }
#   "armed_at" and "last_parse" are ADDITIVE fields (TASK-129-followup guardrails
#   D and E). Old-shape state files written before this change simply lack
#   these keys — every reader falls back tolerantly (armed_at missing → use
#   lastSeen; last_parse missing → a generic "no QA feedback recorded yet"),
#   never crashes. "armed_at[tid]" is set only the FIRST time a task enters
#   pending_tasks in a given arm cycle, and is deleted whenever that task
#   leaves pending_tasks (qa_passed, full clear, or 3-strike auto-unblock) —
#   without that cleanup a task re-armed later would inherit a stale
#   timestamp and read as already-expired the instant it re-arms.
#   "last_parse[tid]" is a one-line human-readable note ("<verdict-label> —
#   <header-note>") describing how the MOST RECENT @agent-qa completion for
#   that task was interpreted — see compute_qa_verdict_label() and the
#   header_note construction in handle_qa_completion(). It exists purely so
#   pretool-check.sh's deny message (guardrail E) can explain WHY a gate
#   hasn't self-healed instead of repeating the same instruction verbatim on
#   every denied call.
#
# STALENESS RELEASE (guardrail D — TASK-129-followup):
#   The read-side staleness check that actually RELEASES a wedged gate lives
#   in pretool-check.sh's rule_qa_gate(), not here — this hook only WRITES
#   armed_at (above), it never evaluates age. See pretool-check.sh's own
#   header comment and rule_qa_gate() for the read-side logic and the
#   COPILOT_QA_GATE_MAX_AGE_HOURS override.
#
# LOG FILE:
#   .claude/hooks/state/qa-gate.log — warnings for missing task IDs etc.
#
# ADVERSARIAL PASS (TASK-131):
#   Optional second-model "try to break this diff" pass.  When a configured CLI
#   is present, @agent-qa can run `.claude/hooks/bin/adversarial-pass.sh` and
#   include the emitted ARTIFACT: adversarial-run|... line in its verdict.
#   Configure via COPILOT_ADVERSARIAL_CMD env var or auto-probe (codex/llm/mods).
#   When no CLI is present the script is a clean no-op — gate never blocked.
#
# ESCAPE HATCH:
#   Set COPILOT_QA_GATE=off to disable all QA gate state management.
#
# STALE CLEANUP:
#   Sessions with lastSeen > 72 hours are pruned on each state write.

set -uo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${COPILOT_HOOK_STATE_DIR:-${SCRIPT_DIR}/state}"
GATE_FILE="${STATE_DIR}/qa-gate.json"
LOCK_FILE="${STATE_DIR}/qa-gate.lock"
LOG_FILE="${STATE_DIR}/qa-gate.log"
JQ="/usr/bin/jq"

MAX_RETRIES=3
STALE_SECONDS=259200  # 72 hours

# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------
if [[ "${COPILOT_QA_GATE:-}" == "off" ]]; then
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
AGENT_TYPE="$(printf '%s' "$PAYLOAD" | "$JQ" -r '.agent_type // ""' 2>/dev/null || echo "")"
LAST_MSG="$(printf '%s' "$PAYLOAD" | "$JQ" -r '.last_assistant_message // ""' 2>/dev/null || echo "")"

# ---------------------------------------------------------------------------
# Design-stage unknowns check (R2 — "restore asking")
#
# WHY THIS IS HERE AND NOT IN THE AGENT FILES ALONE.
#
# Every agent's precedence section already exempts a `QUESTION:/OPTIONS:/CONTEXT:`
# block from its token budget, so the mechanism to ask has always existed. Nothing
# ever asked for it. It appears in fourteen agent files exclusively as an
# exception clause -- a right the specialists have and never exercise.
#
# What that cost, measured: on an identical brief containing a real contradiction
# ("Level 4 finish throughout" against "Garage included"), the vanilla arm asked,
# earned three sealed clarification answers, and priced 25 fewer labour hours. The
# framework arm, with its full design chain running, earned zero. It resolved
# internally what should have been a conversation, and priced a guess. For a
# framework whose stated purpose is experience-first software, that is the wrong
# trade: knowing what it cannot know is part of a specialist's job.
#
# So the unknowns get COUNTED. A design-stage agent that returns without stating
# its unknowns is not silently accepted, and "no unknowns" has to be claimed
# rather than achieved by omission. This hook is non-blocking by contract, so it
# records and surfaces -- it never refuses. The count is what makes "questions
# raised before building" checkable instead of impressionistic.
# ---------------------------------------------------------------------------
DESIGN_STAGE_AGENTS=" sd uxd uids ind cco ta cw "

record_design_unknowns() {
  local state_file="${STATE_DIR}/asking.json"
  local asked="none"

  # `Unknowns:` is the required slot; the QUESTION: block is the escalation for
  # an unknown that actually blocks. Either counts as having surfaced something.
  if printf '%s' "$LAST_MSG" | grep -qE '^[[:space:]]*QUESTION:'; then
    asked="question"
  elif printf '%s' "$LAST_MSG" | grep -qiE '^[[:space:]]*Unknowns:[[:space:]]*(none|n/a|-)?[[:space:]]*$'; then
    asked="declared-none"
  elif printf '%s' "$LAST_MSG" | grep -qiE '^[[:space:]]*Unknowns:'; then
    asked="unknowns"
  else
    asked="absent"
  fi

  mkdir -p "$STATE_DIR" 2>/dev/null || return 0

  # Read prior state as a plain string argument rather than --slurpfile with a
  # process substitution: that form silently produced an empty `prior` here, so
  # every write started from {} and the file only ever held the most recent
  # entry. A counter that resets to one is worse than no counter -- it reads as
  # real data.
  local prior='{}'
  if [[ -s "$state_file" ]]; then
    prior="$(cat "$state_file" 2>/dev/null || echo '{}')"
    printf '%s' "$prior" | "$JQ" -e 'type == "object"' >/dev/null 2>&1 || prior='{}'
  fi

  "$JQ" -n \
    --arg session "$SESSION_ID" \
    --arg agent "$AGENT_TYPE" \
    --arg asked "$asked" \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --argjson prior "$prior" \
    '$prior
     | .[$session] = ((.[$session] // {}) | .entries = ((.entries // []) + [{
         "agent": $agent, "asked": $asked, "ts": $ts
       }]))' > "${state_file}.tmp" 2>/dev/null \
    && mv "${state_file}.tmp" "$state_file" 2>/dev/null || true

  # -------------------------------------------------------------------------
  # Memory fires here, unasked (R5).
  #
  # Memory wrote ZERO entries across seven framework trials. It is
  # instruction-triggered, so during ordinary work it never runs -- and therefore
  # carries nothing between real sessions either, while its always-loaded cost is
  # paid every session regardless. The recommendation was blunt: either it fires
  # unasked, or it stops being paid for.
  #
  # WHY THIS TRIGGER AND NOT A GENERAL ONE. "Store anything interesting" is how a
  # memory store fills with noise and stops being worth reading, which costs more
  # than never firing. An unresolved unknown is the narrowest high-value class
  # available: rare, durable, invisible in the code, and precisely what is lost
  # when a session ends -- the next session re-derives it or, worse, silently
  # decides it. It is also the exact gap the sealed-answer benchmark exposed.
  #
  # Deliberately not stored: declared-none (nothing to carry), absent (already
  # surfaced above), and QUESTION blocks (the user is answering those in-session,
  # so the answer belongs in the transcript, not in a store of open items).
  # -------------------------------------------------------------------------
  if [[ "$asked" == "unknowns" ]] && command -v cc &>/dev/null \
    && [[ "${COPILOT_MEMORY_AUTOCAPTURE:-on}" != "off" ]]; then
    local unknown_text
    unknown_text="$(printf '%s' "$LAST_MSG" \
      | grep -iE '^[[:space:]]*Unknowns:' \
      | head -1 \
      | sed -E 's/^[[:space:]]*[Uu]nknowns:[[:space:]]*//' \
      | cut -c1-400)"
    if [[ -n "$unknown_text" ]]; then
      cc memory store \
        --type context \
        --tags "unknown,${AGENT_TYPE},auto" \
        "Open unknown raised by @agent-${AGENT_TYPE}: ${unknown_text}" \
        >/dev/null 2>&1 || true
    fi
  fi

  # Surface only the omission. A specialist that stated its unknowns needs no
  # commentary; one that skipped the required slot is the case worth naming, and
  # naming it in the transcript is what stops the omission being free.
  if [[ "$asked" == "absent" ]]; then
    "$JQ" -n --arg agent "$AGENT_TYPE" \
      '{systemMessage: ("@agent-" + $agent + " returned no `Unknowns:` line. That slot is required for a design-stage specialist: state the unknowns, or state `Unknowns: none` and own it. An unknown that blocks the work escalates as a QUESTION:/OPTIONS:/CONTEXT: block, which is exempt from every token budget.")}' \
      2>/dev/null || true
  fi
}

if [[ -n "$SESSION_ID" ]] && [[ "$DESIGN_STAGE_AGENTS" == *" $AGENT_TYPE "* ]]; then
  record_design_unknowns
fi

# Only act on me and qa agent types
if [[ "$AGENT_TYPE" != "me" && "$AGENT_TYPE" != "qa" ]]; then
  exit 0
fi

if [[ -z "$SESSION_ID" ]]; then
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
      # Could not acquire in ~300ms — bail, non-blocking
      exit 0
    fi
  done
}

release_lock() {
  rmdir "$LOCK_FILE" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# ISO timestamp
# ---------------------------------------------------------------------------
now_iso() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log_warn() {
  local msg="$1"
  printf '[%s] WARN: %s\n' "$(now_iso)" "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

log_info() {
  local msg="$1"
  printf '[%s] INFO: %s\n' "$(now_iso)" "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# State read/write
# ---------------------------------------------------------------------------
read_gate_state() {
  if [[ ! -f "$GATE_FILE" ]]; then
    echo '{}'
    return
  fi
  "$JQ" '.' "$GATE_FILE" 2>/dev/null || echo '{}'
}

write_gate_state() {
  local json="$1"
  local tmp="${GATE_FILE}.tmp.$$"
  printf '%s\n' "$json" > "$tmp"
  mv "$tmp" "$GATE_FILE"
}

# Prune sessions with lastSeen > 72h
prune_stale() {
  local state="$1"
  printf '%s' "$state" | "$JQ" --argjson stale "$STALE_SECONDS" '
    to_entries
    | map(select(
        (.value.lastSeen // "") != "" and
        (now - (.value.lastSeen | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime)) < $stale
      ))
    | from_entries
  ' 2>/dev/null || printf '%s' "$state"
}

# Get or initialize session entry
get_session() {
  local state="$1"
  printf '%s' "$state" | "$JQ" -r --arg sid "$SESSION_ID" '
    .[$sid] // {"pending_tasks":[],"retries":{},"history":[],"lastSeen":""}
  ' 2>/dev/null || echo '{"pending_tasks":[],"retries":{},"history":[],"lastSeen":""}'
}

# ---------------------------------------------------------------------------
# Task ID extraction
#
# RC-2 (the false-gate incident this fix closes): the previous implementation
# was `grep -oE 'TASK-[0-9]+' | head -1` over the ENTIRE raw message -- a
# scan of free narrative prose, not a structured field. It scraped a stray
# "TASK-612" mentioned somewhere in an agent's summary (a reference in
# passing, not the agent's own task) and armed a QA gate against it, even
# though TASK-612 does not exist in this project's tc database at all -- it
# exists only in a DIFFERENT project's (convoco's) database.
#
# Fix: anchor extraction to the structured "Task: TASK-N | WP: WP-N" header
# line that @agent-me's and @agent-qa's Output Format contracts REQUIRE as
# their first reported line (see .claude/agents/me.md, .claude/agents/qa.md,
# .claude/agents/_shared/output-contract.md's agent-to-agent register --
# "Task/WP IDs" are called out there as structured, precision-over-prose
# fields, not narrative). A bare "TASK-N" appearing mid-sentence anywhere
# else in the message body no longer matches.
#
# This narrows the surface but is not sufficient alone -- a well-formed
# "Task:" header can still reference the wrong project's task graph (stale
# context, a copy-pasted example, cross-session bleed). See
# task_id_valid_in_project() below, which is the hard boundary: extraction
# picks a CANDIDATE, validation is what decides whether it may arm a gate.
#
# Returns empty string if no structured Task: header line is found.
#
# DECORATION TOLERANCE (defect fix — over-strict extraction wedge): the
# anchored match above narrowed the surface correctly (RC-2) but then
# over-narrowed it further than the agents' own contract requires. The
# Output Format templates never mandate plain-text "Task: TASK-N" —
# real @agent-me/@agent-qa summaries routinely render it through whatever
# markdown their model reaches for: **Task:** TASK-129 (bold label),
# - Task: TASK-129 / * Task: TASK-129 (list item), ### Task: TASK-129
# (heading), | Task: TASK-129 | (table row). All of those are still,
# structurally, the SAME field — a line that IS the Task: header, just
# wrapped in markdown decoration — and none of them should have to fail
# extraction just because the label isn't the first four bytes on the line.
#
# So: find lines containing the literal "Task:" label, strip only recognized
# markdown decoration from their front (whitespace, ATX heading hashes, list
# markers -/*/+, table pipes, and bold/italic wrappers **/__/*/_), and
# re-check that what's LEFT still starts with "Task:". This keeps the
# line-anchoring guarantee that made RC-2 possible to fix in the first
# place: a bare "TASK-129" mentioned in running prose never has the literal
# "Task:" label immediately preceding it once decoration is stripped, so it
# still cannot arm a gate by accident. Only markdown WRAPPING the real
# header is tolerated — a sentence that happens to contain "Task:" followed
# later by an unrelated ID is not.
#
# AUTHORSHIP vs QUOTING (defect fix — TASK-129-followup guardrail A): the
# decoration tolerance above was itself over-tolerant in one direction QA
# reproduced live — it could not tell the agent AUTHORING a "Task:" header
# from the agent QUOTING someone else's. A QA message containing
# "> Task: TASK-999" inside a blockquote (or the same text fenced, or
# 4-space-indented) matched just as readily as a real header, because
# blockquote/code markers were being treated as more decoration to strip
# rather than as a signal that the line ISN'T the agent's own. That is the
# same permanent-wedge failure mode RC-2 fixed, reopened via a new trigger:
# a quoted reference to a real task ID could arm or mutate the wrong gate.
#
# Fix: reject a line as a header if it is quoted or code; accept it if it is
# merely decorated. Specifically, before decoration-stripping:
#   - REJECT any line inside a fenced code block (``` or ~~~ — tracked
#     STATEFULLY across the whole line-by-line scan below, because whether
#     a given line is "inside a fence" depends on every fence delimiter
#     seen so far, not on that line in isolation).
#   - REJECT any line indented 4+ spaces or by a leading tab (indented code
#     block per CommonMark) — checked on the RAW line, since trimming
#     leading whitespace first (as the old code did unconditionally) is
#     exactly what erases the signal being checked for.
#   - REJECT any line whose first non-whitespace character is '>'
#     (blockquote).
#   - ACCEPT list markers (-, *, +) as decoration, same as before. This is a
#     deliberate, narrower tradeoff than the other three: QA also found
#     "- Task: TASK-999" used as a quoting bullet, and a bullet is
#     structurally indistinguishable from a real agent authoring its own
#     header as a list item (agents legitimately do this). Rejecting list
#     markers outright would re-break real decorated headers with no
#     reliable way to tell the two apart from formatting alone. This is
#     safe to leave open ONLY because guardrail B (cross-check against
#     pending, see handle_qa_completion) is what actually neutralizes it:
#     even a bullet-quoted real task ID cannot arm or mutate a gate that
#     was never armed for that task. Extraction stopped being the sole
#     line of defense; see the guardrail B comment for why that shift
#     matters.
#
# AMBIGUITY (guardrail C): a message can legitimately contain more than one
# header-shaped "Task:" line (e.g. two authored bullets, one per line, both
# passing the authorship checks above). Picking the first one silently, as
# the previous implementation did, risks silently clearing or penalizing
# the WRONG task when the two disagree. So this function now scans the
# WHOLE message (not stopping at the first match), collects every DISTINCT
# id found on a header-shaped line, and:
#   - 0 distinct ids  → returns "" (no header found; unchanged behavior)
#   - 1 distinct id   → returns it (a single id repeated across several
#                       header-shaped lines is NOT ambiguity — only count
#                       DISTINCT ids, per QA's explicit note)
#   - 2+ distinct ids → returns "AMBIGUOUS:<id1> <id2> ..." so the caller
#                       can tell "ambiguous" apart from "not found" (an
#                       empty string) and fail closed rather than guess.
#
# WHY A STDOUT SENTINEL AND NOT A GLOBAL: an earlier version of this fix set
# a global (_EXTRACT_AMBIGUOUS=1) as a side channel instead of overloading
# the return string. That does not work here and was caught by this file's
# own test suite: EVERY call site invokes this function as
# `task_id="$(extract_task_id "$msg")"` — command substitution — and bash
# always runs the right-hand side of `$(...)` in a SUBSHELL. A subshell gets
# its own copy of the global; whatever it assigns is discarded the instant
# the subshell exits, so the caller's global is never actually updated. The
# only channel that reliably survives a `$(...)` call is the subshell's
# stdout, which is exactly what command substitution captures — hence
# encoding ambiguity IN the returned string via an unambiguous prefix
# ("AMBIGUOUS:") that can never collide with a real "TASK-N" return, rather
# than trying to smuggle a second value out through shell global state.
#
# FENCE-CLOSE INDENT RULE (defect fix — TASK-129-followup CHANGE 1, fourth
# review round): the fence tracker above matched an open OR close delimiter
# run with `^[[:space:]]*(\`{3,}|~{3,})` — unlimited leading whitespace on
# either side — and decided a close purely by comparing delimiter CHARACTER
# and run LENGTH against the open. QA's live repro exploited exactly the
# dimension that check never looked at: indentation.
#
#     ```
#         ```
#     Task: TASK-1
#     ```
#
# The inner ` ``` ` is indented 4 spaces — under CommonMark that is an
# INDENTED CODE BLOCK fence delimiter, i.e. ordinary literal text sitting
# inside the outer fence, not a fence delimiter in its own right. This
# tracker treated it as a real close anyway (same char, same length),
# de-fenced early, and exposed "Task: TASK-1" — nested example text, not the
# agent's own header — to extraction on the very next line.
#
# Fix, per CommonMark's own rule (a closing fence may be indented at most 3
# spaces; 4+ makes it literal content): a delimiter run is only accepted as
# a CLOSE when its own leading indent is 3 spaces or fewer AND contains no
# tab (a leading tab is, by the indented-code-block check just below this
# loop, always treated as 4+ columns of indent, per CommonMark's tab-stop
# rule — the same convention already used for indented-code Task: lines).
# Deliberately scoped to the CLOSE only, not the OPEN: over-indenting an
# OPEN at worst makes this tracker swallow MORE text as "inside a fence"
# than a strict CommonMark parser would (a false negative on extraction —
# fail-closed, not a bypass), so it carries none of the security weight the
# close side does and is left alone rather than touched speculatively.
# A 3-space-indented close is still spec-valid and must still close (QA
# confirmed this works today and it must not regress) — only 4+ is excluded.
# ---------------------------------------------------------------------------
extract_task_id() {
  local msg="$1"
  local line stripped
  local task_pattern='^Task:[[:space:]]*(\*\*|__|\*|_)*[[:space:]]*TASK-[0-9]+'
  # Fence tracking per CommonMark: a fence opened with backticks is closed
  # ONLY by a backtick run of at least the opening length; a tilde fence
  # only by tildes likewise. fence_char is empty when not inside a fence.
  # An unclosed fence at EOF means every subsequent line stays "inside"
  # (fail closed) — this falls out naturally since fence_char is simply
  # never cleared once the input runs out.
  local fence_char=""
  local fence_len=0
  local found_ids=""

  while IFS= read -r line; do
    if [[ "$line" =~ ^([[:space:]]*)(\`{3,}|~{3,}) ]]; then
      local indent="${BASH_REMATCH[1]}"
      local run="${BASH_REMATCH[2]}"
      local run_len=${#run}
      local run_char="${run:0:1}"
      # CommonMark fence-close indent rule (TASK-129-followup CHANGE 1): a
      # closing run indented 4+ spaces, or by a leading tab (tab = 4+
      # columns, same convention as the indented-code-block check below),
      # is literal in-fence content, not a real close. See the
      # "FENCE-CLOSE INDENT RULE" comment above for the exploit this closes.
      local indent_ok=1
      if [[ "$indent" == *$'\t'* ]] || [[ "${#indent}" -gt 3 ]]; then
        indent_ok=0
      fi
      if [[ -z "$fence_char" ]]; then
        # Opening a new fence. (Indent is not restricted on the open side —
        # see the comment above for why that asymmetry is deliberate and
        # safe.)
        fence_char="$run_char"
        fence_len=$run_len
      elif [[ "$run_char" == "$fence_char" ]] && [[ "$run_len" -ge "$fence_len" ]] && [[ "$indent_ok" -eq 1 ]]; then
        # Closing run: same delimiter character, run length >= opening,
        # indented 3 spaces or fewer.
        fence_char=""
        fence_len=0
      fi
      # Any other delimiter run (wrong char, too short, or over-indented)
      # encountered while a fence is open is ordinary content inside that
      # fence, not a close — fall through and let the in-fence check below
      # skip it.
      continue
    fi
    if [[ -n "$fence_char" ]]; then
      continue
    fi

    [[ "$line" == *"Task:"* ]] || continue

    # Indented code block: 4+ leading spaces, or a leading tab. Checked on
    # the RAW line before any trimming.
    if [[ "$line" == $'\t'* ]] || [[ "$line" =~ ^[[:space:]]{4,} ]]; then
      continue
    fi

    # Blockquote: first non-whitespace character is '>'.
    local first_nonspace
    first_nonspace="$(printf '%s' "$line" | sed -E 's/^[[:space:]]*//' | cut -c1 2>/dev/null)" || first_nonspace=""
    if [[ "$first_nonspace" == ">" ]]; then
      continue
    fi

    stripped="$(printf '%s' "$line" | sed -E \
      -e 's/^[[:space:]]*//' \
      -e 's/^(#{1,6})[[:space:]]+//' \
      -e 's/^[-*+][[:space:]]+//' \
      -e 's/^\|[[:space:]]*//' \
      -e 's/^(\*\*|__|\*|_)+//' \
      2>/dev/null)" || stripped=""

    if [[ "$stripped" =~ $task_pattern ]]; then
      local this_id
      this_id="$(printf '%s' "${BASH_REMATCH[0]}" | grep -oE 'TASK-[0-9]+' 2>/dev/null)" || this_id=""
      if [[ -n "$this_id" ]] && [[ " ${found_ids} " != *" ${this_id} "* ]]; then
        found_ids="${found_ids} ${this_id}"
      fi
    fi
  done <<< "$msg"

  found_ids="$(printf '%s' "$found_ids" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' 2>/dev/null)" || found_ids=""

  local id_count=0
  if [[ -n "$found_ids" ]]; then
    id_count="$(printf '%s\n' "$found_ids" | grep -oE 'TASK-[0-9]+' | wc -l | tr -d '[:space:]')" || id_count=0
    [[ "$id_count" =~ ^[0-9]+$ ]] || id_count=0
  fi

  if [[ "$id_count" -eq 0 ]]; then
    echo ""
    return
  fi
  if [[ "$id_count" -eq 1 ]]; then
    echo "$found_ids"
    return
  fi

  # 2+ distinct header-shaped ids — ambiguous. Fail closed: see the
  # "WHY A STDOUT SENTINEL" note above for why this is encoded in the
  # return string rather than a global.
  echo "AMBIGUOUS:${found_ids}"
}

# Extract ALL TASK-N references from a message string.
# Returns a JSON array of unique task IDs, e.g. '["TASK-5","TASK-12"]'
#
# NOTE (sibling audit, see JOB-1 item 5): this one intentionally still scans
# the whole message body rather than anchoring to the "Task:" header, because
# it feeds ONLY the qa-pass CLEAR path (handle_qa_completion's targeted vs.
# full-clear decision) -- never the arm path. A stray extra ID here can at
# most cause a targeted-clear to also happen to match, or fall through to
# the already-safe full-clear fallback; it can never arm a gate against an
# unvalidated task. That asymmetry (arm must be conservative, clear may be
# generous -- see fail-safe note in handle_me_completion) is why this
# function was left unanchored rather than changed to match extract_task_id.
extract_all_task_ids() {
  local msg="$1"
  local ids_raw
  ids_raw="$(printf '%s' "$msg" | grep -oE 'TASK-[0-9]+' | sort -u)" || ids_raw=""
  if [[ -z "$ids_raw" ]]; then
    echo '[]'
    return
  fi
  # Build a JSON array
  printf '%s\n' "$ids_raw" | "$JQ" -R . | "$JQ" -sc . 2>/dev/null || echo '[]'
}

# ---------------------------------------------------------------------------
# Task ID validation — confirm a task ID actually exists in THIS project's
# tc (Task Copilot) database before it is trusted to arm a gate.
#
# This is the sharp edge RC-2 exposed: a QA gate in one project (here,
# copilot-control-tower) was armed against a task ID that resolves only in
# a DIFFERENT project's database (convoco's). Anchored extraction (above)
# narrows *where* a candidate ID can come from; it cannot rule out a
# well-formed header pointing at the wrong project. Validation against the
# LOCAL tc database is the one channel that is actual ground truth rather
# than another heuristic: tc task IDs are project-scoped integers backed by
# a per-project SQLite file, and `tc task get <N> --json` resolves that file
# by walking up from cwd to the nearest `.copilot/tasks.db` -- so "does this
# ID exist in the project we are actually running in" is a real check, not
# a guess.
#
# Returns 0 (valid, arm-eligible) only when `tc task get <N> --json`
# succeeds against the project rooted at $CLAUDE_PROJECT_DIR (the env var
# Claude Code sets for hook invocations; falls back to $PWD, which is what
# the harness uses as cwd for hooks anyway). Any other outcome — malformed
# ID, tc not on PATH, no tasks.db for this project, or a well-formed ID tc
# reports as not found — returns non-zero. There is deliberately no
# "unknown, assume valid" branch: see the fail-safe note at the call site
# for why "cannot validate" and "invalid" get the identical response.
# ---------------------------------------------------------------------------
task_id_valid_in_project() {
  local task_id="$1"
  local num="${task_id#TASK-}"
  [[ "$num" =~ ^[0-9]+$ ]] || return 1

  command -v tc &>/dev/null || return 1

  local project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"
  ( cd "$project_dir" 2>/dev/null && tc task get "$num" --json >/dev/null 2>&1 )
}

# ---------------------------------------------------------------------------
# task_status_arm_eligible — structural cross-check on the ARM path
# (TASK-129-followup CHANGE 2; a guardrail-B-EQUIVALENT-IN-SPIRIT for
# handle_me_completion, not an equal-strength one — see the honest
# assessment at the end of this comment).
#
# WHY THIS EXISTS. Four review rounds have each found a NEW way to make
# embedded/quoted content read as an authored "Task:" header (see
# extract_task_id()'s AUTHORSHIP vs QUOTING and FENCE-CLOSE INDENT RULE
# comments for the two most recent). Each parser fix was correct in
# isolation; a new vector followed every time. On the QA path this stopped
# mattering as much: guardrail B (handle_qa_completion, above) does not
# lean on the parser being perfect — it cross-checks the extracted id
# against pending_tasks[SESSION_ID], state the parser does not control, so
# even a flawless-looking false match cannot clear or mutate a gate that
# was never armed for that task. The ARM path (handle_me_completion) had no
# equivalent: extraction alone decided what arms the gate, and
# task_id_valid_in_project() only confirms the id exists SOMEWHERE in this
# project's tc database, not that it was authored HERE, NOW, by the
# completion that is actually running.
#
# CORROBORATION SOURCE CHOSEN: the task's own STATUS in this project's tc
# database (already the same `tc task get` ground truth
# task_id_valid_in_project() uses for existence — this is state the parser
# has no way to influence). A TERMINAL status — "completed" or "cancelled"
# — means the tc database itself already considers this id's work over; a
# completion arriving *now* citing that id as freshly finished is
# inherently suspicious, and it is exactly the shape QA's live repro takes:
# a real, already-completed task id (TASK-1 in this project) embedded in
# nested fence content that a naive parser reads as a fresh header.
# Terminal status is rejected. "pending", "in_progress", and "blocked" are
# all accepted as arm-eligible.
#
# WHY NOT "must be in_progress / assigned" (this project's own framing's
# stated first preference): checked empirically against this project's real
# tc database before choosing this shape — `tc task list --status
# in_progress --json` returns ZERO of 150 tasks (130 completed, 20
# pending). Nothing in the current @agent-me workflow, `tc worker` dispatch
# (tools/tc/src/tc/commands/worker.py — never calls claim_task, only
# releases a budget-breached task BACK to pending), or any agent/command
# file ever calls `tc task claim` (the one tc command that sets
# status=in_progress) as part of ordinary operation — me.md's own
# documented Workflow step 1 is `tc task get <taskId> --json`, an existence
# check, never a claim. Requiring in_progress here would not narrow the arm
# path, it would DELETE it: every legitimate @agent-me completion under the
# actual, currently-used workflow would fail this check and log a WARN
# instead of arming, on 100% of real completions. A guardrail that always
# fires is not a guardrail; it is dead code with a log line, and it teaches
# whoever reads qa-gate.log to skim past WARN entries wholesale — eroding
# the signal value of every OTHER WARN this file emits, including the
# genuinely dangerous ones (RC-2's cross-project id, guardrail C's
# ambiguity, this same function's own terminal-status rejection).
#
# SESSION/TASK DISPATCH CORRELATION (the framing's second-preference
# candidate): not available. Checked: this hook's documented and consumed
# SubagentStop payload fields are session_id, agent_type, and
# last_assistant_message only (see the file header); Claude Code's
# SubagentStop event carries no dispatched-task-id field this hook could
# cross-check against for a live, in-session Agent(subagent_type="me")
# call. `tc worker`'s headless dispatch path does correlate a task id to a
# specific invocation, but that is a DIFFERENT dispatch mechanism from the
# one this hook fires for (a direct main-session Agent tool call), so it
# cannot be relied on here without inventing a source that isn't actually
# wired into this code path.
#
# HONEST ASSESSMENT (asked for explicitly — TASK-129-followup): this is
# materially weaker than guardrail B, and that is a real limitation, not
# just a caveat. Guardrail B rules out every id that was never armed for
# THIS session — a hard, near-total bar. This check only rules out ids the
# project's own database has already marked done or abandoned; a "pending"
# id (the majority non-terminal state actually in use here, 20/150 real
# tasks) still passes, because there is no session/task dispatch
# correlation available to distinguish "the task @agent-me is genuinely
# completing right now" from "an unrelated pending task's id, embedded or
# quoted." A pending-status false match therefore still arms. This closes
# the SPECIFIC vector QA reproduced (a stale/completed real id read out of
# embedded content) without claiming to close the general class that
# extraction-hardening alone keeps reopening.
#
# Ambiguity/failure fails CLOSED: malformed id, `tc` unavailable, no JSON
# back, or an unreadable/missing status all return non-zero (do not arm) —
# there is no "unknown, assume eligible" branch, mirroring
# task_id_valid_in_project()'s own fail-safe direction.
# ---------------------------------------------------------------------------
task_status_arm_eligible() {
  local task_id="$1"
  local num="${task_id#TASK-}"
  [[ "$num" =~ ^[0-9]+$ ]] || return 1

  command -v tc &>/dev/null || return 1

  local project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"
  local task_json status
  task_json="$(cd "$project_dir" 2>/dev/null && tc task get "$num" --json 2>/dev/null)" || return 1
  [[ -n "$task_json" ]] || return 1

  status="$(printf '%s' "$task_json" | "$JQ" -r '.status // ""' 2>/dev/null)" || status=""
  case "$status" in
    completed|cancelled) return 1 ;;
    "") return 1 ;;
    *) return 0 ;;
  esac
}

# ---------------------------------------------------------------------------
# QA verdict parsing
# Returns: "pass", "fail", or "unknown"
# Precedence (case-insensitive):
#   1. VERDICT: APPROVED or APPROVED-WITH-MINOR-FIXES WITH an ARTIFACT marker → pass
#   2. VERDICT: APPROVED or APPROVED-WITH-MINOR-FIXES WITHOUT an ARTIFACT marker → fail
#      (a bare pass with no artifact is invalid per ADR-001 / WS1 failable-check gate)
#   3. VERDICT: REJECTED → fail
#   4. <promise>COMPLETE</promise> with no REJECTED AND an ARTIFACT marker → implicit pass
#   5. Otherwise → unknown (treated as fail for safety)
#
# ARTIFACT marker format (R3 WS1 / TASK-115, extended TASK-131):
#   ARTIFACT: <type>|<detail>
#   where type ∈ {test-run, file-check, diff-check, adversarial-run}
#   Example: ARTIFACT: test-run|pytest tests/foo.py exit=0 "3 passed"
#   Example: ARTIFACT: adversarial-run|llm FINDINGS: none found exit=0
#
# adversarial-run is OPTIONAL / bonus — emitted by adversarial-pass.sh when a
# second-model CLI is available.  It satisfies the artifact requirement on its
# own but is never a NEW mandatory requirement.  The gate still passes on any
# single recognized artifact type (e.g. test-run alone is sufficient).
#
# ESCAPE HATCH:
#   COPILOT_QA_GATE=off bypasses all gate logic in the caller (subagent-stop.sh).
# ---------------------------------------------------------------------------

# has_artifact_marker: returns 0 (true) if the message contains a valid ARTIFACT line.
has_artifact_marker() {
  local msg="$1"
  # Case-insensitive match for ARTIFACT: <type>|<detail>
  # type must be one of: test-run, file-check, diff-check, adversarial-run
  # adversarial-run added in TASK-131 (availability-gated; optional/bonus type).
  # Adding it here is ADDITIVE — existing types are unchanged; the new type
  # satisfies the artifact requirement but is never a mandatory gate of its own.
  printf '%s' "$msg" | grep -qiE '^[[:space:]]*ARTIFACT:[[:space:]]+(test-run|file-check|diff-check|adversarial-run)\|.+$'
}

parse_qa_verdict() {
  local msg="$1"
  local msg_upper
  msg_upper="$(printf '%s' "$msg" | tr '[:lower:]' '[:upper:]')"

  # Explicit VERDICT tokens (highest precedence)
  if printf '%s' "$msg_upper" | grep -qE 'VERDICT:[[:space:]]*(APPROVED-WITH-MINOR-FIXES|APPROVED)'; then
    # APPROVED verdict is only valid when accompanied by an ARTIFACT marker.
    # A bare "VERDICT: APPROVED" with no artifact is an invalid/insufficient verdict
    # and must NOT unblock the gate (ADR-001 / WS1 principle: verdicts bind to artifacts).
    if has_artifact_marker "$msg"; then
      echo "pass"
    else
      echo "fail"
      log_warn "VERDICT: APPROVED received but NO ARTIFACT marker found — gate NOT unblocked (session: ${SESSION_ID}). QA must include ARTIFACT: test-run|..., ARTIFACT: file-check|..., or ARTIFACT: diff-check|..."
    fi
    return
  fi
  if printf '%s' "$msg_upper" | grep -qE 'VERDICT:[[:space:]]*REJECTED'; then
    echo "fail"
    return
  fi

  # Implicit pass: COMPLETE promise with no REJECTED language, AND an ARTIFACT marker
  if printf '%s' "$msg" | grep -qF '<promise>COMPLETE</promise>'; then
    if ! printf '%s' "$msg_upper" | grep -qE 'REJECTED|VERDICT:[[:space:]]*FAIL'; then
      if has_artifact_marker "$msg"; then
        echo "pass"
      else
        echo "fail"
        log_warn "Implicit pass (<promise>COMPLETE</promise>) but NO ARTIFACT marker — gate NOT unblocked (session: ${SESSION_ID})."
      fi
      return
    fi
  fi

  # Default: unknown → fail (safe default)
  echo "fail"
}

# ---------------------------------------------------------------------------
# compute_qa_verdict_label — DIAGNOSTIC ONLY (guardrail E — TASK-129-followup).
#
# A short human-readable label for HOW a QA message's verdict was
# recognized, stored per-task as part of "last_parse" and surfaced later in
# pretool-check.sh's deny message so a wedged gate explains WHY it isn't
# self-healing instead of repeating the same instruction on every denied
# call (e.g. "last QA verdict: unparseable — no Task: header found").
#
# Deliberately a SEPARATE function rather than a change to parse_qa_verdict()
# itself: parse_qa_verdict() and has_artifact_marker() are preserved
# byte-for-byte per the anti-rubber-stamp contract, and this label is purely
# descriptive — it must never be able to influence pass/fail gating, only
# explain it after the fact. Mirrors parse_qa_verdict()'s own precedence so
# the label stays truthful to what actually happened, without touching the
# protected function.
# ---------------------------------------------------------------------------
compute_qa_verdict_label() {
  local msg="$1" msg_upper
  msg_upper="$(printf '%s' "$msg" | tr '[:lower:]' '[:upper:]')"

  if printf '%s' "$msg_upper" | grep -qE 'VERDICT:[[:space:]]*(APPROVED-WITH-MINOR-FIXES|APPROVED)'; then
    if has_artifact_marker "$msg"; then
      echo "APPROVED"
    else
      echo "APPROVED (no artifact — treated as fail)"
    fi
    return
  fi
  if printf '%s' "$msg_upper" | grep -qE 'VERDICT:[[:space:]]*REJECTED'; then
    echo "REJECTED"
    return
  fi
  if printf '%s' "$msg" | grep -qF '<promise>COMPLETE</promise>'; then
    if ! printf '%s' "$msg_upper" | grep -qE 'REJECTED|VERDICT:[[:space:]]*FAIL'; then
      if has_artifact_marker "$msg"; then
        echo "COMPLETE (implicit pass)"
      else
        echo "COMPLETE (no artifact — treated as fail)"
      fi
      return
    fi
  fi
  echo "unparseable"
}

# ---------------------------------------------------------------------------
# Handle @agent-me completion
# ---------------------------------------------------------------------------
handle_me_completion() {
  # Guard: BLOCKED and CONFUSED are non-completion terminal states.
  # Neither represents a finished implementation that needs QA review:
  #   <promise>BLOCKED</promise> — external/technical blocker; agent cannot proceed
  #   <promise>CONFUSED</promise> — decision fork that requires user input
  # In both cases, skip the QA gate so the signal surfaces to the user.
  if printf '%s' "$LAST_MSG" | grep -qF '<promise>BLOCKED</promise>'; then
    local blocked_task
    blocked_task="$(extract_task_id "$LAST_MSG")"
    log_info "me_completed with BLOCKED promise — skipping QA gate for ${blocked_task:-unknown} (session: ${SESSION_ID})"
    exit 0
  fi
  if printf '%s' "$LAST_MSG" | grep -qF '<promise>CONFUSED</promise>'; then
    local confused_task
    confused_task="$(extract_task_id "$LAST_MSG")"
    log_info "me_completed with CONFUSED promise — skipping QA gate for ${confused_task:-unknown} (session: ${SESSION_ID})"
    exit 0
  fi

  local task_id
  task_id="$(extract_task_id "$LAST_MSG")"

  # GUARDRAIL C (ambiguity fails closed): applied to the arm path too, per
  # TASK-129-followup — "apply the same hardened extraction to BOTH
  # handle_qa_completion() and handle_me_completion()". Two or more distinct
  # header-shaped "Task:" lines means we cannot tell which one is the
  # agent's real completion; arming a gate against a guess is worse than
  # not arming at all (see the fail-safe note below, same direction as an
  # invalid task_id_valid_in_project() result). See extract_task_id()'s
  # "WHY A STDOUT SENTINEL" comment for why this is an "AMBIGUOUS:" prefix
  # check on the return value, not a global flag.
  if [[ "$task_id" == AMBIGUOUS:* ]]; then
    log_warn "agent-me completed with 2+ distinct Task: header-shaped lines (${task_id#AMBIGUOUS:}) — cannot determine which is authoritative, NOT arming QA gate (session: ${SESSION_ID})"
    exit 0
  fi

  if [[ -z "$task_id" ]]; then
    log_warn "agent-me completed but no TASK-N found in last_assistant_message (session: ${SESSION_ID})"
    exit 0
  fi

  if ! task_id_valid_in_project "$task_id"; then
    # FAIL-SAFE DIRECTION: do NOT arm on an ID that doesn't validate.
    #
    # A gate that fails to arm degrades to the pre-hook status quo for this
    # one completion — QA review is still the mandatory *social* contract in
    # every agent's Route-To table, only the mechanical backstop is missing,
    # and that gap is visible (this WARN) and recoverable by a human or a
    # later pass.
    #
    # A gate that arms on a bad ID is NOT self-healing: it denies every
    # Bash/Agent tool call in the session except Agent(qa) and a short tc
    # allowlist, and its only exit is 3 consecutive QA failure cycles
    # against a task QA can never find in this project's database (RC-2
    # burned exactly one such cycle before this fix landed). Under-enforcing
    # once is far cheaper than a session-wide false block, so validation
    # failure fails OPEN on the gate (skip arming), never closed.
    log_warn "agent-me completed with ${task_id} but it does not resolve in this project's tc database (cross-project or stale ID) — NOT arming QA gate (session: ${SESSION_ID})"
    exit 0
  fi

  # CHANGE 2 (TASK-129-followup, structural cross-check on the arm path):
  # existence alone is no longer sufficient — see task_status_arm_eligible()
  # for the full rationale, the corroboration source chosen, and an honest
  # comparison against guardrail B's strength. Deliberately a SEPARATE call
  # (not folded into task_id_valid_in_project() above) so the two failure
  # modes — "doesn't exist anywhere in this project" vs. "exists here but
  # its own status says this work is already over/abandoned" — stay
  # distinguishable in the log rather than collapsing into one message.
  if ! task_status_arm_eligible "$task_id"; then
    log_warn "agent-me completed with ${task_id} but its status in this project's tc database is terminal (completed/cancelled) or unreadable — a finished/abandoned task is not something @agent-me just completed; refusing to arm QA gate without stronger corroboration (session: ${SESSION_ID}). See task_status_arm_eligible() for why this check exists and its honest limits."
    exit 0
  fi

  acquire_lock
  trap 'release_lock' EXIT

  local state session_entry now
  now="$(now_iso)"
  state="$(read_gate_state)"
  session_entry="$(get_session "$state")"

  # Add task to pending_tasks (if not already present). Also stamp
  # armed_at[task_id] with the arming time (guardrail D write-side) — but
  # ONLY the first time this task enters pending_tasks in this cycle. If
  # armed_at[$tid] is already set (task re-completed by @agent-me while
  # still pending, e.g. after a QA REJECTED sent it back), the ORIGINAL
  # arming time is what staleness should measure from — bumping it forward
  # on every me-completion would let a genuinely stuck task keep resetting
  # its own age and never go advisory.
  local updated_entry
  updated_entry="$(printf '%s' "$session_entry" | "$JQ" \
    --arg tid "$task_id" \
    --arg now "$now" \
    --arg event "me_completed" '
    .pending_tasks = (
      if (.pending_tasks | map(. == $tid) | any) then .pending_tasks
      else .pending_tasks + [$tid]
      end
    ) |
    .armed_at = ((.armed_at // {}) as $a | $a + (if ($a[$tid] // null) == null then {($tid): $now} else {} end)) |
    .history = .history + [{"taskId": $tid, "event": $event, "ts": $now}] |
    .lastSeen = $now
  ' 2>/dev/null)"

  if [[ -z "$updated_entry" ]]; then
    log_warn "Failed to update session entry for me_completed (task: ${task_id})"
    release_lock
    trap - EXIT
    exit 0
  fi

  local merged pruned
  merged="$(printf '%s' "$state" | "$JQ" \
    --arg sid "$SESSION_ID" \
    --argjson entry "$updated_entry" \
    '.[$sid] = $entry' 2>/dev/null || echo "$state")"
  pruned="$(prune_stale "$merged")"
  write_gate_state "$pruned"

  log_info "me_completed: added ${task_id} to pending_tasks (session: ${SESSION_ID})"

  release_lock
  trap - EXIT
}

# ---------------------------------------------------------------------------
# Handle @agent-qa completion
# ---------------------------------------------------------------------------
handle_qa_completion() {
  local task_id verdict all_task_ids header_note
  task_id="$(extract_task_id "$LAST_MSG")"
  header_note=""

  # GUARDRAIL C (ambiguity fails closed — TASK-129-followup): 2+ distinct
  # header-shaped "Task:" lines means we cannot tell which one is
  # authoritative. Guessing risks silently clearing or penalizing the WRONG
  # task's gate, which is a worse outcome than doing nothing this cycle —
  # so this exits BEFORE the lock is acquired and BEFORE any state is
  # touched, identical in spirit to the existing "no header found" no-op
  # below, just for the opposite (too many, not too few) failure shape. See
  # extract_task_id()'s "WHY A STDOUT SENTINEL" comment for why this is an
  # "AMBIGUOUS:" prefix check on the return value, not a global flag.
  if [[ "$task_id" == AMBIGUOUS:* ]]; then
    log_warn "agent-qa completed with 2+ distinct Task: header-shaped lines (${task_id#AMBIGUOUS:}) — cannot determine which is authoritative, refusing to act (session: ${SESSION_ID})"
    exit 0
  fi

  verdict="$(parse_qa_verdict "$LAST_MSG")"

  all_task_ids="$(extract_all_task_ids "$LAST_MSG")"

  acquire_lock
  trap 'release_lock' EXIT

  local state session_entry now
  now="$(now_iso)"
  state="$(read_gate_state)"
  session_entry="$(get_session "$state")"

  # GUARDRAIL B (cross-check against pending — TASK-129-followup, the
  # highest-value guardrail here): extraction (guardrail A) narrows WHERE a
  # candidate id can come from, but a well-formed, genuinely-authored header
  # can still name a task that isn't the one THIS session's gate is armed
  # for (stale copy-paste, cross-session bleed, or simply QA reviewing the
  # wrong thing). Anchoring extraction alone cannot rule that out — it is
  # a property of the LINE, not of the SESSION's actual armed state.
  #
  # So: after extraction, verify the id is actually in pending_tasks for
  # THIS session before trusting it to identify which task to mutate. If it
  # is NOT pending, refuse to act on it — clearing or penalizing a task the
  # gate was never armed for is the exact false-positive shape RC-2 and the
  # blockquote defect both share. This makes the parser stop being
  # load-bearing: even a PERFECT false match (a real task id, cleanly
  # authored, just the wrong one) cannot clear or penalize a gate that was
  # never armed for that task, because this check no longer trusts
  # "parsed cleanly" as a stand-in for "is relevant".
  #
  # Clearing task_id here (rather than exiting) deliberately falls through
  # to the existing single-pending-attribution logic just below: if exactly
  # one task is pending, attribution to it isn't a guess — QA cannot have
  # been reviewing anything else — so treating "parsed but not pending" the
  # same as "didn't parse at all" for that fallback is correct, not a
  # loosening.
  if [[ -n "$task_id" ]]; then
    local is_pending
    is_pending="$(printf '%s' "$session_entry" | "$JQ" -r --arg tid "$task_id" \
      '(.pending_tasks // []) | map(. == $tid) | any' 2>/dev/null)" || is_pending="false"
    if [[ "$is_pending" != "true" ]]; then
      local pending_list_str
      pending_list_str="$(printf '%s' "$session_entry" | "$JQ" -r '(.pending_tasks // []) | join(", ")' 2>/dev/null)" || pending_list_str=""
      log_warn "agent-qa completed; parsed header task ${task_id} is NOT in pending_tasks for this session (pending: [${pending_list_str}]) — refusing to clear/penalize it (session: ${SESSION_ID}); falling back to single-pending attribution if unambiguous"
      header_note="cross-check failed: header parsed ${task_id}, not pending for this session"
      task_id=""
    fi
  fi

  # On a pass verdict, we can proceed even without a task_id — QA's approval
  # unblocks ALL pending tasks for the session (a passing QA run clears the gate).
  # On a fail verdict, we need a task_id to track retries.
  #
  # SINGLE-PENDING ATTRIBUTION (defect fix — the gate-wedge this closes): the
  # old code just did `exit 0` right here on an unparseable failing verdict,
  # BEFORE ever reaching the retry-counting logic below. That wasn't a
  # one-off miss, it was permanent for that session: QA's own markdown habits
  # (the same decoration extract_task_id() now tolerates, above) trip this
  # exact path on every failing run, so MAX_RETRIES could never be reached
  # and the 3-strikes auto-unblock never fired. Evidence: TASK-129 in this
  # project's log accumulated seven identical WARNs here while `retries`
  # stayed `{}` — the gate stayed armed indefinitely with no way out but the
  # COPILOT_QA_GATE=off escape hatch.
  #
  # Fix: when the header can't be parsed, check how many tasks are pending
  # for THIS session. Exactly one pending task is the one case where
  # attribution isn't a guess — QA cannot have been reviewing anything else,
  # because nothing else is outstanding. Zero pending means there's nothing
  # to charge the failure to; two or more pending means picking one would be
  # fabricating certainty the message doesn't contain — both of those keep
  # the original no-op (still logged) rather than risk crediting the wrong
  # task's retry counter.
  if [[ -z "$task_id" && "$verdict" != "pass" ]]; then
    local pending_count
    pending_count="$(printf '%s' "$session_entry" | "$JQ" '.pending_tasks | length' 2>/dev/null)" || pending_count=0
    [[ "$pending_count" =~ ^[0-9]+$ ]] || pending_count=0

    if [[ "$pending_count" -eq 1 ]]; then
      task_id="$(printf '%s' "$session_entry" | "$JQ" -r '.pending_tasks[0] // empty' 2>/dev/null)" || task_id=""
      [[ -z "$header_note" ]] && header_note="unparseable — no Task: header found"
    fi

    if [[ -n "$task_id" ]]; then
      log_warn "agent-qa completed but no TASK-N found in last_assistant_message (session: ${SESSION_ID}, verdict: ${verdict}) — attributed to sole pending task ${task_id} for retry counting"
    else
      log_warn "agent-qa completed but no TASK-N found in last_assistant_message (session: ${SESSION_ID}, verdict: ${verdict}) — ${pending_count} task(s) pending, cannot attribute unambiguously, no-op"
      release_lock
      trap - EXIT
      exit 0
    fi
  fi

  # GUARDRAIL E write-side (last_parse note): header_note may already be set
  # by guardrail B (cross-check failed) or the single-pending fallback above
  # (no header at all); if task_id came through extraction cleanly and
  # pending, neither branch ran, so default it here. Combined with
  # compute_qa_verdict_label(), this becomes the one-line "last QA verdict"
  # string pretool-check.sh's deny message surfaces (guardrail E) — stored
  # per-task below wherever retries/pending state actually changes for it.
  if [[ -z "$header_note" ]]; then
    if [[ -n "$task_id" ]]; then
      header_note="header parsed: ${task_id}"
    else
      header_note="unparseable — no Task: header found"
    fi
  fi
  local last_parse_note
  last_parse_note="$(compute_qa_verdict_label "$LAST_MSG")$( printf ' — %s' "$header_note" )"

  local updated_entry advisory_msg=""

  if [[ "$verdict" == "pass" ]]; then
    # Strategy: clear all pending_tasks that appear in the QA message OR (when
    # the message references a different set of tasks) clear ALL pending tasks.
    # Rationale: a passing QA verdict means the work round-trip is complete.
    # The common failure mode is QA mentioning an old/different TASK-N while a
    # *different* task sits in pending_tasks — the pass should still unblock.
    #
    # Algorithm:
    #   1. Find the intersection of pending_tasks with all IDs mentioned in msg.
    #   2. If the intersection is non-empty → clear only those (targeted).
    #   3. If the intersection is empty (QA mentioned unrelated IDs) → clear ALL
    #      pending tasks (QA has approved work for this session).
    local pending_json
    pending_json="$(printf '%s' "$session_entry" | "$JQ" '.pending_tasks // []' 2>/dev/null || echo '[]')"
    local intersection_count
    intersection_count="$(printf '%s' "$pending_json" | "$JQ" \
      --argjson mentioned "$all_task_ids" \
      '[.[] | select(. as $t | $mentioned | map(. == $t) | any)] | length' 2>/dev/null || echo 0)"

    if [[ "$intersection_count" -gt 0 ]]; then
      # Targeted clear: remove only the tasks QA mentioned
      local history_entries
      history_entries="$(printf '%s' "$all_task_ids" | "$JQ" \
        --arg now "$now" \
        --arg event "qa_passed" \
        '[.[] | {"taskId": ., "event": $event, "ts": $now}]' 2>/dev/null || echo '[]')"
      # .armed_at and .last_parse are cleaned up alongside .retries for every
      # cleared id — required for guardrail D correctness, not just tidiness:
      # armed_at[tid] is only ever SET the first time a task enters
      # pending_tasks (see handle_me_completion), so if it isn't deleted here
      # a task cleared then later re-armed would inherit its OLD arm
      # timestamp and read as already-stale the instant it re-arms.
      updated_entry="$(printf '%s' "$session_entry" | "$JQ" \
        --argjson mentioned "$all_task_ids" \
        --argjson hist "$history_entries" \
        --arg now "$now" '
        .pending_tasks = (.pending_tasks | map(select(. as $t | $mentioned | map(. == $t) | any | not))) |
        .retries = (reduce $mentioned[] as $tid (.retries; del(.[$tid]))) |
        .armed_at = (reduce $mentioned[] as $tid ((.armed_at // {}); del(.[$tid]))) |
        .last_parse = (reduce $mentioned[] as $tid ((.last_parse // {}); del(.[$tid]))) |
        .history = .history + $hist |
        .lastSeen = $now
      ' 2>/dev/null)"
      log_info "qa_passed (targeted): cleared tasks ${all_task_ids} from pending_tasks (session: ${SESSION_ID})"
    else
      # Full clear: QA passed but mentioned different task IDs — unblock entire session
      local pending_arr
      pending_arr="$(printf '%s' "$pending_json" | "$JQ" -c '.' 2>/dev/null || echo '[]')"
      local history_entries
      history_entries="$(printf '%s' "$pending_json" | "$JQ" \
        --arg now "$now" \
        --arg event "qa_passed_full_clear" \
        '[.[] | {"taskId": ., "event": $event, "ts": $now}]' 2>/dev/null || echo '[]')"
      updated_entry="$(printf '%s' "$session_entry" | "$JQ" \
        --argjson hist "$history_entries" \
        --arg now "$now" '
        .pending_tasks = [] |
        .retries = {} |
        .armed_at = {} |
        .last_parse = {} |
        .history = .history + $hist |
        .lastSeen = $now
      ' 2>/dev/null)"
      log_info "qa_passed (full clear): cleared all pending tasks ${pending_arr} because QA approved for session ${SESSION_ID} (mentioned: ${all_task_ids})"
    fi
  else
    # Fail path: track retries by task_id
    local current_retries
    current_retries="$(printf '%s' "$session_entry" | "$JQ" -r --arg tid "$task_id" \
      '.retries[$tid] // 0' 2>/dev/null || echo 0)"
    local new_retries=$(( current_retries + 1 ))

    if [[ "$new_retries" -ge "$MAX_RETRIES" ]]; then
      # Auto-unblock: remove from pending_tasks after 3 failures
      local event="qa_failed_advisory_unblock"
      # armed_at[$tid] is deleted here too (same reasoning as the pass-path
      # cleanup above): the task is leaving pending_tasks, so its arm cycle
      # is over. last_parse[$tid] is intentionally KEPT (not deleted) even
      # though the task is unblocked — it's the last diagnostic breadcrumb
      # for why this task needed 3 strikes, and nothing currently reads
      # last_parse for a task that isn't pending, so leaving it is harmless
      # and potentially useful for a human reviewing qa-gate.json by hand.
      updated_entry="$(printf '%s' "$session_entry" | "$JQ" \
        --arg tid "$task_id" \
        --arg now "$now" \
        --arg event "$event" \
        --arg note "$last_parse_note" \
        --argjson retries "$new_retries" '
        .pending_tasks = (.pending_tasks | map(select(. != $tid))) |
        .retries[$tid] = $retries |
        .armed_at = ((.armed_at // {}) | del(.[$tid])) |
        .last_parse = ((.last_parse // {}) + {($tid): $note}) |
        .history = .history + [{"taskId": $tid, "event": $event, "ts": $now}] |
        .lastSeen = $now
      ' 2>/dev/null)"
      advisory_msg="QA gate degraded to advisory: ${task_id} failed QA ${new_retries} consecutive times. Main session is unblocked, but human review is strongly recommended — the code has not passed automated verification."
      log_warn "qa_failed_advisory_unblock: ${task_id} failed ${new_retries}x, auto-unblocking (session: ${SESSION_ID})"
    else
      local event="qa_failed_retry_${new_retries}"
      # last_parse[$tid] write is guardrail E's write side: whatever this
      # deny message needs later (retries + last-parse reason) has to be
      # persisted HERE, at mutation time, because pretool-check.sh's deny
      # path (the read side) has no access to $LAST_MSG — it only ever sees
      # qa-gate.json.
      updated_entry="$(printf '%s' "$session_entry" | "$JQ" \
        --arg tid "$task_id" \
        --arg now "$now" \
        --arg event "$event" \
        --arg note "$last_parse_note" \
        --argjson retries "$new_retries" '
        .retries[$tid] = $retries |
        .last_parse = ((.last_parse // {}) + {($tid): $note}) |
        .history = .history + [{"taskId": $tid, "event": $event, "ts": $now}] |
        .lastSeen = $now
      ' 2>/dev/null)"
      log_info "qa_failed: ${task_id} retry ${new_retries}/${MAX_RETRIES} (session: ${SESSION_ID})"
    fi
  fi

  if [[ -z "$updated_entry" ]]; then
    log_warn "Failed to compute updated entry for qa completion (task: ${task_id:-unknown})"
    release_lock
    trap - EXIT
    exit 0
  fi

  local merged pruned
  merged="$(printf '%s' "$state" | "$JQ" \
    --arg sid "$SESSION_ID" \
    --argjson entry "$updated_entry" \
    '.[$sid] = $entry' 2>/dev/null || echo "$state")"
  pruned="$(prune_stale "$merged")"
  write_gate_state "$pruned"

  release_lock
  trap - EXIT

  # Emit advisory if needed (after lock released)
  if [[ -n "$advisory_msg" ]]; then
    printf '{"systemMessage":"%s"}\n' \
      "$(printf '%s' "$advisory_msg" | sed 's/"/\\"/g')"
  fi
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
case "$AGENT_TYPE" in
  me)  handle_me_completion ;;
  qa)  handle_qa_completion ;;
esac

exit 0
