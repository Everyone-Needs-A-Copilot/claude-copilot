# CI acceptance and merge gates

Local QA approval and publication are separate decisions. A passing local check,
a successful CodeQL job, or GitHub's mergeable flag does not establish that the
whole delivery is green. A known pre-existing failure is still a failure.

This contract applies to Claude Code, Codex and human operators alike. GitHub
enforces the same main-branch gates regardless of which client performs a merge.
It reuses existing CI and tc evidence; it adds no testing service or agent loop.

## Scope and authority

The desired server policy is in
[`.github/ci-required-checks.json`](../../.github/ci-required-checks.json).
It covers Claude Copilot, CLI Copilot, CLI Copilot Internal and Copilot Control
Tower. It is an operator-reviewed policy, not an automatic rules reconciler.
Read back the live GitHub configuration to establish that it is installed.
Repositories without CI are **uncovered**, not implicitly green; adding their
pipelines is separate work.

Each covered repository has an additive, active `CSE CI merge gate` ruleset on
`refs/heads/main`: require a pull request, require the exact named checks from
GitHub Actions, and require an up-to-date branch. Its bypass-actor list is empty.
Existing signature, review, history, deletion and other protection rules remain
in force. Do not weaken those rules to unblock a repair.

## Delivery sequence and stopping point

1. Freeze the repository, candidate head SHA, current base SHA and expected
   applicable automatic workflows. Map the change to a bounded local test lane
   and the task's registered acceptance criteria; capture the tested identity.
2. Diagnose from the first divergent state. Classify a failure as implementation,
   fixture, environment or policy; fix the shared cause before adding tests.
   Use focused checks first and existing affected suites next. Keep the existing
   verification-policy caps; a timeout is incomplete, not a reason to retry
   repeatedly or silently enlarge the lane.
3. Push the candidate through a pull request. Inspect **all applicable automatic
   checks**, not just GitHub's configured required subset. Require successful,
   completed evidence for the exact candidate/tested merge revision. Missing,
   stale, pending, cancelled, failed or unknown evidence is incomplete.
4. A skipped inner job is acceptable only when its successful selector explicitly
   proves the change irrelevant and its final gate succeeds. Record manual or
   billed exclusions separately. Claude's live, billed evaluation is manual
   opt-in; the local evaluation remains required. CodeQL is not a substitute for
   functional tests, and functional tests are not a complete security audit.
5. Re-read the PR head and base before merging. If either changes, verify the new
   revision. Merge normally with an exact head guard; never use administrator
   bypass, force push or temporarily remove a failing required check.
6. Verify every expected automatic push workflow on the resulting **main SHA**.
   A missing main run is not success. Record the PR, merge SHA, run URLs, scoped
   results and fresh task-bound QA verdict in tc and the delivery receipt.

**Complete** means the accepted change is merged, its applicable PR and main CI
are green, the intended protections are verified live, and its registered
acceptance criteria have current evidence. Then stop. Do not start unrelated
warning cleanup, tool upgrades, new test platforms or speculative regressions.
If a required result is red or unavailable, report the exact unresolved cause
and whether the candidate remains unmerged; do not call the delivery complete.

During CI, report the current stage, new outcome or blocker concisely. Poll only
while a known run is active; do not loop endlessly on a failed run. A transient
infrastructure retry needs recorded evidence and a bounded retry decision.

## Path-scoped checks without missing required statuses

Claude's onboarding and time-language workflows always start for their existing
branch/event scope. A cheap selector validates the event's commit identities and
uses Git to inspect the exact original path scope. Pull requests use the merge
base; pushes use before/after SHAs. New-branch pushes conservatively run the suite.
Only a successful, explicit irrelevant result can skip an expensive suite.

The final `cc Onboard Contract gate` and `Time Estimate Language gate` jobs run
with `always()`. They reject selector errors, missing/unknown output, and any
applicable suite that fails, is cancelled, or is unexpectedly skipped. The inner
suite names are not required separately, because their documented irrelevant
skips are intentional. The selector/gate tests include negative controls.

GitHub documents that workflow-level path skips leave required checks pending;
job-level skips can instead count as successful. Explicit final gates make the
allowed skip condition observable and fail closed.
See [GitHub's required-check guidance](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks).

## Operating and changing the gates

Inspect a candidate with `gh pr checks <number> --repo <owner/repo>` and inspect
the workflow runs on its exact SHA. Confirm main with `gh run list --branch main
--commit <merge-sha> --repo <owner/repo>` and view each applicable run. Read both
rulesets and classic branch protection: they compose; one does not replace the
other. Save before/after configuration and verify the live applied main rules.

When adding or renaming an automatic workflow, update the manifest and live
rules together. First prove the new context reports on a PR, including an
unrelated-path case where relevant. Only replace an old required name once the
new result exists and its semantics are reviewed. Do not treat the manifest
alone as proof that a gate exists on GitHub.

If main turns red after a previously green merge, stop further delivery. Open a
bounded repair or reviewed revert PR and preserve the same gates. Policy failures
(for example instruction-context budgets) need a policy-consistent correction or
an explicit owner decision; do not disable the assertion, silently raise a cap,
approve an override, or reinterpret red as green. Additional Dependabot PRs and
their notification emails follow these same gates; dependency churn is not an
exception to acceptance.

These checks prevent known required CI failures from being merged through the
normal path. They cannot guarantee that every defect has a test, that hosted
infrastructure never fails, or that an administrator cannot later edit policy.
