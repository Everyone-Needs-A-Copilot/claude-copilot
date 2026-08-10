#!/bin/bash
# check-test-wiring.sh
#
# Anti-rot invariant: fails if a test file exists in the repo but no CI
# workflow runs it. This is the guard against the exact failure this
# script was written to prevent -- 76 of 99 tools/cc/tests files and the
# entirety of root tests/ and tools/tc/tests were unreferenced by any
# workflow because the CI wiring enumerated individual filenames instead
# of sweeping directories.
#
# Coverage model (two ways a test file can be "covered"):
#   1. GLOB ROOTS -- directories a workflow sweeps wholesale (e.g.
#      `pytest tools/cc/tests/`, `find tests -name '*.test.ts'`). Any
#      file added under one of these roots is covered automatically,
#      with zero workflow changes. This is the preferred, drift-proof
#      pattern and covers the overwhelming majority of test files.
#   2. NAMED FILES -- a small, deliberately curated list (tests/hooks/*.sh
#      run in an explicit, order-sensitive sequence in smoke-tests.yml;
#      .claude/fitness-check.sh) where the ordering/rationale matters
#      enough that per-file listing is intentional, not accidental. These
#      are checked by literal basename match against every workflow file.
#
# If this script fails, either (a) a genuinely new, uncovered test
# location was added -- wire it into a workflow, preferring a whole-
# directory/glob run over naming the file -- or (b) the GLOB ROOTS /
# NAMED FILES lists below need to be updated to reflect real CI wiring.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

WORKFLOWS_DIR=".github/workflows"
UNCOVERED=0

# Directories that a workflow sweeps as a whole (pytest <dir>/ or a glob
# over *.test.ts) -- see pytest-suites.yml and agent-skill-ts-tests.yml.
GLOB_ROOTS=(
  "tests"                # root pytest suite (--ignore=tests/tui) + *.test.ts glob
  "tools/cc/tests"
  "tools/tc/tests"
  ".claude/skills"       # scripts/test_*.py, swept via `pytest .claude/skills`
)

is_under_glob_root() {
  local f="$1"
  for root in "${GLOB_ROOTS[@]}"; do
    case "$f" in
      "$root"/*)
        # tests/tui is a vendored third-party package's own suite, run by
        # its own dedicated job (vendored-monitor-tests in
        # pytest-suites.yml) via an explicit `find tests/tui -name
        # 'test_*.py'` file list -- NOT part of the `pytest tests/
        # --ignore=tests/tui` copilot sweep (this repo's root conftest.py
        # deliberately collect_ignore_globs it out of that sweep). Treat
        # it as covered by directory, checked separately below.
        [[ "$root" == "tests" && "$f" == tests/tui/* ]] && continue
        return 0
        ;;
    esac
  done
  return 1
}

is_named_in_a_workflow() {
  local basename="$1"
  grep -rl --fixed-strings "$basename" "$WORKFLOWS_DIR"/*.yml >/dev/null 2>&1
}

is_under_vendored_monitor_root() {
  local f="$1"
  case "$f" in
    tests/tui/*) return 0 ;;
    *) return 1 ;;
  esac
}

check_file() {
  local f="$1"
  if is_under_glob_root "$f"; then
    return 0
  fi
  if is_under_vendored_monitor_root "$f"; then
    return 0
  fi
  if is_named_in_a_workflow "$(basename "$f")"; then
    return 0
  fi
  echo "UNCOVERED: $f (not under a glob-swept root and not named in any .github/workflows/*.yml)"
  UNCOVERED=1
}

# 1. Python pytest files.
while IFS= read -r -d '' f; do
  check_file "$f"
done < <(find tests tools/cc/tests tools/tc/tests .claude/skills -type f -name 'test_*.py' -print0 2>/dev/null)

# 2. TypeScript test-runner files.
while IFS= read -r -d '' f; do
  check_file "$f"
done < <(find tests -type f -name '*.test.ts' -print0 2>/dev/null)

# 3. Shell test suites (both naming conventions used in this repo:
#    tests/hooks/test-*.sh and tests/*.test.sh).
while IFS= read -r -d '' f; do
  check_file "$f"
done < <(find tests/hooks -type f -name 'test-*.sh' -print0 2>/dev/null)

while IFS= read -r -d '' f; do
  check_file "$f"
done < <(find tests -maxdepth 1 -type f -name '*.test.sh' -print0 2>/dev/null)

# 4. Named single-file suites outside GLOB_ROOTS.
if [[ -f ".claude/fitness-check.sh" ]]; then
  check_file ".claude/fitness-check.sh"
fi

if [[ $UNCOVERED -eq 0 ]]; then
  echo "OK: every test file is either under a glob-swept root or named in a workflow."
  exit 0
else
  echo ""
  echo "FAIL: one or more test files are not run by any CI workflow."
  echo "Wire the suite in (prefer sweeping its containing directory over"
  echo "naming the file) or extend GLOB_ROOTS in this script."
  exit 1
fi
