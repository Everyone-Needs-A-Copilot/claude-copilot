#!/usr/bin/env bash
# Shared tc v2 test input for lifecycle suites. The caller owns a disposable
# TEST_ROOT/TEST_PROJECT; this helper never uses the author's project database.
store_evidence() {
  local task_num="$1"
  local verdict="${2:-APPROVED}"
  local content identity
  printf '%s\n' 'guarded fixture' > "$TEST_PROJECT/acceptance-input.txt"
  printf '%s\n' '{"schemaVersion":2,"criteria":[{"id":"C1","expected":"The guarded fixture input exists"}],"sources":["acceptance-input.txt"]}' > "$TEST_ROOT/contract.json"
  (cd "$TEST_PROJECT" && tc task contract "$task_num" --file "$TEST_ROOT/contract.json" --json) >/dev/null || return 1
  identity="$(cd "$TEST_PROJECT" && tc task evidence-identity "$task_num")" || return 1
  (cd "$TEST_PROJECT" && test -f acceptance-input.txt) || return 1
  content="CRITERION: C1
EXPECTED: The guarded fixture input exists
OBSERVED: test -f acceptance-input.txt returned exit 0 against the captured source
$identity
BASELINE: unavailable, fresh fixture database
ARTIFACT: test-run|test -f acceptance-input.txt exit=0
UNTESTED: none
VERDICT: ${verdict}"
  (cd "$TEST_PROJECT" && tc wp store --task "$task_num" --type test --title "Fixture QA evidence" --content "$content" --json) >/dev/null 2>&1
}

store_passing_evidence() {
  store_evidence "$1" "APPROVED"
}
