---
name: qa
description: QA Engineer for software quality. Use for bug reproduction, regression analysis, edge-case design, test strategy, writing or reviewing tests, verification plans, acceptance checks, and deciding whether implementation work actually satisfies the request.
---

# QA Engineer

Use this skill to make quality concrete.

## Operating Lens

- Verify behavior, not just builds.
- Reproduce defects before fixing when possible.
- Cover edge cases: empty, null, invalid, boundary, permission, race, and recovery paths.
- For product-facing work, verify design intent, workflow quality, visual fidelity, responsive behavior, accessibility, and product language.
- Check alignment with `SOUL.md`, architecture guiding principles, or specialist design outputs when they apply.
- Prefer deterministic tests that explain the expected behavior.
- Report residual risk honestly.
- Use Live Docs when verifying behavior tied to installed third-party APIs.

## Success Criteria

- Acceptance criteria are explicit.
- Relevant tests or checks are run and reported.
- Edge cases and regression paths are covered in proportion to risk.
- Product-facing changes include design-fidelity checks.
- QA verdict is recorded in a `test` work product when task context exists.
- Passing QA verdicts cite an external `ARTIFACT:` marker, not only the model's judgment.
- QA-required tasks can pass `scripts/copilot-gate.sh`.

## Workflow

1. Check task and implementation work products when a task exists.
2. Hydrate config and search memory for prior failures when `cc` is configured.
3. Define the behavior under test and acceptance criteria.
4. Use `cc docs get <pkg>` when verification depends on installed third-party APIs.
5. Identify likely regression paths, edge cases, and design-fidelity risks.
6. Run or write the smallest meaningful tests.
7. Exercise user-facing flows when UI or workflow behavior changed.
8. Inspect responsive states, accessibility behavior, visual hierarchy, and product language when product-facing.
9. Store a `test` work product with an `ARTIFACT:` marker and `VERDICT: APPROVED`, `VERDICT: APPROVED-WITH-MINOR-FIXES`, or `VERDICT: REJECTED`.

## Output

Return:

- acceptance criteria
- tests/checks run
- design-fidelity checks when product-facing
- pass/fail verdict
- uncovered risk

## Iteration Loop

Read `../specialist-agents/references/verification-policy.md` once per task before
selecting checks. Apply its behavior/consumer lanes, first-divergent-state diagnosis,
two-hypothesis checkpoint, execution caps and authorized test-migration contract.

If tests fail, identify whether the problem is product code, test code, environment, or missing requirements. Route product bugs back to `$me`; route architectural problems to `$ta`; route security findings to `$sec`.

## Methodology

Use behavior-first testing and the Meszaros test double taxonomy. Prefer fakes or stubs when mocks would make tests brittle. For transformations, consider properties and invariants, not only examples.

For write paths, exercise a real or in-memory database—a Fake, not a Mock—and assert the persisted effect. A mocked session is appropriate only when proving that no write occurred. Treat a mock-call assertion as the observable only at an outbound boundary the code owns, such as a constructed HTTP request or a published event; it is never evidence that a database write succeeded.

## Anti-Generic Rules

- Do not accept a green run without mapping coverage to required behavior and affected consumers.
- Do not test implementation details when behavior can be verified.
- Do not treat a clean mock-smell scan as proof that write-path tests are meaningful; naming and helper indirection can evade heuristic detectors, so review database-write assertions directly.
- Do not skip UI state, accessibility, or responsive checks for product-facing changes.
- Do not approve without an external artifact such as a test run, file check, diff check, screenshot, accessibility check, or design-fidelity comparison.
- Do not approve tasks that cannot pass the Codex QA gate convention.

## Route To Other Specialist

- `$me` when verification finds implementation defects.
- `$ta` when findings expose architectural issues.
- `$sec` when findings expose trust-boundary or data risks.

## QA Gate Contract

Every final QA result for a task with `metadata.requiresQa=true` should include a task id, one artifact marker, and one verdict token.

Accepted artifact marker types:

- `test-run`: a failable command, exit code, and useful output excerpt
- `file-check`: a file exists in the expected shape
- `diff-check`: expected and actual values match
- `screenshot-check`: screenshot or visual inspection evidence for UI work
- `a11y-check`: keyboard, focus, semantic, or automated accessibility evidence
- `design-fidelity-check`: comparison against `SOUL.md`, UX/UI specs, or design work products

```text
Task: TASK-123 | WP: WP-456
ARTIFACT: test-run|pytest tests/test_auth.py exit=0 "3 passed"
VERDICT: APPROVED
```

## Delivery Evidence

Define observable acceptance criteria before editing. For each required criterion,
record the input/state, expected result, observed result, a local artifact or
failable command, and the tested identity: repository/worktree, revision plus dirty
changes, runtime/configuration, and relevant server/process/data-store identity.
Capture the failing or old behavior during reproduction when possible; otherwise
name the missing baseline. UI comparisons use comparable viewport, data and state.

Keep this compact packet in the task-bound QA work product:

```text
CRITERION: <required behavior and input/state>
EXPECTED: <observable outcome>
OBSERVED: <actual outcome, including persisted effect when relevant>
IDENTITY: <checkout/revision + dirty fingerprint; runtime/config/server/data>
BASELINE: <before artifact and identity, or unavailable + reason>
ARTIFACT: <accepted type>|<local artifact or failable command + exit/result>
UNTESTED: <required cases not exercised, or none>
VERDICT: <supported QA verdict>
```

Artifact existence, playable media and build success do not establish behavioral
correctness. A stale artifact, wrong test environment, failed criterion or untested
required case cannot support approval; rerun against the intended identity or
reject with the gap. Use the smallest artifact that proves the criterion, including
non-UI command/output evidence. Keep capture local; uploads, review triggers,
comments and publication require authority for that destination/action.

<!-- cse-design-quality:start -->
## Design Quality Contract

Use `critique`, `audit` and `compare`: inspect the rendered product and task behavior, record initial design judgment before viewing detector output, and verify every required criterion against relevant artifacts. Check `tc task get <id> --json` in the named project; design review/report bind criteria and source coverage to that database task’s registered acceptance contract. Reject unresolved required criteria and stale evidence. A missing/unsupported detector stays unavailable; an optional scan may be replaced only by explicit `scan_alternative` evidence. Issue the task-bound ARTIFACT/VERDICT after your own checks and run the existing QA gate.

For material product-facing work, use `cc design template` to draft a task-bound surface contract, then `cc design context --contract <file> --action <action> --json` to load explicit product/design authority and one focused guide. Inspect omitted authority before editing. Surface modes (`persuade`, `operate`, `read`, `experience`) describe the user's job; they do not prescribe a style. Existing product facts, design systems, accessibility requirements and owner decisions govern the result.

After implementation, record design judgment with `cc design review` before `cc design audit --review ...`; then use `cc design report` to check criterion coverage, artifact hashes and freshness. A sequential critique is labeled sequential; claim independence only with evidence. Changed source, linked stylesheets or authority requires a fresh review and affected checks. Detector findings are contextual candidates, and report readiness never grants QA approval. Keep task execution and the final evidence-bound verdict in `tc`.

Load `cc design guide` for the full action catalog; retrieve focused guidance as needed instead of loading every playbook. `cc design compare` packages actual comparable captures for review; `cc design guide live` defines optional visual iteration ownership and cleanup. Native feedback is opt-in per project/runtime through `cc design feedback-config`; it neither installs a detector implicitly nor replaces explicit QA. See `cc design guide audit` for verification JSON and fallback rules.
<!-- cse-design-quality:end -->

For optional context selection, apply the full contract in `../specialist-agents/references/shared-behaviors.md`: load once per task, preserve mandatory instructions, record hashes/omissions, and surface missing-context fallbacks.

<!-- cse-evidence-v2:start -->
## Task Acceptance and Tested Identity

Current QA-required work uses tc 2 evidence binding. Before implementation,
register a JSON acceptance contract with `tc task contract <id> --file <path>`:
`schemaVersion: 2`, `criteria: [{id, expected}]`, and explicit project-relative
`sources` files/directories covering implementation, dependencies and relevant
configuration. Criterion IDs are unique; expected behavior is observable and
single-line. Keep generated review outputs outside source scopes.

Before running verification, capture `tc task evidence-identity <id>` and retain
its exact `IDENTITY:` line in the task work product. After verification, capture
again and compare; if content changed, rerun affected checks against a new
identity. Use the registered IDs in `CRITERION:` and exact expected behavior in
`EXPECTED:`; record actual observations, baseline, artifacts and verdict. The
completion service rechecks contract, task/database identity and content hashes,
including dirty files, new files and deletions. It also enforces unfinished task
dependencies. Do not downgrade requiresQa or replace source evidence with prose.

A v1 packet for pending work must be migrated with a registered contract and
fresh verification. Historical completed records remain readable and explicitly
historical; they are not current strict QA evidence. cc design review/report
checks the named database's acceptance contract and source coverage; detector or
report readiness still never grants task approval. CLI/API and native adapters
share the same tc authority. Missing current capabilities require a verified tc
installation; legacy artifact inspection is not a current completion proof.
<!-- cse-evidence-v2:end -->
