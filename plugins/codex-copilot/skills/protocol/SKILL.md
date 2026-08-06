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

- invoke specialist skills in the main session by default
- use `spawn_agent` only when the user explicitly asks for subagents or parallel execution
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

1. check repository decision instruments when they apply
2. classify the task
3. state the workflow
4. ensure `tc` context exists for substantial work
5. load known references and memory when `cc` is configured
6. for third-party API work, require Live Docs before planning or implementation
7. record QA-required implementation tasks with `metadata.requiresQa=true`
8. use `docs/40-initiatives/NN-slug/` for formal multi-phase initiative knowledge while keeping live execution state in `tc`
9. perform the next appropriate specialist step
10. do not jump straight to implementation when earlier specialist work is warranted
11. do not use `spawn_agent` unless the user explicitly asked for delegation or parallel work

For experience work that does not materially change screens, components, or interface states, `$uid` may be skipped only when the checkpoint states why.

## Checkpoints

For design-heavy flows, stop after major design stages unless the user clearly asked for uninterrupted execution.

Checkpoint stages:

- after `sd`
- after `uxd`
- after `uids`
- after `ta` when the plan materially shapes implementation

Each checkpoint should summarize:

- what was decided
- whether any applicable soul or architecture principle changed the direction
- what happens next
- what the user can correct before continuing

## Main-session pattern

Use these native skills directly:

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

If the user explicitly asks for delegation or parallel work, use `$launcher` to map the needed specialists onto native Codex spawned-agent roles.

## Task Copilot

For substantial work:

- create or use a PRD/task in `tc`
- store long outputs as work products
- keep the main response concise

## References

Read `references/generated-workflows.md` for the catalog-derived specialist sequences,
`references/flows.md` for routing details, and `references/checkpoints.md` for checkpoint behavior.
