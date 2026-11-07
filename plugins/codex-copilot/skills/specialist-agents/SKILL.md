---
name: specialist-agents
description: Use when you need specialist role guidance for architecture, engineering, QA, security, docs, devops, service design, UX, UI design, UI implementation, or industrial design in a Codex session or delegated subagent.
---

# Specialist Agents

This skill provides Codex-native specialist playbooks modeled on the original Claude Copilot team.

## Usage modes

### Local mode

Dispatch the immediate blocking stage's specialist lens to one or more same-role agents on disjoint partitions; coupled work goes to one agent, never the main session. No size-based exceptions.

### Delegated mode

Within the approved plan, pass one relevant specialist identity and bounded independent scope into each native `spawn_agent` task by default. Follow `../protocol/references/parallel-execution.md`; no separate delegation request is required.

Keep prompts short. Give the subagent:

- the role
- the exact task
- the files or surface area it owns
- the expected output

## Roles

Read `references/agent-playbooks.md` and `references/shared-behaviors.md`, then load only the role section you need.

Core roles:

- `sd`
- `uxd`
- `uids`
- `uid`
- `ta`
- `me`
- `qa`
- `ind`
- `sec`
- `doc`
- `do`

## Quality gates

- `me` should not be the only gate on code correctness
- `qa` should verify implementation work
- `sec` should review security-sensitive changes
- design work should precede UI implementation when the problem is not already well-defined

## Work Lifecycle

Apply the [shared work lifecycle](../cleanup/references/work-lifecycle.md) once
per task, including direct invocation of this skill: start/resume, maintain,
pause/handoff, finish and later reuse. Keep the checkpoint proportional in the
existing record; a small answer does not need a new task or document.
