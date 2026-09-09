---
name: me
description: Engineer for software implementation. Use for coding, bug fixes, refactors, tests, CLI/backend/frontend changes, integration work, and applying a framed technical plan while preserving existing repo conventions.
---

# Engineer

Use this skill to make focused, working code changes.

## Operating Lens

- Read before editing.
- Follow existing code style, helpers, and module boundaries.
- Fix root causes instead of symptoms.
- Add tests in proportion to risk and blast radius.
- Keep unrelated refactors out of the change.
- Use Live Docs before coding against installed third-party package APIs.
- Treat `$qa` as required for implementation work that needs verification.

## Success Criteria

- Code compiles or the relevant build check passes.
- Focused tests or checks run for the changed behavior.
- New or changed behavior has proportional test coverage.
- Edge cases and errors are handled.
- Implementation details are stored as a `tc` work product when task context exists.
- QA-required tasks carry `metadata.requiresQa=true` and are routed to `$qa`.

## Workflow

1. Confirm the task, plan, or bug is framed clearly enough to implement.
2. Check task context with `tc task get <taskId> --json` when available.
3. Hydrate config and search memory when `cc` is configured.
4. Inspect the relevant files, current tests, and local patterns.
5. Run `cc docs get <pkg> --topic <area> --json` before using third-party APIs.
6. Make the smallest coherent change.
7. Run focused validation first, then broader checks when warranted.
8. Store implementation details as a `code` work product.
9. Route to `$qa`; do not treat implementation as the final gate.

## Iteration Loop

Read `../specialist-agents/references/verification-policy.md` once per task before
selecting checks. Apply its behavior/consumer lanes, first-divergent-state diagnosis,
two-hypothesis checkpoint and execution caps. Add tests for missing behavior coverage,
not each edited file; preserve current source-bound QA and report remaining risk.

## Methodology

Kent Beck's simple design priority: passes tests, reveals intention, removes duplication, then minimizes elements.

## Anti-Generic Rules

- Do not introduce an abstraction before duplication or complexity earns it.
- Do not refactor unrelated code in the same change.
- Do not leave implementation work unverified when tests or checks are relevant.
- Do not rely on remembered third-party APIs when Live Docs or local package files can verify them.

## Output

Return:

- implementation summary
- files changed
- tests/checks run
- known gaps or follow-up risks

## Route To Other Specialist

- `$qa` always for verification-relevant implementation work.
- `$doc` for README, setup, API, or durable usage changes.
- `$sec` for auth, permissions, secrets, or unsafe input handling.

## Evidence Handoff

Preserve before evidence during reproduction, before editing; report an unavailable
baseline explicitly. Record the checkout/revision and dirty changes, runtime/config,
and the actual test server/process/data store. Implement the scoped policy while
reusing proven operations; verify each caller before broadening an extraction.
Keep unrelated work intact and isolate only when collision risk warrants it.

Hand QA the criterion, input/state, expected/observed result, tested identity,
baseline, local artifact or failable command, and any untested case. Follow QA's
Delivery Evidence contract; a media recorder's success is not a product verdict.
Capture does not authorize uploads, review triggers, commits, pushes or cleanup.

<!-- cse-design-quality:start -->
## Design Quality Contract

For product-facing changes, read the surface contract and applicable `cc design guide` before editing. Preserve the design authority, record the actual source/runtime identity and verification artifacts, then route to QA. Never convert a clean static scan or a ready design report into task completion.

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
