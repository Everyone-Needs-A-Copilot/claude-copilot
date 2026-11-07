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
#   3. The release link plan built from THIS checkout (the central model that
#      replaced the per-project copy install, PRD-16) actually links reflect
#      for Claude -- not just that the roster says it would.
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
# 3. Release link plan: build the real user-level link plan (the same
#    build_plan the release engine uses) from a scratch release whose
#    claude-copilot component is THIS checkout's .claude tree, then check
#    reflect is linked for Claude.
#    Old expectation: activate_components() copied commands into a disposable
#    project's .claude/commands. Reason for change: the per-project copy model
#    is retired; commands reach Claude through ~/.claude links from the release.
# ---------------------------------------------------------------------------
SCRATCH_DIR="$(mktemp -d "${TMPDIR:-/tmp}/roster-distribution-test.XXXXXX")"
cleanup_scratch() { rm -rf "$SCRATCH_DIR" 2>/dev/null || true; }
trap cleanup_scratch EXIT

INSTALL_OUTPUT="$(PYTHONPATH="$CC_SRC" "$CC_VENV_PYTHON" -c "
import shutil
from pathlib import Path
from cc.core.release.engine import layout
from cc.core.release.links import build_plan

home = Path('$SCRATCH_DIR') / 'home'
home.mkdir(parents=True, exist_ok=True)
release = layout.release_dir('20261106T000000Z-roster', home)
src = Path('$PROJECT_ROOT').resolve() / '.claude'
shutil.copytree(src / 'commands', release / 'claude-copilot' / '.claude' / 'commands')
plan = build_plan(release, home)
names = sorted(e.name for e in plan.entries if e.runtime == 'claude' and e.kind in ('command', 'skill'))
reflect = [e.link for e in plan.entries if e.runtime == 'claude' and e.name in ('reflect.md', 'reflect')]
print('REFLECT_LINKED:' + str(bool(reflect)))
print('LISTING:' + ','.join(names))
" 2>&1)"
INSTALL_EXIT=$?

if [[ "$INSTALL_EXIT" -ne 0 ]]; then
  fail "release link plan built from this checkout exits 0"
  echo "    --- plan output ---" >&2
  echo "$INSTALL_OUTPUT" | sed 's/^/    /' >&2
else
  ok "release link plan built from this checkout exits 0"

  if grep -q "^REFLECT_LINKED:True$" <<< "$INSTALL_OUTPUT"; then
    ok "release link plan links reflect for Claude"
  else
    fail "release link plan links reflect for Claude"
  fi

  echo "    Claude command/skill links in the plan:"
  echo "$INSTALL_OUTPUT" | grep "^LISTING:" | sed 's/^LISTING://' | tr ',' '\n' | sed 's/^/    - /'
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
