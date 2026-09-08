# Testing rethink: evidence and recommendations

Explanation and proposed operating policy, 2026-09-08. Execution record:
Claude Copilot PRD-4 / TASK-55; repairs TASK-49, TASK-51, TASK-53, TASK-54.
Read with [the incoming handoff](13-handoff-remaining-work-and-testing-rethink.md).
This review does not change the global QA policy or purchase a testing service.

The recommendation is to keep deterministic tests, select them by the changed
behavior and its consumers, and stop making every repair restart the whole
verification process. Use agents to reproduce, investigate and author useful
checks; ordinary test execution should not require model inference. Preserve
real boundary tests for installation, persistence, recovery and evidence binding.
For UI work, make a reproducible Playwright scenario and its before/after trace
and recording the central artifact.

## What was measured

Measurements are local observations on this busy macOS machine with Python
3.14.7, not CI benchmarks or performance guarantees. Claude's worktree already
contained substantial uncommitted work; Codex's tree was clean at `e90ecee`.
No live model trial was launched. Deterministic test execution does not itself
consume inference tokens; agent investigation, tool output and repeated review do.
This session does not have a defensible total token-cost measurement for prior
sessions, nor historical failure/flake rates.

| Observation | Result | What it establishes |
|---|---|---|
| Complete `tools/tc` pytest run | 585 passed in 24.59 seconds | This suite alone does not explain an hours-long cycle |
| First `tools/cc` collection | Failed in 1.76 seconds: missing numpy | Environment preflight was missing; numpy was already declared in the dev extra and was installed locally |
| Bounded `tools/cc -m 'not machine'` baseline | Stopped after 240 seconds at approximately 71%, with failures visible | There is material test execution cost; this was an incomplete run, not a failed-test census |
| Complete portable `cc` batch after the roster repair | 3,093 passed, 11 skipped, 2 failed in 384.83 seconds | Approximately 6 minutes 25 seconds, not hours; both failures were snapshot fixtures mixing the working installer with old HEAD |
| Roundtrip reproduction | 3 failed, 30 passed in 26.02 seconds | Exact failures identified before the roster fix |
| Focused roundtrip + roster + shared mirror checks after repair | 66 passed in 37.93 seconds | Repairs work at their real seams, including disposable installs |
| Stack/root-cause checks including machine observations | 100 passed, 3 failed in 13.05 seconds | Mirror resolution works; machine assertions/configuration still disagree in three named places |
| Restored owner hook suite | 68 assertions passed; median hook invocation 44 ms | Preserved suite passes, including the existing 50 ms threshold; the handoff's 76-case count was inaccurate |
| Additional budget boundaries | 3 passed in 0.89 seconds | UTF-8 charging, denied retry accounting, concurrent exact totals, and committed CI override enforcement |
| Snapshot fixture repair, TASK-56 | 24 passed in 54.45 seconds | Disposable current-candidate commit replaces mixed source identities; real install, preservation and rollback assertions retained |
| QA-hook fixture repair, TASK-56 | 18 assertions passed | A real v2 contract/identity replaces obsolete evidence; bare claims and stale source evidence still fail |
| Complete machine-only `cc` lane | 28 passed, 11 skipped, 7 failed in 25.32 seconds | Remaining environment/contract discrepancies are enumerated below, not suppressed |
| Codex hook verification / structural agent contracts | Passed in 0.48 / 6.13 seconds | These are deterministic structural checks, not a live model effectiveness trial |

The complete portable batch preceded the final TASK-56 **test-fixture-only**
repair. Its two failures then passed in the complete 24-test snapshot file. The
whole portable suite was not restarted after that migration; do not relabel its
recorded result as a fresh zero-failure full run. The full `tc` suite remained
unchanged. Final hook boundary rerun: 3 passed in 0.82 seconds. Hook registration
and disposable project-shim checks: 4 and 11 assertions passed, respectively.

The portable batch's largest measured test-file costs were roundtrip (56.42 s),
snapshot installation (54.95 s), canonical transactions (33.12 s), and knowledge
skill sources (30.79 s). Together these account for about 46% of summed case time.
These are the first fixture/transaction costs to inspect, not grounds to delete
their unique assertions. The same roundtrip file ran much faster in the focused
run; concurrent machine load and shared environment effects matter.

The unchanged hook performance assertion also exposed load sensitivity: median
103 ms during concurrent installation tests, then 44 ms (45, 44, 45, 44, 44)
with those jobs finished. Both results are retained. An idle pass establishes
the measured idle target, not a universal 50 ms guarantee. Run performance
checks under a declared workload separately from functional correctness.

The source inventory contains 145 `cc` test files with 2,721 test functions
(parameterization changes collected case counts). There are 507 conformance
functions, 137 evaluation functions, 15 in the integration directory, and at
least 825 ecosystem-related functions in 51 top-level files selected by filename.
The remaining 1,237 functions are not all simple unit tests. This is an inventory
heuristic, not a behavioral classification or a justification for deletion.

### Structural costs visible in the foundation

- `.claude/agents/qa.md` requires NEW tests for changed code, a typical coverage
  threshold, unit plus integration for backend files, and E2E for frontend files.
  Its loop permits 12 iterations. `.claude/agents/me.md` also asks for all existing
  and new tests to pass. These instructions can multiply a small change into
  repeated broad work. Their presence proves an amplification mechanism, not how
  often it caused the owner's prior delays.
- Codex's QA/engineering skills already say to run the smallest meaningful tests
  and add coverage proportionally. Port that proportionality back into Claude's
  operating policy while retaining task-bound evidence.
- `pytest-suites.yml` runs the whole portable cc suite. `conformance.yml` repeats
  its portable conformance directory. `cc-onboard-contract.yml` repeats a sizable
  subset on macOS; OS-specific validation can be valuable, but should be explicitly
  budgeted as a platform lane. Separate workflows have separate concurrency groups.
- Codex's `smoke-test.sh` invokes parity, hooks, version checks, routing generation,
  structural agent evals and update verification. `run-agent-evals.sh` launches
  `cc eval run` once per roster entry and discards each JSON result. Those checks
  should be named and timed separately; “agent evals” must say whether they are
  structural checks or actual model executions.
- The roundtrip suite performs several real setup/update transactions with
  overlapping assertions. Keep unique preservation, repeat-update and failure
  checks, but share an immutable prepared source fixture where safe. Do not share
  mutable installed destinations across tests.
- The readonly tripwires and temporary config roots prevent real machine mutation.
  Preserve prevention and detection when optimizing fixture cost.
- A real plan selecting only `flow` returned a census of 49 repositories. Scope
  should limit work performed where possible, not only filter the final report.
  No census optimization was implemented in this review.

## What the bug history supports

The review used a deliberately stratified sample of older and recent fixes across
Claude and Codex, inspecting production diffs and accompanying test changes.
It is not a random sample and cannot estimate escape rate, test recall, or a
percentage of all defects that are relational. A newly added regression test is
evidence of a missing scenario; it is not proof that no previous test could fail.
Old commits were inspected, not replayed against every historical environment.

| Commit | Failure class / root mechanism | Test evidence and implication |
|---|---|---|
| Claude `ee0b04e`, `1afe0c9` | Two command allowlists disagreed with the manifest | Commit records explicitly say real install/recovery rehearsals found these; added tests cover new commands and invalid paths |
| Claude `7c9fedf` | Immutable source permissions copied into writable projects | Added workspace regression for mode handling; a real filesystem seam is required |
| Claude `7858fb3` | Conformance counted runtime-owned overlays as framework drift | Existing effectiveness tests changed alongside the ownership boundary; “green” requires the correct ownership contract |
| Claude `aaf186f` | Reconciliation missed authoritative source changes | Existing recipe/reconciliation tests gained scenarios; test the source-to-plan-to-installed relationship |
| Claude `28facd3` | Targeted conformance request still executed broad collectors | Added routing test for narrow execution; test work performed, not just filtered output |
| Claude `7fc34ca` | Runtime packaging omitted dispatch verification dependencies | Added installer/runtime contract tests; a source import pass was insufficient |
| Claude `380a22e` | macOS lock path assumed on Linux | Existing runtime tests were extended for platform selection; controlled platform cases matter |
| Claude `bd922d5` | Drift checker searched only current-branch history | Commit explains a false alarm against newer deployed content; the verifier can be the defective component |
| Codex `0c02077` | Org plugin detection assumed checkout directory names | Existing update verification gained the pinned-mirror layout; test supported source layouts |
| Codex `7c7c064` | Plugin sync compared content but missed executable mode | Update verification gained mode-change scenarios; byte equality alone was insufficient |
| Codex `32066b4` | Hook launcher assumed one runtime environment variable | Only hook registration changed in that commit; payload-level tests alone do not establish launcher reachability |
| Codex `214ca52` | Updater fingerprint format/source choice violated lock contract | Existing update verification changed; validate serialized output against the consumer's schema |
| Codex `7f7d6f6` | Parity baseline update accepted insufficient proof | Added adversarial verifier cases; tests of evidence acceptance need negative controls |

This confirms that source/consumer disagreement and environmental seams deserve
first-class tests in this foundation. It does **not** support replacing evidence
parser, task state, search, arithmetic or transaction tests with text invariants.

## Proposed verification lanes

Select the lane from what changed, not the filename extension alone. A skill text
edit, an evidence parser change and a filesystem transaction have different risks.

| Work | Default verification | Escalation trigger |
|---|---|---|
| Instructions, skills, routing | Parse/frontmatter, referenced files, manifest membership, actual registration/dispatch wiring, changed structural contract | Instruction changes a model decision: one bounded behavioral scenario; release/pilot uses broader held-out evaluation |
| Pure code/transformations | Small reproducer, expected value/membership, relevant boundary cases | Shared caller or state transition changes: affected contract tests |
| Persistence/API/CLI | One real boundary test for persisted output, failure and rollback where applicable | Schema, concurrency, auth, recovery or shared serialization change |
| Installation/reconciliation | Shared roster/path invariants plus disposable plan/apply/independent verify; second apply no-op; preserve customized files | Release, installer or transaction change: immutable source and platform lanes |
| UI interactions | One seeded Playwright scenario with semantic outcome assertions, before/after trace and video | Changed navigation, authentication, responsive behavior or shared component: affected journey/state matrix |
| Model effectiveness | Separate frozen baseline/candidate paired trial with actual review | Changes to routing/judgment/learning; never a compulsory rerun for unrelated code edits |

For the array example, compare **membership**, not merely length. First record
the nine returned IDs, the seven required IDs, and where the two extras entered
the transformation. Fix that predicate, exercise its input partitions, and check
the consumer once. Two distinct bugs can yield the same count, and seven items
can still be the wrong seven. The new roundtrip checks explicitly include
equal-count/wrong-membership negative cases.

For a cluster of failures: group by the first shared failing dependency, reproduce
one representative, inspect every caller of that dependency, then run the affected
checks as a set. Record additional independent defects separately. After two
falsified hypotheses, read the enforcing code and change the experiment; do not
generate more speculative tests. This follows Codex's existing debugging rule.

### Make execution visible and bounded

Every run should publish the selected lane and reason, command, selected tests,
source/environment identity, start time, elapsed time, currently running case,
pass/fail/skip counts and local artifacts. Keep verbose output in a file; show a
short heartbeat and failure summary. A timeout is **incomplete**, never a pass.

Proposed budgets are operational limits, not delivery estimates: targeted checks
start with a 60-second ceiling; affected integration work with a three-minute
ceiling; broad release verification uses measured suite baselines and its own
explicit cap. Hitting a cap produces a named slow case and a scope decision.
Do not silently restart. Record compute wall time separately from agent reasoning,
review time and model token cost. Slowest-test reports and JUnit XML should be
retained automatically in CI and linked from `tc`.

Run focused checks during repair, the affected closure once after the fix, and
the broad suite once for a completed batch/release. Reuse recorded execution
artifacts when the command, inputs, dependencies and tested identity are unchanged;
each task still needs its own acceptance mapping and valid tc identity. Source
changes invalidate affected evidence. A new task ID alone should not require
executing the identical external command again.

Keep one owner for every full CI suite. Remove redundant same-platform execution
only after confirming inventory coverage; retain the full-directory discovery
guard so new tests cannot disappear from CI. The repo previously missed 76 of
99 cc files through an enumerated allowlist. Narrow local selection must not
recreate that problem in the release gate.

Machine-dependent checks should be a clearly reported environment lane with an
owner and required release triggers, not abandoned quarantine. A fixture that
expects every cell to be an authoring checkout cannot grade a machine deliberately
migrated to immutable mirrors. A missing signer declaration is a configuration
failure; it should not masquerade as a defect in a path resolver.

### Keep test integrity without freezing obsolete contracts

Maintain the prohibition on weakening assertions to make broken behavior pass.
Allow a contract migration when the task/user has authorized the new behavior:
record the old/new rule, why the change is intended, the exact test diff, and a
negative control that still rejects a broken implementation. Preserve before
evidence. An unchanged test of an obsolete contract is not automatically correct.

The current Codex integrity script reports any added test or edited fixture as
unverified. Its task exception needs an explicit machine-readable contract-change
record, not repeated permission requests or an unchecked environment bypass.
This is a recommendation; that gate has not been modified here.

## UI testing: the practical tool choice

Start with Playwright Test plus a visible browser session driven by the existing
coding agent. Microsoft's [Playwright CLI](https://github.com/microsoft/playwright-cli)
supports headed sessions and a dashboard with live session views. That is a close
fit to this ecosystem's CLI boundary and the owner's need to see progress.

For defect work: seed a stable state, reproduce the original failure, save its
trace/video, fix the product, rerun the same scenario with the same assertions,
then review the successful trace/video. Keep the successful verification video
for the task; normal regressions may retain only failures. Use a first-run trace
when retries are disabled: `on-first-retry` would otherwise record nothing.
Playwright provides trace and video controls in its
[recording configuration](https://playwright.dev/docs/test-use-options), and the
[trace viewer](https://playwright.dev/docs/trace-viewer) adds actions, snapshots,
network and diagnostic detail that video alone cannot establish.

Playwright also supplies planner, generator and healer
[test agents](https://playwright.dev/docs/test-agents) for Claude/Codex.
They author/repair tests; they are not an independent proof that the product is
correct. The documented healer can skip a test when it believes the functionality
is broken. That behavior must not count as a passing Copilot verdict. Prefer one
existing QA agent with the CLI for a narrow defect; do not make a three-agent
chain mandatory for every button. Generated agent definitions currently include
MCP tools, so adopting those verbatim would require revisiting this foundation's
explicit CLI-only development-tool boundary.

If hosted execution is valuable, pilot one representative UI journey before a
platform decision:

| Option | What it supplies | When to consider it |
|---|---|---|
| Local Playwright + CLI | Visible agent work, deterministic regression code, local artifacts | Recommended starting point; fits current ownership and tooling |
| Browserbase | Hosted browsers with live inspection and replay; connects existing Playwright automation | Browser infrastructure or shared live visibility becomes the bottleneck; [official session docs](https://docs.browserbase.com/platform/browser/getting-started/using-browser-session) |
| QA Wolf | Playwright-based testing platform and optional managed test maintenance, investigation and video playback | You want to buy ongoing QA operation as a service; [vendor capability description](https://www.qawolf.com/) |

These are capability comparisons, not measured CSE results or pricing quotes.
Hosted browsers will not shorten Python tests or fix duplicated source contracts.
No vendor account, upload, integration or subscription was created. The foundation
can remain local while a consuming app opts into a hosted browser service.

## Adoption order

1. Ratify proportional test selection, visible runs and a stop condition in Claude
   and Codex's QA/engineering contracts. Retain tc evidence binding.
2. Add timing/JUnit artifacts and explicit suite ownership to the existing runners.
   Consolidate duplicate CI work after checking discovered inventory.
3. Establish one Playwright defect workflow in a real consuming frontend: failure
   reproduction, product fix, equivalent before/after evidence and persistent
   regression. Compare local and hosted operation only if infrastructure cost is
   observed.
4. Use the next representative changes to measure total feedback time, repeated
   executions, failure diagnosis time, test maintenance and escaped defects.
   Keep the separately specified human effectiveness pilot open until a real
   reviewer supplies its required observations.

Success means shorter measured feedback with equally strong observable contracts,
not a lower test count or more green verdicts. Unknowns: historical token/rework
costs, cross-machine runtime distribution, comparative hosted-service performance,
and whether the proposed workflow improves defect outcomes on held-out work.

## Repairs and remaining operational work

TASK-49 implements the owner-specified byte/file budget instead of the five-call
streak: accumulated state, denied attempts not charged, no reset on dispatch,
warnings, exact reviewed overrides, and CI use of committed override entries only.
The owner shell test is byte-identical to Git blob
`ebf9e4aa25027965e341aa9533fff845d75affd8` (SHA-256
`63e12600de26fb1dcb896ef16a74a2b0baba0b26605d9f410cca548ff1988809`).
It runs in a disposable copy because it manipulates hook state and override files.
The byte accounting is a cost estimate, especially for Bash, not model token billing.

TASK-51 removes the roundtrip's independent command enumeration and binds current
reference checks to the authoritative source manifest. Missing, extra, future,
and equal-count/wrong-member cases are checked. Codex plugin membership also comes
from the independent source, never from the installed destination being graded.
Historical negative fixtures stay historical; exact comparison remains enforced.

TASK-53 and TASK-54 mirror-resolution code was already present when this review
started, despite the incoming handoff's statement that TASK-54 was unimplemented.
The focused and machine checks validate those changes; this session did not
rewrite either resolver or their existing machine tests. Both delegate to the
shared mirror content-root computation. TASK-56 fixes the two adjoining stale
fixture contracts described in the measurement table. Existing installer,
provenance, evidence and signature enforcement was not weakened.

Seven machine-only failures remain. They are not a green release verdict:

- Organization attribution expects a current `cco` winner but gets no such row.
- Two stack assertions expect all 16 authoring cells to skip mirror verification
  and only 80 meaningful results. The accepted mirror design now produces PASS
  for the two foundation mirrors and 82 meaningful results.
- CLI and Knowledge foundation signer declarations are absent; Claude and Codex
  foundation signer checks pass.
- Fleet classification expects 13 repositories not found in this machine's scan.
- The active non-Git-root fixture expects an unavailable `audible` root.
- Shared-docs discovery expects `/Volumes/Dev/Sites/...`, unlike this machine's
  `/Users/pabs/Sites/...` location.

TASK-50's original effective-source exception no longer occurs in the real
configuration: the pinned mirror verifies and a real Claude+Codex plan completes.
The effective Codex source is
`/Users/pabs/.copilot/mirrors/codex-foundation/plugins/codex-copilot`, ref `v0.7.0`,
tree `a35a7aa6f9e31f88899cd347a49c92801379bf1a`, signer
`SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo`.
Production signature verification succeeds for both the authoring repository and
mirror; exact pinned-byte provenance succeeds only for the mirror. The evolving
authoring repository differs from the pin (`git diff --quiet` returns 1), as
expected. Do not freeze or revert it. Plain `git verify-tag` under the ambient
Git trust configuration prints a good signature but exits 1 with “No principal
matched”; it is not equivalent to the production verifier's scoped trust file.
TASK-50 is not marked fully complete: advancing the release pin remains separate,
and its original failure's whole-plan-versus-component blast-radius criterion was
not established. A controlled replay reusing census observations stopped earlier
at a stale recipe/state validation error; it is not evidence of that requested
failure path. No production manifest was changed to manufacture a failure.

The plan for `/Users/pabs/Sites/COPILOT/flow` selected 23 operations, including
Claude 5.15.0 and the older signed Codex 0.7.0. It was inspected, **not applied**.
Its recorded ID is `plan_99e1fae3b2661e9b24d6944f3e5a064f`; it is an expiring
diagnostic artifact, never an instruction to reuse that ID for a later apply.
The first request incorrectly named `/Users/pabs/Sites/COPILOT` as an approved
root; correcting the request to the machine-approved `/Users/pabs/Sites` allowed
planning without changing machine policy.

TASK-36 propagation remains held: the current Claude changes are not an agreed
committed distribution candidate, and the effective Codex pin does not contain
all evolving authoring content. The disposable snapshot fixture proves installation
of a test candidate; it is not a published release or permission to publish the
owner's existing changes. A foundation signing key is **not** a precondition for
Claude configuration distribution. Select/commit the intended Claude candidate,
advance Codex through its signed-release/pin lifecycle, then use a fresh individual
plan/apply/independent-verify for each eligible project. No consumer was modified.

The exact TASK-36 inventory was rechecked read-only. Paths are shown in full to
avoid treating similarly named source, tier and consumer repositories as peers.

| Path | Disposition |
|---|---|
| `/Users/pabs/Sites/COPILOT/convoco` | Clean; held for distribution candidate |
| `/Users/pabs/Sites/COPILOT/drip-copilot` | Clean; held for distribution candidate |
| `/Users/pabs/Sites/COPILOT/flow` | Clean; plan inspected; held for distribution candidate |
| `/Users/pabs/Sites/COPILOT/force-readiness-assessment` | Clean; held for distribution candidate |
| `/Users/pabs/Sites/COPILOT/insights-copilot` | Clean; held for distribution candidate |
| `/Users/pabs/Sites/COPILOT/pipeline-copilot` | Clean; held for distribution candidate |
| `/Users/pabs/Sites/COPILOT/research-copilot` | Clean; held for distribution candidate |
| `/Users/pabs/Sites/COPILOT/voice-copilot` | Held; nine `owner: project` agents, untouched |
| `/Users/pabs/Sites/COPILOT/method-copilot` | Held; no lock |
| `/Users/pabs/Sites/COPILOT/everyone-needs-knowledge-management` | Held; no lock |
| `/Users/pabs/Sites/COPILOT/preflight-copilot` | Held; no lock |
| `/Users/pabs/Sites/COPILOT/sow-copilot` | Held; no lock/full agent install |
| `/Users/pabs/Sites/COPILOT/docs` | Held; not a Git repository, nonstandard install |
| `/Users/pabs/Sites/CSE/claude-copilot-accounting` | Ecosystem tier, not a consumer target |
| `/Users/pabs/Sites/CSE/claude-copilot-internal` | Ecosystem tier, not a consumer target |
| `/Users/pabs/Sites/CSE/cli-copilot` | Ecosystem foundation, not a consumer target |
| `/Users/pabs/Sites/CSE/cli-copilot-internal` | Ecosystem tier, not a consumer target |
| `/Users/pabs/Sites/CSE/knowledge-copilot-internal` | Ecosystem tier, not a consumer target |
| `/Users/pabs/Sites/CSE/claude-copilot-private` | Held; 17 dirty paths |
| `/Users/pabs/Sites/CSE/cli-copilot-accounting` | Held; 17 dirty paths |
| `/Users/pabs/Sites/CSE/cli-copilot-private` | Held; 17 dirty paths |
| `/Users/pabs/Sites/CSE/codex-copilot-accounting` | Held; 17 dirty paths |
| `/Users/pabs/Sites/CSE/codex-copilot-internal` | Held; 2 dirty paths |
| `/Users/pabs/Sites/CSE/codex-copilot-private` | Held; 17 dirty paths |
| `/Users/pabs/Sites/CSE/copilot-bench` | Held; 13 dirty paths |
| `/Users/pabs/Sites/CSE/copilot-control-tower` | Held; 18 dirty paths |
| `/Users/pabs/Sites/CSE/cse-101` | Held; 3 dirty paths |
| `/Users/pabs/Sites/CSE/knowledge-copilot` | Held; 17 dirty paths |
| `/Users/pabs/Sites/CSE/knowledge-copilot-accounting` | Held; 17 dirty paths |
| `/Users/pabs/Sites/CSE/knowledge-copilot-private` | Held; 20 dirty paths |
| `/Users/pabs/Sites/CSE/product-creation-copilot` | Held; 17 dirty paths |
| `/Users/pabs/Sites/CSE/claude-copilot` | Authoring source; existing and session changes preserved |
| `/Users/pabs/Sites/CSE/codex-copilot` | Clean authoring source; not reverted to old pin |
| `/Users/pabs/Sites/CSE/shared-docs` | Symlink to knowledge-copilot-internal, not a second target |

TASK-47 remains owner-dependent for macOS application packaging: the actual
foundation private key `/Users/pabs/.ssh/enac_foundation_release` is absent.
No substitute key, signature override, package publication or credential read was
used. TASK-33 remains open for a frozen baseline/candidate trial with a real
reviewer. Mechanical passes are not evidence of improved model effectiveness.

Execution artifacts are retained under
`.copilot/evidence/testing-rethink-20260908/` and referenced from `tc` work products.
No global QA-policy rewrite, CI consolidation, consumer rollout or hosted-browser
purchase was performed. Those are distinct adoption/release decisions, not hidden
side effects of this investigation.
