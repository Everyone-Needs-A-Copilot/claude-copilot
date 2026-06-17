#!/usr/bin/env bash
# session-start.sh — SessionStart hook for Claude Copilot
#
# PURPOSE:
#   Emits the session protocol guardrails (from protocol-injection.md)
#   PLUS a compact "Known references" block sourced from:
#     1. cc config values (paths.shared_docs, paths.knowledge_repo, plus
#        any refs.* keys stored via `cc config set refs.<name> <value>`)
#     2. reference-type cc memory entries (FTS5 keyword search for "reference")
#
# OUTPUT:
#   JSON with a "systemMessage" field containing the full injection text.
#   Claude Code's SessionStart hook reads this and prepends it to session context.
#
#   If no references are configured and no memory entries exist, the Known
#   References block is omitted entirely (graceful no-op).
#
# REGISTERING A REFERENCE:
#   cc config set refs.shared_docs /path/to/docs
#   cc config set refs.cli_copilot /path/to/cli-copilot
#   cc memory store --type reference "CLI Copilot location: /path/to/cli-copilot"
#
# ESCAPE HATCH:
#   COPILOT_SESSION_START=off  — skip this hook entirely

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INJECTION_FILE="${SCRIPT_DIR}/protocol-injection.md"
MANIFEST_FILE="${SCRIPT_DIR}/../agents/manifest.json"

# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------
if [[ "${COPILOT_SESSION_START:-}" == "off" ]]; then
  exit 0
fi

# ---------------------------------------------------------------------------
# Read the static guardrails content
# ---------------------------------------------------------------------------
if [[ ! -f "$INJECTION_FILE" ]]; then
  # No injection file — exit cleanly (hook is optional)
  exit 0
fi

GUARDRAILS="$(cat "$INJECTION_FILE")"

# ---------------------------------------------------------------------------
# Generate the framework-agent roster from manifest.json (TASK-114 / ADR-002)
# Replaces the hardcoded agent list in Rule 1 with the live manifest roster
# so the banner can never go stale.  Falls back to the static file text when
# manifest is absent or python3 is unavailable (safe degradation).
# Output format is byte-compatible: the systemMessage JSON envelope is
# unchanged; only the inner text line is regenerated.
# ---------------------------------------------------------------------------
if [[ -f "$MANIFEST_FILE" ]] && command -v python3 &>/dev/null; then
  # Resolve the manifest path to an absolute path for passing to python3
  MANIFEST_ABS="$(cd "$(dirname "$MANIFEST_FILE")" && pwd)/$(basename "$MANIFEST_FILE")"
  # Use a temp file to pass guardrails text to python3 (avoids stdin/heredoc conflicts)
  _GUARDRAILS_TMP="$(mktemp /tmp/copilot-guardrails-XXXXXX.txt)"
  printf '%s' "$GUARDRAILS" > "$_GUARDRAILS_TMP"
  GUARDRAILS_UPDATED="$(python3 - "$MANIFEST_ABS" "$_GUARDRAILS_TMP" <<'PYEOF'
import json, sys, re

manifest_path = sys.argv[1]
guardrails_path = sys.argv[2]

with open(guardrails_path) as f:
    guardrails = f.read()

try:
    with open(manifest_path) as f:
        data = json.load(f)
    # Only framework agents (not setup-only kc)
    framework = sorted(
        name for name, desc in data["agents"].items()
        if desc.get("role") == "framework"
    )
    # Format as backtick-quoted @agent-X list
    agent_list = ", ".join(f"`@agent-{a}`" for a in framework)
    roster_line = f"- Framework agents: {agent_list}"
    # Replace the "- Framework agents: ..." line (greedy to end of line)
    updated = re.sub(r'- Framework agents:.*', roster_line, guardrails, count=1)
    print(updated, end="")
except Exception:
    # Fall back silently — print guardrails unchanged
    print(guardrails, end="")
PYEOF
  )" || GUARDRAILS_UPDATED=""
  rm -f "$_GUARDRAILS_TMP"

  if [[ -n "$GUARDRAILS_UPDATED" ]]; then
    GUARDRAILS="$GUARDRAILS_UPDATED"
  fi
fi

# ---------------------------------------------------------------------------
# Build "Known references" block from cc config + cc memory
# ---------------------------------------------------------------------------

REFS_BLOCK=""

# Helper: escape a string for JSON embedding (basic: escape backslash, double-quote, newline)
json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr '\n' ' '
}

# -- 1. cc config: standard path keys (shared_docs, knowledge_repo) ----------
if command -v cc &>/dev/null; then
  SHARED_DOCS="$(cc config get paths.shared_docs --raw 2>/dev/null || true)"
  KNOWLEDGE_REPO="$(cc config get paths.knowledge_repo --raw 2>/dev/null || true)"

  if [[ -n "$SHARED_DOCS" ]] || [[ -n "$KNOWLEDGE_REPO" ]]; then
    REFS_BLOCK="${REFS_BLOCK}"$'\n'"## Known References"$'\n'
    [[ -n "$SHARED_DOCS" ]]    && REFS_BLOCK="${REFS_BLOCK}- **shared_docs:** ${SHARED_DOCS}"$'\n'
    [[ -n "$KNOWLEDGE_REPO" ]] && REFS_BLOCK="${REFS_BLOCK}- **knowledge_repo:** ${KNOWLEDGE_REPO}"$'\n'
  fi

  # -- 2. cc config: arbitrary refs.* keys ------------------------------------
  # List all config keys, filter refs.*, output as key=value lines
  while IFS='=' read -r key value; do
    key="${key// /}"
    value="${value// /}"
    if [[ "$key" == refs.* ]] && [[ -n "$value" ]]; then
      ref_name="${key#refs.}"
      # Start block if not started yet
      if [[ -z "$REFS_BLOCK" ]]; then
        REFS_BLOCK="${REFS_BLOCK}"$'\n'"## Known References"$'\n'
      fi
      REFS_BLOCK="${REFS_BLOCK}- **${ref_name}:** ${value}"$'\n'
    fi
  done < <(cc config export 2>/dev/null || true)

  # -- 3. cc memory: reference-type entries -----------------------------------
  REF_MEMORIES="$(cc memory list --type reference --json 2>/dev/null || true)"
  if [[ -n "$REF_MEMORIES" ]] && [[ "$REF_MEMORIES" != "[]" ]] && [[ "$REF_MEMORIES" != "null" ]]; then
    # Check if jq is available for parsing; fallback to showing count
    if command -v jq &>/dev/null; then
      # Extract content snippets from reference entries (max 5, 120 chars each)
      ENTRY_LINES="$(printf '%s' "$REF_MEMORIES" | jq -r '.[0:5] | .[] | .content // .content' 2>/dev/null | head -5 | sed 's/^/  /')"
      if [[ -n "$ENTRY_LINES" ]]; then
        if [[ -z "$REFS_BLOCK" ]]; then
          REFS_BLOCK="${REFS_BLOCK}"$'\n'"## Known References"$'\n'
        fi
        REFS_BLOCK="${REFS_BLOCK}Memory references (FTS5 keyword-searchable via \`cc memory search\`):"$'\n'
        REFS_BLOCK="${REFS_BLOCK}${ENTRY_LINES}"$'\n'
      fi
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Compose final message
# ---------------------------------------------------------------------------
if [[ -n "$REFS_BLOCK" ]]; then
  FULL_TEXT="${GUARDRAILS}"$'\n\n'"---"$'\n'"${REFS_BLOCK}"$'\n'"*To register a reference: \`cc config set refs.<name> <value>\` or \`cc memory store --type reference \"<content>\"\`*"
else
  FULL_TEXT="${GUARDRAILS}"
fi

# ---------------------------------------------------------------------------
# Emit JSON systemMessage
# ---------------------------------------------------------------------------
# Use python for safe JSON encoding (always available alongside cc)
if command -v python3 &>/dev/null; then
  python3 -c "
import json, sys
text = sys.stdin.read()
print(json.dumps({'systemMessage': text}))
" <<< "$FULL_TEXT"
elif command -v python &>/dev/null; then
  python -c "
import json, sys
text = sys.stdin.read()
print(json.dumps({'systemMessage': text}))
" <<< "$FULL_TEXT"
else
  # Fallback: manual JSON escape (handles common cases)
  ESCAPED="$(json_escape "$FULL_TEXT")"
  printf '{"systemMessage":"%s"}\n' "$ESCAPED"
fi

exit 0
