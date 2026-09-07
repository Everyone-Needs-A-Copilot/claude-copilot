#!/usr/bin/env bash
# test-optional-context-surfaces.sh — drift detector for the Optional
# Context instruction block (work package C, task C1/C4).
#
# The canonical source is .claude/agents/_shared/optional-context.md.
# It must be embedded BYTE-IDENTICAL (not merely similar) into every
# delivery surface named by task C1:
#   - .claude/agents/ta.md
#   - .claude/agents/me.md
#   - .claude/agents/qa.md
#   - .claude/commands/protocol.md
#   - templates/CLAUDE.template.md
#   - plugins/codex-copilot/skills/specialist-agents/references/shared-behaviors.md
#
# Root CLAUDE.md is deliberately NOT in this list (per C1's own scope: it
# ships nowhere and only needs prose consistency, not byte identity).
#
# NEW FILE ONLY. Does not modify any existing test.
#
# Run: bash tests/instructions/test-optional-context-surfaces.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
cd "$PROJECT_ROOT" || exit 1

PASS=0
FAIL=0

ok() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

SOURCE_FILE=".claude/agents/_shared/optional-context.md"

# Files required to carry a byte-identical embed of the canonical block.
EMBED_SURFACES=(
  ".claude/agents/ta.md"
  ".claude/agents/me.md"
  ".claude/agents/qa.md"
  ".claude/commands/protocol.md"
  "templates/CLAUDE.template.md"
  "plugins/codex-copilot/skills/specialist-agents/references/shared-behaviors.md"
)

# Extracts the '## Optional Context' block (heading through the final
# "Never block." fallback line, inclusive) from a file. Same extraction
# rule used by the implementation's own verification pass, so a change to
# the block's start/end markers has to be made deliberately in both places.
extract_block() {
  local file="$1"
  awk '
    /^## Optional Context$/ { f = 1 }
    f { print }
    f && /unconfigured; optional context limited to project and machine skills\." Never block\./ { exit }
  ' "$file"
}

# ---------------------------------------------------------------------------
# 1. Canonical source file exists and contains exactly one Optional Context
#    block (the drift check is meaningless against a missing or malformed
#    source).
# ---------------------------------------------------------------------------
if [[ ! -f "$SOURCE_FILE" ]]; then
  fail "canonical source $SOURCE_FILE exists"
  echo "FATAL: canonical source missing, cannot proceed" >&2
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
else
  ok "canonical source $SOURCE_FILE exists"
fi

SOURCE_BLOCK="$(extract_block "$SOURCE_FILE")"
SOURCE_HEADING_COUNT="$(grep -c '^## Optional Context$' "$SOURCE_FILE")"

if [[ -z "$SOURCE_BLOCK" ]]; then
  fail "canonical source contains an extractable '## Optional Context' block"
else
  ok "canonical source contains an extractable '## Optional Context' block"
fi

if [[ "$SOURCE_HEADING_COUNT" -eq 1 ]]; then
  ok "canonical source has exactly one '## Optional Context' heading (found $SOURCE_HEADING_COUNT)"
else
  fail "canonical source has exactly one '## Optional Context' heading (found $SOURCE_HEADING_COUNT)"
fi

# The canonical source file, in full, IS the block (whole-file identity is
# the strongest form of "this file is the source of truth" — nothing else
# may share the file).
SOURCE_FULL_BYTES="$(wc -c < "$SOURCE_FILE" | tr -d ' ')"
SOURCE_BLOCK_BYTES="$(printf '%s' "$SOURCE_BLOCK" | wc -c | tr -d ' ')"

# ---------------------------------------------------------------------------
# 2. Every embed surface: block present, and byte-identical to the source
#    block (diff, not eyeball comparison).
# ---------------------------------------------------------------------------
for surface in "${EMBED_SURFACES[@]}"; do
  if [[ ! -f "$surface" ]]; then
    fail "$surface exists"
    continue
  fi
  ok "$surface exists"

  heading_count="$(grep -c '^## Optional Context$' "$surface")"
  if [[ "$heading_count" -ne 1 ]]; then
    fail "$surface has exactly one '## Optional Context' heading (found $heading_count)"
    continue
  fi
  ok "$surface has exactly one '## Optional Context' heading"

  surface_block="$(extract_block "$surface")"
  if [[ -z "$surface_block" ]]; then
    fail "$surface: block is extractable and non-empty"
    continue
  fi

  if diff <(printf '%s' "$SOURCE_BLOCK") <(printf '%s' "$surface_block") > /dev/null 2>&1; then
    ok "$surface: Optional Context block is byte-identical to $SOURCE_FILE"
  else
    fail "$surface: Optional Context block is byte-identical to $SOURCE_FILE"
    echo "    --- diff ($surface vs $SOURCE_FILE) ---" >&2
    diff <(printf '%s' "$SOURCE_BLOCK") <(printf '%s' "$surface_block") | sed 's/^/    /' >&2
  fi
done

# ---------------------------------------------------------------------------
# 3. Root CLAUDE.md is explicitly NOT required to be byte-identical (task
#    C1 scope: prose-extended for consistency, ships nowhere). Assert only
#    that it still names the mechanism, as a smoke check against total
#    drift — not a byte check.
# ---------------------------------------------------------------------------
if grep -q 'cc skill select' CLAUDE.md 2>/dev/null; then
  ok "root CLAUDE.md still references 'cc skill select' (prose consistency, not byte identity)"
else
  fail "root CLAUDE.md still references 'cc skill select' (prose consistency, not byte identity)"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
