# Phase implementation and verification contract

Planning record: PRD-5 / TASK-58. Foundation implementation is in TASK-60–63;
[operation and limits](01-foundation-implementation.md) distinguish implemented
source behavior from the remaining pilot and adoption work. Create
repo-local QA-required execution tasks and register exact source scopes before
editing each phase. Codex changes belong in the Codex foundation, then follow its
normal distribution path; editing Claude's vendored copy alone is not parity.

## Phase 1 — Proportional verification contract

Ownership: QA/architecture, then the respective foundation engineer.

- Claude: `.claude/agents/{me,qa}.md`, necessary shared behavior and protocol
  surfaces, their generated/distributed equivalents and relevant instruction tests.
- Codex: native `me`/`qa` skills and its test-integrity gate where contract
  migration needs a verifiable exception. Discover the actual gate before editing.
- Replace unconditional new-test/file-extension rules with behavior, risk and
  consumer-based selection. Retain required regression and meaningful boundary
  coverage. Replace repeated repair attempts with the two-hypothesis diagnostic
  checkpoint; the checkpoint is investigation, not automatic abandonment.
- Permit an authorized obsolete-contract migration only with old/new expectations,
  rationale, exact test diff and a negative control. Never waive all test integrity.
- Reduce duplicated always-loaded guidance while preserving mandatory contracts.
  The merge audit measured 232,590 bytes of agent content against a 204,014-byte
  absolute ceiling, and 27,699 always-loaded bytes against 26,268. These failures
  also occur with main's unchanged instruction content. Prefer shared references
  loaded once; do not reset the baseline merely to make the check green. Any new
  budget requires a deliberate, measured decision. Reconcile the separate deployed
  agent source before claiming runtime parity.

Verify: table-driven representative changes select the intended lanes; an
unmapped/shared change expands coverage; skill text does not trigger live model
tests merely because it changed; a behavioral routing change does. Broken
implementations and unexplained missing coverage still fail approval.

## Phase 2 — Observable local execution

Ownership: engineering in `tools/cc` plus DevOps adapters; QA verifies boundaries.

- Add a focused verification module/command to the existing `cc` CLI. Reuse
  subprocess and report infrastructure where suitable; do not build a scheduler,
  separate test framework, daemon or second task store.
- Define a versioned plan/result schema and small repository-owned lane manifests.
  These map checks and owners, not a second acceptance-criteria authority.
- Plan and run named argument arrays against an explicit working directory,
  isolated data/runtime and source identity. Treat manifest commands as executable
  project code, not trusted merely because an agent generated a plan.
- Write local start/result/heartbeat/log artifacts atomically. Include test IDs,
  skip/failure reasons, exit codes and owned process IDs. On timeout/cancellation,
  terminate only the runner's process group and preserve partial evidence.
- Build conservative content/environment-based execution reuse; keep tc approval
  task-bound. Reject missing or changed artifacts and never reuse incomplete runs.

Verify: real child-process fixtures for success, failure, timeout, cancellation,
partial output and child cleanup; unrelated process survives; no secrets in normal
summaries; source/test/dependency/config/data changes invalidate reuse. Identical
execution can be referenced by two tasks without cross-task approval. First
validate through one real pytest lane, then shell and Playwright adapters.

## Phase 3 — Suite ownership and cost reduction

Ownership: DevOps for workflows; QA/engineering for fixture optimization.

- Claude: assign one portable owner across `pytest-suites.yml` and
  `conformance.yml`; retain macOS-specific onboarding and real-machine lanes.
- Codex: name/time smoke subcommands and preserve structural agent-eval JSON;
  keep live model evaluations explicitly separate and opt-in where appropriate.
- Remove duplicate same-platform execution only after proving the discovered
  inventory is still covered. Keep discovery-based CI, not a hand-maintained
  file allowlist that can silently miss new tests.
- Profile measured hotspots first: roundtrip, snapshot installation, canonical
  transactions and knowledge-source fixtures. Share frozen source preparation,
  never mutable installed destinations or task databases.
- Separate loaded/idle performance measurements from correctness. Machine fixture
  disagreement receives an owner and an explicit corrected contract/configuration,
  not permanent silent quarantine.

Verify: CI test-selection union equals the intended discovered inventory; adding
a test makes it discoverable automatically; distinct OS coverage remains; actual
rollback, preservation, repeated no-op and bad-source cases still fail appropriately.
Record before/after suite timings and fixture preparation costs under comparable
load. Do not upgrade dependencies or rewrite unrelated tests in this phase.

## Phase 4 — One visible UI defect workflow

Ownership: the selected application's engineer and QA; framework supplies guidance
and runner adapter, not application assertions or test-data ownership.

Choose a real reproducible defect and seed/reset data. Capture the original failure
with stable state/viewport and semantic assertions. Fix product code, rerun the same
scenario, retain both recordings/traces and a regression test. Review the successful
outcome, console/network evidence, accessibility and responsive states as relevant.
Required behavior cannot become a skip or weakened assertion during healing.

Verify: failing baseline, passing candidate, equivalent fixtures, no production-data
mutation, private artifact handling, and the persistent test failing again when the
specific defect is deliberately reintroduced in a disposable negative-control copy.

## Phase 5 — Pilot decision and controlled rollout

Ownership: maintainer and QA. Freeze a representative mix of instructions, code,
installation and UI work, with common correctness criteria and held-out failures.
Record diagnosis/rework as well as process timing; distinguish machine and model
variability. Use the README scorecard. The existing human effectiveness trial is
not satisfied by these mechanical measurements.

Exit: reviewed comparison meets declared feedback targets, required detection is
retained, CI inventory is intact, and any unexplained failure blocks a green claim.
If results are inconclusive, retain the baseline policy and named evidence gap.
Roll back selection/CI changes independently of runner observability; keep all
measurements. Choose hosted browsers only after the UI pilot provides a concrete
infrastructure reason and the owner approves cost/data handling.
