#!/bin/bash
# Codex PreToolUse hook: the main session is a coordinator (2026-11-05).
# Denies main-thread file edits and non-allowlisted shell. Spawned agents are never
# blocked: thread kind is read from the first line of the session transcript
# (thread_source / source.subagent). Fails OPEN on any parse error or when the
# thread kind cannot be determined. Escape hatch: COPILOT_COORDINATOR=off (logged).

JQ="$(command -v jq 2>/dev/null || true)"
[ -n "$JQ" ] || exit 0
PAYLOAD="$(cat 2>/dev/null)"
[ -n "$PAYLOAD" ] || exit 0

TOOL="$($JQ -r '.tool_name // empty' <<< "$PAYLOAD" 2>/dev/null)"
case "$TOOL" in
  Bash|apply_patch|Edit|Write|MultiEdit) ;;
  *) exit 0 ;;
esac

LOG_DIR="${COPILOT_COORDINATOR_LOG_DIR:-$HOME/.codex/log}"
if [ "${COPILOT_COORDINATOR:-}" = "off" ]; then
  mkdir -p "$LOG_DIR" 2>/dev/null
  printf '%s coordinator-bypass tool=%s session=%s\n' "$(date -u +%FT%TZ)" "$TOOL" \
    "$($JQ -r '.session_id // "unknown"' <<< "$PAYLOAD" 2>/dev/null)" >> "$LOG_DIR/coordinator-bypass.log" 2>/dev/null
  exit 0
fi

# Main thread only: spawned agents (thread_source=subagent) are never blocked.
TP="$($JQ -r '.transcript_path // empty' <<< "$PAYLOAD" 2>/dev/null)"
[ -n "$TP" ] && [ -r "$TP" ] || exit 0
KIND="$(head -n 1 "$TP" 2>/dev/null | $JQ -r '.payload | if .thread_source == "user" then "main" elif (.thread_source == "subagent" or ((.source|type) == "object" and (.source|has("subagent")))) then "sub" else "unknown" end' 2>/dev/null)"
[ "$KIND" = "main" ] || exit 0

deny() {
  $JQ -cn --arg r "Coordinator rule (2026-11-05): the main session does not $1. Dispatch an agent with spawn_agent. Allowed here: tc; cc status/list/progress/skill; pwd, date, readlink <path>; git status (-s -b --porcelain), git log (--oneline -n N --format= --graph --decorate --all --since= --until= --author= --stat --name-only --name-status --first-parent --no-merges, refs/ranges, -- paths), git branch (-a -r -v -vv --list --show-current), git worktree list [--porcelain], git rev-parse (--abbrev-ref --short --show-toplevel --git-dir --is-inside-work-tree, refs); notes under ~/.codex/memories. Override: COPILOT_COORDINATOR=off (logged)." \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

NOTE_DIRS="$HOME/.codex/memories/:$HOME/.codex/scratchpad/:${COPILOT_COORDINATOR_NOTES:-}"

path_ok() {
  local p="$1" d
  case "$p" in *..*) return 1 ;; esac
  case "$p" in "~/"*) p="$HOME/${p#\~/}" ;; esac
  IFS=: read -ra DIRS <<< "$NOTE_DIRS"
  for d in "${DIRS[@]}"; do
    [ -n "$d" ] || continue
    case "$d" in */) ;; *) d="$d/" ;; esac
    case "$p" in "$d"*) return 0 ;; esac
  done
  return 1
}

if [ "$TOOL" != "Bash" ]; then
  PATHS="$($JQ -r '[.tool_input | (.. | strings)] | join("\n")' <<< "$PAYLOAD" 2>/dev/null \
    | sed -nE 's/^\*\*\* (Add|Update|Delete) File: (.*)$/\2/p; s/^\*\*\* Move to: (.*)$/\1/p')"
  FP="$($JQ -r '.tool_input.file_path // .tool_input.path // empty' <<< "$PAYLOAD" 2>/dev/null)"
  [ -n "$FP" ] && PATHS="$PATHS"$'\n'"$FP"
  PATHS="$(printf '%s' "$PATHS" | sed '/^$/d')"
  [ -n "$PATHS" ] || deny "edit files"
  while IFS= read -r p; do path_ok "$p" || deny "edit project files ($p)"; done <<< "$PATHS"
  exit 0
fi

CMD="$($JQ -r '.tool_input.command // empty' <<< "$PAYLOAD" 2>/dev/null)"
[ -n "$CMD" ] || exit 0
# Unwrap a plain `bash -lc '...'`/`zsh -lc` wrapper if present.
if [[ "$CMD" =~ ^(/bin/)?(ba|z)?sh\ +-l?c\ +[\'\"](.*)[\'\"]$ ]]; then CMD="${BASH_REMATCH[3]}"; fi

case "$CMD" in *'`'*|*'$('*|*'>'*|*'<'*|*$'\n'*) deny "run shell with substitution, redirection or multiple lines" ;; esac

# Split a segment into tokens in W, removing matched surrounding quotes. Fails (1) on
# unterminated quotes, backslashes, `$`, or any quote left inside a token.
tokenize() {
  W=(); local s="$1" tok="" has=0 q="" c i
  for ((i=0; i<${#s}; i++)); do
    c="${s:i:1}"
    if [ -n "$q" ]; then
      if [ "$c" = "$q" ]; then q=""; else tok+="$c"; fi
    else
      case "$c" in
        "'"|'"') q="$c"; has=1 ;;
        ' '|$'\t') if [ "$has" = 1 ]; then W+=("$tok"); tok=""; has=0; fi ;;
        *) tok+="$c"; has=1 ;;
      esac
    fi
  done
  [ -z "$q" ] || return 1
  [ "$has" = 0 ] || W+=("$tok")
  local t
  for t in "${W[@]}"; do
    case "$t" in *\\*|*\$*|*"'"*|*'"'*) return 1 ;; esac
  done
  return 0
}

REV_RE='^[A-Za-z0-9._/@^~:-]+$'
is_rev() { [[ "$1" != -* && "$1" =~ $REV_RE ]]; }

# Allowlisted git arguments only (after quote removal); anything unlisted is denied.
git_args_ok() {
  local sub="$1"; shift
  local a n=0 dashdash=0
  case "$sub" in
    status)
      for a in "$@"; do
        case "$a" in -s|--short|-b|--branch|--porcelain|--porcelain=v1|--porcelain=v2) ;; *) return 1 ;; esac
      done ;;
    log)
      while [ $# -gt 0 ]; do
        a="$1"; shift
        if [ "$dashdash" = 1 ]; then continue; fi
        case "$a" in
          --) dashdash=1 ;;
          --oneline|--graph|--decorate|--all|--stat|--name-only|--name-status|--first-parent|--no-merges) ;;
          -n) [[ "${1:-}" =~ ^[0-9]+$ ]] || return 1; shift ;;
          -[0-9]*) [[ "$a" =~ ^-[0-9]+$ ]] || return 1 ;;
          --max-count=*) [[ "${a#*=}" =~ ^[0-9]+$ ]] || return 1 ;;
          --format=*|--pretty=*|--since=*|--until=*|--author=*) ;;
          -*) return 1 ;;
          *) if [[ "$a" == *..* ]]; then [[ "$a" =~ $REV_RE ]] || return 1; else is_rev "$a" || return 1; fi ;;
        esac
      done ;;
    branch)
      local listing=0
      for a in "$@"; do [ "$a" = "--list" ] && listing=1; done
      for a in "$@"; do
        case "$a" in
          -a|-r|-v|-vv|--list|--show-current) ;;
          -*) return 1 ;;
          *) [ "$listing" = 1 ] || return 1 ;;
        esac
      done ;;
    worktree)
      [ "${1:-}" = "list" ] || return 1
      [ $# -le 2 ] || return 1
      [ $# -lt 2 ] || [ "$2" = "--porcelain" ] || return 1 ;;
    rev-parse)
      for a in "$@"; do
        case "$a" in
          --abbrev-ref|--short|--short=[0-9]*|--show-toplevel|--git-dir|--is-inside-work-tree) ;;
          -*) return 1 ;;
          *) is_rev "$a" || return 1 ;;
        esac
      done ;;
    *) return 1 ;;
  esac
  return 0
}

seg_ok() {
  tokenize "$1" || return 1
  [ ${#W[@]} -gt 0 ] || return 0
  local bin="${W[0]##*/}" a
  case "$bin" in
    tc) return 0 ;;
    cc) case "${W[1]:-}" in status|list|progress|skill) return 0 ;; esac; return 1 ;;
    pwd) for a in "${W[@]:1}"; do [ "$a" = "-P" ] || [ "$a" = "-L" ] || return 1; done; return 0 ;;
    date) for a in "${W[@]:1}"; do [ "$a" = "-u" ] || [[ "$a" == +* ]] || return 1; done; return 0 ;;
    readlink) [ ${#W[@]} -eq 2 ] && [[ "${W[1]}" != -* ]] && return 0; return 1 ;;
    git)
      local i=1
      while [ "${W[$i]:-}" = "-C" ]; do [ -n "${W[$((i+1))]:-}" ] || return 1; i=$((i+2)); done
      [ -n "${W[$i]:-}" ] || return 1
      git_args_ok "${W[@]:$i}"; return $? ;;
    head|tail|wc) [ "$SEG_IDX" -gt 0 ] && return 0; return 1 ;;
  esac
  return 1
}

# Split on every control operator: && || ; & | (newlines are rejected above) (each segment must be allowlisted; head/tail/wc only as pipe sinks).
SEG_IDX=0
while IFS= read -r seg; do
  seg="${seg#"${seg%%[![:space:]]*}"}"
  seg_ok "$seg" || deny "run work commands (${seg%% *})"
  SEG_IDX=$((SEG_IDX+1))
done < <(printf '%s\n' "$CMD" | sed -E 's/&&|\|\||[;&|]/\n/g')
exit 0
