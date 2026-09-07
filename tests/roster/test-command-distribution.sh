#!/usr/bin/env bash
# test-command-distribution.sh — roster/distribution test (work package C,
# task C3/C4).
#
# C3's finding: the VERSION.json roster (not file presence in
# .claude/commands/) decides what actually ships to a project or machine
# (tools/cc/src/cc/core/ecosystem/canonical_transaction.py:claude_reference_roster
# reads components.commands.projectCommands / machineCommands;
# project_integration.py:_claude_source_files consumes exactly that roster).
# This test asserts:
#   1. `reflect.md` specifically appears in `components.commands.projectCommands`.
#   2. Every command file intended for delivery appears in SOME roster
#      (project or machine) -- with an explicit, documented allowlist of
#      commands that are deliberately repo-local (not a silent pass).
#   3. A real disposable-project install (activate_components, the same
#      function `/setup-project` drives) actually places reflect.md on disk
#      in a scratch project directory -- not just that the resolver
#      function says it would.
#
# NEW FILE ONLY. Does not modify any existing test.
#
# Run: bash tests/roster/test-command-distribution.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
cd "$PROJECT_ROOT" || exit 1

PASS=0
FAIL=0

ok() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }

VERSION_JSON="$PROJECT_ROOT/VERSION.json"
CC_VENV_PYTHON="$PROJECT_ROOT/tools/cc/.venv/bin/python"
CC_SRC="$PROJECT_ROOT/tools/cc/src"

if [[ ! -f "$VERSION_JSON" ]]; then
  echo "FATAL: $VERSION_JSON not found" >&2
  exit 1
fi

if [[ ! -x "$CC_VENV_PYTHON" ]]; then
  echo "FATAL: $CC_VENV_PYTHON not found or not executable — cannot exercise the real installer" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 1. reflect.md is specifically in components.commands.projectCommands
# ---------------------------------------------------------------------------
REFLECT_IN_PROJECT_COMMANDS="$(python3 -c "
import json
d = json.load(open('$VERSION_JSON'))
print('reflect.md' in d['components']['commands']['projectCommands'])
")"

if [[ "$REFLECT_IN_PROJECT_COMMANDS" == "True" ]]; then
  ok "reflect.md is in components.commands.projectCommands"
else
  fail "reflect.md is in components.commands.projectCommands"
fi

# ---------------------------------------------------------------------------
# 2. Every command file intended for delivery appears in a roster
#
# "Intended for delivery" is not self-defined by the roster (that would be
# circular): it is every .md file physically present in .claude/commands/
# MINUS an explicit, named allowlist of commands documented elsewhere as
# deliberately repo-local / not yet distributed. Any command that is
# neither rostered nor allowlisted fails loudly, so a future command added
# to .claude/commands/ cannot silently ship nowhere the way reflect.md did.
#
# Allowlist basis (checked against this repo's own investigation,
# scratchpad/wp-c-evidence.md §3 "Distributed vs repo-local"):
#   - config.md              — configuration dashboard, no roster entry found
#   - setup-knowledge-sync.md — install command for a git-hook workflow, no roster entry found
#   - skills-approve.md      — documented in docs/70-reference/00-quick-reference.md
#                               as a user command, but absent from BOTH rosters today;
#                               a real gap, deliberately left as a documented exception
#                               here rather than silently passed or silently "fixed" by
#                               this test (fixing rosters is out of scope for C4, which
#                               authors tests only).
# ---------------------------------------------------------------------------
KNOWN_NOT_YET_ROSTERED=(
  "config.md"
  "setup-knowledge-sync.md"
  "skills-approve.md"
)

is_known_exception() {
  local name="$1"
  for known in "${KNOWN_NOT_YET_ROSTERED[@]}"; do
    [[ "$name" == "$known" ]] && return 0
  done
  return 1
}

ROSTERED="$(python3 -c "
import json
d = json.load(open('$VERSION_JSON'))
c = d['components']['commands']
rostered = set(c.get('projectCommands', [])) | set(c.get('machineCommands', []))
print('\n'.join(sorted(rostered)))
")"

UNACCOUNTED=0
for f in "$PROJECT_ROOT"/.claude/commands/*.md; do
  name="$(basename "$f")"
  if grep -qxF "$name" <<< "$ROSTERED"; then
    ok "$name is in a VERSION.json roster"
  elif is_known_exception "$name"; then
    echo "  SKIP (documented exception, not distributed): $name"
  else
    fail "$name is in a VERSION.json roster (unaccounted-for command — neither rostered nor a documented exception)"
    UNACCOUNTED=$((UNACCOUNTED + 1))
  fi
done

if [[ "$UNACCOUNTED" -eq 0 ]]; then
  ok "no unaccounted-for commands (every .claude/commands/*.md is either rostered or a documented exception)"
fi

# ---------------------------------------------------------------------------
# 3. Disposable-project install: exercise the real activate_components()
#    function (the same one core/ecosystem/workspaces.py:activate_components
#    drives for /setup-project) against a scratch project directory, using
#    THIS checkout as claude_root, then list the resulting directory.
# ---------------------------------------------------------------------------
SCRATCH_DIR="$(mktemp -d "${TMPDIR:-/tmp}/roster-distribution-test.XXXXXX")"
cleanup_scratch() { rm -rf "$SCRATCH_DIR" 2>/dev/null || true; }
trap cleanup_scratch EXIT

INSTALL_OUTPUT="$(PYTHONPATH="$CC_SRC" "$CC_VENV_PYTHON" -c "
from pathlib import Path
from cc.core.ecosystem.workspaces import activate_components

project = Path('$SCRATCH_DIR') / 'project'
project.mkdir(parents=True, exist_ok=True)
claude_root = Path('$PROJECT_ROOT').resolve()

activated = activate_components(project, ('claude',), claude_root=claude_root)
commands_dir = project / '.claude' / 'commands'
listing = sorted(p.name for p in commands_dir.iterdir()) if commands_dir.is_dir() else []
print('ACTIVATED:' + ','.join(activated))
print('REFLECT_PRESENT:' + str((commands_dir / 'reflect.md').is_file()))
print('LISTING:' + ','.join(listing))
" 2>&1)"
INSTALL_EXIT=$?

if [[ "$INSTALL_EXIT" -ne 0 ]]; then
  fail "disposable-project install via activate_components() exits 0"
  echo "    --- install output ---" >&2
  echo "$INSTALL_OUTPUT" | sed 's/^/    /' >&2
else
  ok "disposable-project install via activate_components() exits 0"

  if grep -q "^ACTIVATED:claude$" <<< "$INSTALL_OUTPUT"; then
    ok "activate_components() reports 'claude' activated"
  else
    fail "activate_components() reports 'claude' activated"
  fi

  if grep -q "^REFLECT_PRESENT:True$" <<< "$INSTALL_OUTPUT"; then
    ok "disposable project's .claude/commands/reflect.md exists after install"
  else
    fail "disposable project's .claude/commands/reflect.md exists after install"
  fi

  echo "    Directory listing of disposable project's .claude/commands/:"
  echo "$INSTALL_OUTPUT" | grep "^LISTING:" | sed 's/^LISTING://' | tr ',' '\n' | sed 's/^/    - /'
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
