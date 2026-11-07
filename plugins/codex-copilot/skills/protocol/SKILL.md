---
name: protocol
description: Use as the primary Codex Copilot entrypoint for new work. It classifies the request, chooses the right specialist workflow, creates tc-backed planning context when needed, and routes execution through codex-copilot agents similarly to Claude Copilot's /protocol command.
---

# Protocol

`$protocol` is the primary Codex Copilot entrypoint for new work.

Use it at the start of a task to decide how the work should proceed.

## Purpose

It should behave like the Claude Copilot `/protocol` command in intent:

- classify the request
- choose the correct specialist workflow
- require the right kind of thinking before implementation
- route the work through the correct agents

In Codex, that means:

- dispatch the specialist lens to an agent; the main session is a coordinator and never applies it itself
- from the first turn, split the request into independent streams and dispatch them through native `spawn_agent`; read-only work needs no approval wait, approval gates apply only before writes, outward actions and spending
- use `tc` as the durable record for substantial work

## Repository Decision Instruments

Before routing substantial work, check whether the repository defines its own decision instruments:

- If a root `SOUL.md` exists, read it before substantial product-facing work. Use it to decide whether the product direction should be built, reshaped, or rejected before specialist routing continues.
- If `docs/01-architecture/12-architecture-guiding-principles.md` exists, read it before durable technical, architecture, migration, data, security, performance, AI pipeline, or productized implementation work. Use it as the technical decision lens.

Keep these instruments separate:

- `SOUL.md` answers whether the product direction fits the product's purpose, taste, anti-patterns, and quality bar.
- architecture principles answer how accepted product direction should be built safely, scalably, efficiently, and securely.

## Request Classification

| Request type | Signals | Workflow |
|--------------|---------|----------|
| defect | broken behavior, regression, failing tests, bug fix | `bug` |
| technical | architecture, refactor, backend, migration, optimization | `technical_feature` |
| experience | user-facing feature, workflow, screen, UI, UX | `experience_feature` |
| physical-digital | hardware, connected product, tangible service touchpoint, physical object plus software | `physical_digital_feature` |
| UI polish | visual refinement, component styling, layout polish | `ui_polish` |
| security-sensitive | auth, permissions, secrets, trust boundaries | `security_sensitive` |
| infrastructure | CI, deploy, environment, observability, worktrees, release automation | `infrastructure` |
| ambiguous | improve, update, change, enhance without clear direction | ask for clarification before routing |

## Required behavior

0. coordinator rule first (`$parallel-execution`): dispatch read-only streams immediately, before any tier or done block; the done block and tier gate writes, outward actions and spending, never dispatch itself, and T1 gets no exemption from dispatch. Then set the verification tier, using the Verification Tiers table in `../specialist-agents/references/verification-policy.md` (T1 copy, T2 structural, T3 foundational; `tc task tier <id> T1|T2|T3 --reason "<text>"`; from the diff, upward only, owner-only downgrades, untiered is T3); T1 is not substantial work and skips the done block, T2 and T3 add a sixth `Tier:` line. Before substantial work, post the five-line done block (Done means / Proven by / Not in scope / Assumptions / First example) and wait for one word; register it with `tc task contract <id> --from-done-block <file>` (see `references/checkpoints.md`)
1. check repository decision instruments when they apply
2. classify the task
3. state the workflow
4. ensure `tc` context exists for substantial work
5. load known references and memory when `cc` is configured
6. for third-party API work, require Live Docs before planning or implementation
7. record QA-required implementation tasks with `metadata.requiresQa=true`; `$qa` is required for T3 and escalations, T1/T2 finish with `tc task attest`
8. use `docs/40-initiatives/NN-slug/` for formal multi-phase initiative knowledge while keeping live execution state in `tc`
9. perform the next appropriate specialist step
10. do not jump straight to implementation when earlier specialist work is warranted
11. (runs from the first turn, not after approval, for read-only work) apply `references/parallel-execution.md`: validate the ready-work graph, dispatch within measured capacity, converge current evidence and prepare verified resource disposition

For experience work that does not materially change screens, components, or interface states, `$uid` may be skipped only when the checkpoint states why.

## Fixed Delivery Boundary

Before implementation, state the deliverable, required acceptance criteria,
affected consumers, verification lane/cap and exclusions in `tc`. Freeze this
batch scope; use the engineering/QA Proportional Verification fixed finish line.
After current source-bound QA approval (T3) or a valid tc attestation (T1/T2) satisfies every required criterion, close
the task, report completion and separately pending work, then stop. Unrelated
findings do not authorize another improvement cycle. Missing required evidence or
an exhausted cap remains incomplete; never weaken acceptance to declare completion.

## User-Facing Output

- Lead with what is now true—the answer, decision, result, or blocker—not what was investigated.
- Include only what the user needs to trust the result, decide, or act. Preserve required findings, uncertainty, citations, QA evidence, safety warnings, blockers, and next actions.
- Default to at most 6 sentences or 5 bullets; exceed that only when requested or required by risk, complexity, or completeness.
- Keep progress updates to one sentence: material result plus next active step.
- Completion reports have four lines: Works (with evidence), Unverified, Parked (task IDs), Decision needed (or “none”). No confidence percentages.
- Decisions lead with a recommendation; take it and report when every option is reversible within current authorization, and offer options only when a choice is irreversible, outward or budget-affecting.
- Omit preambles, generic closers, self-narration, repeated findings, evidence inventories, command traces, and chronology unless requested or necessary.
- Store detailed analysis and evidence in `tc` work products. Content outranks form; length never removes a required fact, artifact, verdict, identifier, or blocker.

## Unknowns

Every design-stage lens (`$sd`, `$uxd`, `$uids`, `$ind`, `$ta`) ends with an `unknowns:` line. `unknowns: none` is permitted and is a claim you own; omitting the line is not.

An unknown that would change the work escalates rather than being noted:

```
QUESTION: [the one thing that changes the answer]
RECOMMENDATION: [what you would do, and why]
CONTEXT: [why this cannot be resolved from what you were given]
```

One question, not a checklist. State the recommendation first; if every option is reversible within current authorization, take it and report instead of asking. Options appear only for irreversible, outward or budget-affecting choices, each with its consequence. `CONTEXT:` states what you already ruled out — that is what makes it a question rather than a request to be told what to do.

**Resolving a genuine ambiguity silently is a defect, not efficiency.** Measured on an identical brief carrying a real contradiction ("Level 4 finish throughout" against "Garage included"): the arm with no framework asked, got the answer, and priced 25 fewer labour hours. The arm running the full design chain asked nothing and priced a guess. Inferring an answer where the brief is undecided converts the user's decision into your hidden assumption and buries it in a deliverable, where it resurfaces as rework. Guessing is acceptable only when the guess is stated as one.

Every dispatched scope carries explicit assumptions and unresolved decisions. The coordinator reconciles them at convergence and surfaces decision-changing ambiguity; parallel workers must not turn an undecided owner choice into an implicit agreement.

## Checkpoints

For design-heavy flows, stop after major design stages unless the user clearly asked for uninterrupted execution.

Checkpoint stages:

- after `sd`
- after `uxd`
- after `uids`
- after `ta` when the plan materially shapes implementation

Design-flow checkpoints (`sd`, `uxd`, `uids`, and PRD or design approval) require explicit user approval: there is no auto-proceed. Everywhere else, when there is no real decision, state the outcome and proceed.

Each checkpoint follows `references/checkpoints.md`: outcome first, recommendation first, options only for irreversible, outward or budget-affecting choices, and no evidence inventory. Include soul, architecture, QA, or next-step context only when it changes the decision.

## Coordinator pattern

The main session never applies these skills itself; it briefs dispatched agents to load them:

- `$sd`
- `$uxd`
- `$uids`
- `$uid`
- `$ta`
- `$me`
- `$qa`
- `$ind`
- `$sec`
- `$doc`
- `$do`

Optional pack specialists (`kc`, `cco`, `cw`, `cs`, `cpa`) are activated per project when the user needs knowledge, creative, copywriting, customer success, or financial advisory work.

## Delegated pattern

Approved work uses `$launcher` to map useful independent scopes onto native Codex spawned-agent roles by default. Read `references/parallel-execution.md` before dispatch. `$orchestrate` is a deprecated compatibility redirect; orchestration is part of this protocol, not another owner-operated stage.

## Task Copilot

For substantial work:

- create or use a PRD/task in `tc`
- store long outputs as work products
- keep the main response concise

## References

Read `references/generated-workflows.md` for the catalog-derived specialist sequences,
`references/flows.md` for routing details, and `references/checkpoints.md` for checkpoint behavior.

<!-- cse-design-quality:start -->
## Design Quality Routing

For material product-facing work, carry one named surface contract through service/interaction design, visual design, implementation and QA. Use `cc design guide` for focused actions and `cc design context` for explicit source authority; retain the existing specialist chain and required walkthroughs. Record initial critique before detector evidence, inspect the rendered result, and leave approval to task-bound QA. Static findings and screenshot comparisons inform judgment; neither replaces behavioral verification.
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
Tier scope: the contract, identity and per-criterion packet above are the T3 path. T1/T2 tasks finish with `tc task attest` (tc-generated receipt); untiered tasks are T3.

A v1 packet for pending work must be migrated with a registered contract and
fresh verification. Historical completed records remain readable and explicitly
historical; they are not current strict QA evidence. cc design review/report
checks the named database's acceptance contract and source coverage; detector or
report readiness still never grants task approval. CLI/API and native adapters
share the same tc authority. Missing current capabilities require a verified tc
installation; legacy artifact inspection is not a current completion proof.
Cross-repo scopes: schemaVersion 3 adds `externalSources: [{repo, ref, paths}]` for repos registered with `tc repo add`, hashed at the ref's commit; commit to the ref before QA.
<!-- cse-evidence-v2:end -->

## Work Lifecycle

Apply the [shared work lifecycle](../cleanup/references/work-lifecycle.md) once
per task, including direct invocation of this skill: start/resume, maintain,
pause/handoff, finish and later reuse. Keep the checkpoint proportional in the
existing record; a small answer does not need a new task or document.

At start/resume (including a new PRD or initiative) and finish/merge/pause/handoff, proactively inspect relevant worktrees. During cleanup automatically retire only recorded, fully integrated, clean and inactive merged worktrees after identity, recovery, consumer and project-teardown checks; never remove the coordinator’s current tree. Preserve branch history and hold dirty, unmerged, drifted, active or unknown work with an owner and next action. Other deletion requires exact approval; continue unrelated work while that approval is pending.

For substantial QA-required work, include an observable `WORK-LIFECYCLE` (or
equivalent) criterion before acceptance is frozen. QA inspects the maintained
record, applicable lesson-to-decision/check evidence, recovery/retirement results
and explicit holds, using the shared lifecycle's acceptance guidance. A missing
checkpoint cannot pass on metadata or a bare approval. A verified, in-scope hold
can satisfy delivery checkpoint evidence while cleanup remains pending; it does
not establish a cleanup or product-quality success. Preserve frozen scope and
cumulative history for existing work.
