## Proportional Verification

Record criterion, affected consumers, lane/commands, exclusions/reasons and cap
before checks. Select behavior and risk, not file extension.

| Change | Default checks | Expand when |
|--------|----------------|-------------|
| Instructions/routing | Parse, references, manifest, actual dispatch/hook wiring | Changed routing/judgment: bounded behavioral scenario; wording alone does not require live model evaluation |
| Logic/transformation | Reproducer, boundaries, affected callers | Shared API, serialization, concurrency/state change |
| Storage/installation | Disposable real persistence, rollback, preservation, repeat no-op | Schema/installer/release: platform/snapshot coverage |
| UI behavior | Seeded Playwright semantic assertions; comparable before/after trace and video for defects | Shared component/navigation/auth/responsive changes: affected journeys/states |
| Machine/model effectiveness | Separate environment assessment or frozen paired evaluation | Relevant machine/model change, never an unrelated code edit |

Unknown impact selects a broader named lane, never an empty selection. New tests
are required for missing behavior coverage, not each edited file. Existing mapped
coverage may suffice; unexplained gaps or broken behavior fail approval. Preserve
safety, concurrency, transaction and evidence-parser negative controls.

Reproduce first: expected/actual values and first divergent state. Inspect extra-item
IDs/membership and the introducing transformation, not count alone. Failures through
one unchanged dependency are one observation. After two falsified root-cause
hypotheses, inspect the enforcement path and cite file:line; change investigation,
not more speculative tests or automatic abandonment.

### Fixed finish line

Before implementation, state the deliverable, required acceptance criteria,
affected consumers, verification lane/cap and explicit exclusions in the task.
Freeze that boundary for the batch; a new requirement needs an explicit scope
decision, not an automatic extra improvement.

Run the smallest sufficient checks, then one planned batch acceptance pass.
Repair failures caused by this change and rerun affected checks only. Record
unrelated defects separately; they do not silently reopen completed work. A
pre-existing defect that prevents a required criterion still blocks that criterion.
Never lower acceptance or hide a failure to meet a cap.

When every required criterion has current source-bound QA approval, close the
task, report what is complete and any separately pending work, then stop. Do not
start another polish, audit, broad rerun or follow-up task without a new request.
Missing required evidence or an exhausted cap means incomplete, not complete;
report the specific blocker and stop automatic retries until scope/cap is decided.

Focused checks first; broad portable checks once per completed batch/release.
Rerun affected checks when inputs change. Caps: focused 60 seconds, affected 180
seconds, broad 900 seconds. Show operation, elapsed time and artifact path at least
every 30 seconds. Timeout is incomplete, never a pass or silent restart; record a
scope/cap decision before retry. Limits are ceilings, not required passes or delivery
estimates. Test subprocesses need no model inference.
Reuse requires matching source/test/dependency/runtime/config/data, cases, commands
and intact successful artifacts; non-hermetic machine/model runs are not cacheable
by default. Reuse artifacts, never another task's approval: tc remains the sole
source-bound QA authority.

Never weaken, skip or delete assertions to hide a defect. Obsolete-contract migration
requires explicit authority, old/new expectations and rationale, exact changed
assertions/diff and a negative control rejecting the targeted broken behavior.
Report changed tests; green alone does not establish integrity. Escalate undecided
authority/behavior. UI healing cannot pass by skipping required behavior; evidence
stays local/private unless upload is explicitly authorized.

### Codex test-change receipt

`scripts/check-test-integrity.sh <base-ref> --test-change-receipt <local.json>`
validates an explicitly reviewed change, not authority or semantic correctness.
Keep the comparison base fixed. Receipt schema 1 requires:

- `baseCommit`, `task`, `authorizationRef`, `oldExpectation`, `newExpectation`,
  `rationale`: exact base commit and real task/user authority plus contract change.
- `changes`: exact changed grading-file set; each entry has repository-relative
  `path`, `beforeSha256`, `indexSha256`, `afterSha256` (null only for absence), and
  `assertions` describing the exact additions/removals/changes.
- `diffSha256`: SHA-256 of compact JSON of the hexadecimal byte strings of both
  unstaged-plus-staged and cached diffs against the base, using `git diff
  --no-ext-diff --no-textconv --binary --no-renames`, restricted to sorted changed
  grading paths. Content hashes also bind untracked test files.
- `negativeControl`: command argument array, nonzero `exitCode`, `rejectedBehavior`,
  repository-relative artifact `path` and its `sha256`. Capture a real rejection of
  the targeted broken behavior in a disposable copy; do not invent a log or status.

The gate detects missing/stale evidence, not whether these claims are true. QA must
review authority, exact assertions and the negative control before source-bound tc
approval; receipt success alone is not a pass. `tests/test_verification_policy.py`
contains a synthetic format example and adversarial fixtures, not reusable authority.
