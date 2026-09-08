# Fast, visible, risk-based verification

> Mode: Initiative
>
> Status: Proposed — planning authorized; policy/runner implementation not started
>
> `tc` context: Claude Copilot PRD-5 / TASK-58

## What you get

A clear answer to **what is being checked, why, how long it has been running,
what failed, and what evidence supports the fix**. Small changes receive a small
but sufficient check. Releases retain broad verification. UI defects get a
repeatable scenario and comparable before/after video and trace.

This is a change to the way Claude and Codex select, execute and explain tests,
not a new hosted platform or a promise to eliminate defects. Existing pytest,
shell tests, Playwright and `tc` remain useful. Ordinary test execution does not
need a model call; agents investigate failures and interpret the results.

## Why this plan

The [measured review](../../30-operations/14-testing-rethink-evidence-and-recommendations.md)
found a portable `cc` batch taking 384.83 seconds and `tc` taking 24.59 seconds.
Repeated full runs, duplicated source rosters, stale fixtures and machine-specific
assumptions add avoidable work. Those measurements do not identify the complete
cause or token cost of earlier hours-long sessions.

The objective is **less repeated work and faster trustworthy feedback**, measured
on actual tasks. A reduced test count, a passing video recorder, or an agent's
confidence is not a success metric.

## The new daily workflow

```text
Change + acceptance criterion
  → select relevant checks and show the reason/budget
  → reproduce the failure and identify the shared cause
  → fix it; verify affected behavior and its consumers
  → retain source-bound evidence in tc
  → run broad verification once for the completed batch/release
```

For the seven-versus-nine-items example: record the returned IDs, required IDs,
and first transformation introducing the extras. Test that rule's meaningful
input partitions and the consuming boundary. Compare membership, not just count.
Several failures sharing that rule are one diagnostic group, not separate repair
loops. Independent failures remain separate defects.

After two falsified root-cause hypotheses, change the investigation: inspect the
actual enforcement path or first divergent state. Do not respond by generating
more speculative tests or restarting the full suite. A failing broad run produces
focused follow-up work; unchanged completed checks are not automatically repeated.

## Select the right lane

| Change | Required default | When to expand |
|---|---|---|
| Instructions, skills, routing | Parse, references, manifest membership, real hook/dispatch wiring | Changed model judgment: bounded behavioral scenario; release/pilot: held-out evaluation |
| Code logic or data transformation | Small reproducer plus relevant boundaries and affected callers | Shared API, serialization, concurrency or state transition |
| Storage, installation or reconciliation | Real disposable boundary: persisted output, failure/rollback, preservation, repeat no-op where relevant | Installer/schema/release changes: platform and immutable-snapshot lane |
| UI defect | Seeded Playwright scenario with semantic assertions and before/after recording | Shared component, navigation, auth or responsive change: affected journey/state matrix |
| Machine configuration | Explicit environment assessment, separate from portable product tests | Setup, deployment or a machine-affecting change; required release environments |
| Model effectiveness | Frozen paired baseline/candidate inputs and actual review | Routing, judgment or learning changes—not an unrelated code edit |

Unknown impact selects a broader named lane, never an empty selection. New tests
are required for missing behavior coverage, not merely because a source file was
edited. Evidence/parser, concurrency, transaction and safety tests stay in place.

## Implementation sequence and impact

| Phase | Deliverable / owner | What changes for you | Exit gate |
|---|---|---|---|
| 1. Align the rules | QA/engineering contracts in Claude and Codex; QA + architecture | No unconditional new-test requirement or twelve-pass repair ritual; each run has a reason and stop condition | Representative instruction, code, installer and UI changes select sufficient checks; uncovered shared changes expand scope |
| 2. Make runs visible and bounded | One local `cc` runner with pytest/shell/Playwright adapters; engineering + DevOps | Live progress, hard limits, concise failures, durable logs and artifact reuse | Timeout kills only owned processes; failures/skips remain visible; changed source or environment invalidates reuse; `tc` alone grants approval |
| 3. Remove duplicated execution | Suite ownership and immutable fixture reuse; DevOps + QA | One broad run per platform/candidate, fewer repeated installs | Discovered tests remain covered by the union of CI jobs; unique rollback/preservation/platform cases retained |
| 4. Prove the UI workflow | One opt-in consuming frontend pilot; its engineer + QA | Watch reproduction, inspect the defect, then view the same scenario succeeding | Original failure and fixed behavior use equivalent data, viewport and assertions; persistent regression; no healer-skipped pass |
| 5. Measure and adopt | A matched task sample and rollout decision; maintainer + QA | Adoption based on measured feedback/rework rather than optimism | Required evidence complete, unexplained failures visible, no known lost defect detection, measured reduction in repeated work |

See [phase scope and acceptance checks](phases/phase-plan.md) for implementation
boundaries. These are sequential adoption gates, not delivery-time estimates.

## What the runner will do

Proposed CLI surface—not available yet:

```text
cc verify plan --task <id> --base <review-base> --json
cc verify run --task <id> --plan <file> --json
cc verify status --run <id> --json
```

`plan` reports impact, selected commands/tests, exclusions and budget. `run`
executes those commands without model inference. `status` reads local artifacts;
there is no daemon or new server. Agents and humans use the same results.

The console shows phase, current case or command, elapsed time, completed counts,
failure summary and artifact path, with a heartbeat at least every 30 seconds.
Logs and JUnit/media stay outside source folders and outside chat. Reports separate
test execution, environment preparation, agent reasoning and human review; token
cost is reported only when the runtime supplies a real measurement.

Initial **execution caps**, to be calibrated by lane: 60 seconds for focused
checks, 180 seconds for affected integration checks, and 900 seconds for a broad
portable batch. These are maximums, not expected runtimes or promises. A cap means
`incomplete`, names the slow operation, and requires a recorded scope/cap decision
before another run. It never becomes green, silently restarts or spends on models.

Reuse requires the same relevant source and test hashes, selected cases, command,
dependencies, runtime, configuration and data identity. Reusing execution does
not reuse another task's approval: each task keeps its acceptance mapping and a
current `tc` identity. Non-hermetic machine/model runs are not cacheable by default.

## UI testing and tools

Start with local Playwright Test and a visible browser controlled by the existing
agent. Microsoft's [Playwright CLI](https://github.com/microsoft/playwright-cli)
supports headed browser sessions; its role is interaction/reproduction, while a
saved Playwright Test scenario provides the deterministic regression.

For a reported defect, retain trace and video on both the original failing run and
the successful verification. [Playwright recording configuration](https://playwright.dev/docs/test-use-options)
supports that; routine regressions can retain failures only. With retries disabled,
do not use `on-first-retry` as the sole trace policy.
[Trace Viewer](https://playwright.dev/docs/trace-viewer) adds action snapshots,
console and network evidence so a visual recording is not the entire diagnosis.

Agent assistance is optional and task-scoped. Do not add a mandatory chain of
planner/generator/healer agents. Playwright's documented
[test agents](https://playwright.dev/docs/test-agents) can author and repair tests;
a healer skipping broken functionality must remain an unresolved defect, not an
approved result. No agent may relax the product assertion to obtain a pass.

Use synthetic data and isolated accounts. Traces can contain application data and
credentials; keep them local/private with explicit retention and access controls.
No default upload, paid account or hosted browser is required. Evaluate hosted
execution only if this pilot shows browser availability or collaboration is the
bottleneck. The framework stays local; an application may opt into a provider.

## Adoption scorecard

First record a baseline on representative changes, then compare similar task
classes under the new workflow. Record slow, failed and incomplete cases as well
as successes; do not cherry-pick easy repairs.

- **Visibility:** every run has a reason, current operation, elapsed time and final
  status; all caps and skips are explained.
- **Repeat work:** count identical broad reruns, repeated installations and tests
  executed per resolved root cause; unchanged reruns should disappear by default.
- **Feedback:** median and tail time from reported defect to verified fix, split
  into execution, preparation, diagnosis and review. Initial adoption target:
  at least 30% lower median verification-cycle time on the matched sample,
  without worsening the measured tail. This is a target, not a result.
- **Quality:** replay the same held-out known defects against both workflows;
  retain detection of every required defect. Track escapes, reopenings, flakes,
  test maintenance and reviewed corrective work. Small samples cannot prove a
  defect-rate improvement; serious regressions stop rollout.
- **Cost:** record actual runtime/model usage where available; do not convert
  subprocess wall time or character counts into invented token costs.

Pilot on the foundations plus one consuming UI journey. Widen only after reviewing
the scorecard. Revert the lane-selection/CI policy if detection or required coverage
regresses; preserve the evidence and useful observability. No mass test deletion.

## Decisions, boundaries and unknowns

[ADR-001](decisions/ADR-001-bounded-verification.md) records the local-first runner,
single QA authority and rejected alternatives. [Retrospectives](retrospectives/README.md)
will contain measured outcomes once the pilot exists. Live work state belongs in
`tc`, not a duplicated Markdown task board.

Unknowns: the consuming frontend/journey for the UI pilot, its test-data reset
mechanism, cross-machine timings, historical token/rework cost, and whether the
new workflow improves held-out outcomes. None is grounds to buy tooling or claim
results now; the pilot choices are required before Phase 4 execution.
