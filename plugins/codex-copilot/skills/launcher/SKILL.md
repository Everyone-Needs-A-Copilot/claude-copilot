---
name: launcher
description: Use when you want to invoke codex-copilot specialist agents natively in Codex, either by selecting the right specialist skill for the main session or by mapping specialists onto real Codex spawned-agent roles for delegated work.
---

# Launcher

Use this skill to launch codex-copilot specialists in a Codex-native way.

## Native Modes

### Coordinator Session

The main session is a coordinator (see `$parallel-execution`): it never applies a specialist skill itself. It briefs each dispatched agent to load one of these specialist skills:

- `$ta`
- `$me`
- `$qa`
- `$sec`
- `$doc`
- `$do`
- `$sd`
- `$uxd`
- `$uids`
- `$uid`
- `$ind`

### Delegated Subagent

For useful independent work within the approved plan, dispatch by default using a real native `spawn_agent`. Use these role hints only when the current runtime supports them; otherwise give the native agent the specialist skill and scope:

- `explorer`: `ta`, `qa`, `sec`
- `worker`: `me`, `uid`, `do`
- `default`: `sd`, `uxd`, `uids`, `ind`, `doc`

## Required Behavior

1. choose the workflow
2. ensure `tc` task context exists for substantial work
3. dispatch every read, edit and work command to an agent; the main session keeps only coordinator-allowlist work, with no size-based exceptions
4. if spawning, each subagent has one specialist identity and one bounded task, but a stage may dispatch several same-role subagents on disjoint partitions
5. refill available capacity as independent work becomes ready; keep actual cwd, branch, task and agent receipts
6. use one integrator and independent scoped QA plus cross-stream checks, preserving source freshness
7. follow `../protocol/references/parallel-execution.md`; route T3 implementation through `qa` and retain proportional T1/T2 attestation

Read `references/workflows.md` for the standard sequences.

## Work Lifecycle

Apply the [shared work lifecycle](../cleanup/references/work-lifecycle.md) once
per task, including direct invocation of this skill: start/resume, maintain,
pause/handoff, finish and later reuse. Keep the checkpoint proportional in the
existing record; a small answer does not need a new task or document.
